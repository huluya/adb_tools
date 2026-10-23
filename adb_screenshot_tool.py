import ctypes
import io
import ctypes
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk


APP_TITLE = "ADB设备工具"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class AdbScreenshotTool:
    """设备截图、录屏与常用 ADB 操作。

    截图仍直接使用 `adb exec-out screencap -p`，避免经由投屏窗口二次取图。
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1280x820")
        self.root.minsize(1040, 680)
        self.root.configure(background="#f4f6f8")

        self.result_queue = queue.Queue()
        self.image = None
        self.preview_photo = None
        self.capture_busy = False
        self.recording = False
        self.record_process = None
        self.record_remote_path = None
        self.record_preview_stop_event = None
        self.record_preview_thread = None
        self.record_started_at = None
        self.record_timer_after_id = None
        self.record_elapsed_var = tk.StringVar(value="已录制 0 秒")
        self.log_capture_state = "idle"
        self.log_capture_process = None
        self.log_capture_started_at = None
        self.log_capture_timer_after_id = None
        self.log_capture_elapsed_var = tk.StringVar(value="已抓取 0 秒")
        self.log_capture_button = None
        self.file_directory_view = None
        self.mirror_process = None
        self.mirror_stop_requested = False
        self.mirror_window_handle = None
        self.artifact_paths = {}
        self.performance_state = "idle"
        self.performance_stop_event = None
        self.performance_thread = None
        self.performance_samples = []
        self.performance_baseline = {}
        self.performance_serial = None
        self.performance_package = None
        self.performance_started_at = None
        # 性能监测的实时日志直接显示在“当前操作”区域，同时也输出到启动该工具的控制台。
        self.performance_live_logs = []
        self.performance_live_phase = ""
        self.performance_ui_after_id = None

        # PyInstaller 的 onefile 运行时 __file__ 位于临时解压目录；产物必须放在 EXE 旁边。
        self.app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(self.app_dir, "captures")

        default_adb = self.find_adb()
        self.adb_var = tk.StringVar(value=default_adb)
        self.adb_is_embedded = bool(
            getattr(sys, "frozen", False)
            and os.path.normcase(os.path.abspath(default_adb)).startswith(
                os.path.normcase(os.path.abspath(getattr(sys, "_MEIPASS", "")))
            )
        )
        self.scrcpy_path = self.find_scrcpy()
        self.device_var = tk.StringVar()
        self.device_state_map = {}
        self.devices_refreshing = False
        self.wifi_host_var = tk.StringVar()
        self.wifi_port_var = tk.StringVar(value="5555")
        self.package_var = tk.StringVar()
        self.record_limit_var = tk.StringVar(value="180")
        self.status_var = tk.StringVar(value="准备就绪")

        self.build_ui()
        self.root.after(100, self.poll_results)
        self.refresh_devices()
        self.root.after(2500, self.auto_refresh_devices)

    @staticmethod
    def find_adb():
        executable_dir = os.path.dirname(os.path.abspath(sys.executable))
        # 单文件 EXE 的内置 Platform Tools 解压到 _MEIPASS；优先使用它，
        # 这样用户电脑无需安装或配置 adb。
        bundled_dir = getattr(sys, "_MEIPASS", "")
        known = [
            os.path.join(bundled_dir, "platform-tools", "adb.exe"),
            os.path.join(executable_dir, "platform-tools", "adb.exe"),
            r"C:\platform-tools\adb.exe",
            os.path.join(executable_dir, "adb.exe"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "adb.exe"),
        ]
        for path in known:
            if os.path.isfile(path):
                return path
        return shutil.which("adb") or "adb.exe"

    @staticmethod
    def find_scrcpy():
        executable_dir = os.path.dirname(os.path.abspath(sys.executable))
        bundled_dir = getattr(sys, "_MEIPASS", "")
        known = [
            os.path.join(bundled_dir, "scrcpy", "scrcpy.exe"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "scrcpy", "scrcpy-win64-v3.3.3", "scrcpy.exe"),
            os.path.join(executable_dir, "scrcpy.exe"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "scrcpy.exe"),
        ]
        for path in known:
            if os.path.isfile(path):
                return path
        return shutil.which("scrcpy") or "scrcpy.exe"

    def build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Accent.TButton", padding=(10, 5))

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(outer, text=APP_TITLE, font=("Microsoft YaHei UI", 14, "bold")).pack(anchor=tk.W)
        ttk.Label(outer, text="截图使用设备原生能力；投屏窗口支持鼠标和键盘操作。", font=("Microsoft YaHei UI", 9), foreground="#64748b").pack(anchor=tk.W, pady=(0, 5))

        workspace = ttk.Frame(outer)
        workspace.pack(fill=tk.BOTH, expand=True)
        # 左侧功能区约占 60%，右侧预览约占 35%，最后保留约 5% 留白。
        workspace.columnconfigure(0, weight=12)
        workspace.columnconfigure(1, weight=7)
        workspace.columnconfigure(2, weight=1)
        workspace.rowconfigure(0, weight=1)
        workspace.rowconfigure(1, weight=3)
        workspace.rowconfigure(2, weight=2)
        left = ttk.Frame(workspace)
        left.grid(row=0, column=0, rowspan=3, sticky=tk.NSEW, padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=3)
        left.rowconfigure(2, weight=2)
        right = ttk.Frame(workspace)
        right.grid(row=0, column=1, rowspan=3, sticky=tk.NSEW)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        connection = ttk.LabelFrame(left, text="连接相关", padding=9)
        connection.grid(row=0, column=0, sticky=tk.EW)
        ttk.Label(connection, text="设备").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        self.device_combo = ttk.Combobox(connection, textvariable=self.device_var, state="readonly")
        self.device_combo.grid(row=0, column=1, sticky=tk.EW, pady=3)
        ttk.Button(connection, text="刷新设备", command=self.refresh_devices).grid(row=0, column=2, padx=(8, 0), pady=3)
        ttk.Label(connection, text="无线连接").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=3)
        wireless = ttk.Frame(connection)
        wireless.grid(row=1, column=1, sticky=tk.W, pady=3)
        ttk.Entry(wireless, textvariable=self.wifi_host_var, width=29).pack(side=tk.LEFT)
        ttk.Label(wireless, text=" : ").pack(side=tk.LEFT)
        ttk.Entry(wireless, textvariable=self.wifi_port_var, width=7).pack(side=tk.LEFT)
        ttk.Button(wireless, text="USB 开启", command=self.enable_wireless).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(wireless, text="重启 ADB", command=self.restart_adb).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(connection, text="连接", command=self.connect_wireless).grid(row=1, column=2, padx=(8, 0), pady=3)
        connection.columnconfigure(1, weight=1)

        functions = ttk.LabelFrame(left, text="功能", padding=9)
        functions.grid(row=1, column=0, sticky=tk.NSEW, pady=(10, 0))
        functions.rowconfigure(0, weight=1)
        functions.columnconfigure(0, weight=1)
        functions_canvas = tk.Canvas(functions, borderwidth=0, highlightthickness=0, background="#f4f6f8")
        functions_scroll = ttk.Scrollbar(functions, orient=tk.VERTICAL, command=functions_canvas.yview)
        functions_canvas.configure(yscrollcommand=functions_scroll.set)
        functions_canvas.grid(row=0, column=0, sticky=tk.NSEW)
        functions_scroll.grid(row=0, column=1, sticky=tk.NS)
        functions_body = ttk.Frame(functions_canvas)
        functions_window = functions_canvas.create_window((0, 0), window=functions_body, anchor=tk.NW)

        def update_functions_scrollregion(_event=None):
            functions_canvas.configure(scrollregion=functions_canvas.bbox("all"))

        def resize_functions_body(event):
            functions_canvas.itemconfigure(functions_window, width=max(1, event.width))

        def scroll_functions(event):
            if event.delta:
                functions_canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta < 0 else 1), "units")

        functions_body.bind("<Configure>", update_functions_scrollregion)
        functions_canvas.bind("<Configure>", resize_functions_body)
        functions_canvas.bind("<MouseWheel>", scroll_functions)
        functions_body.bind("<MouseWheel>", scroll_functions)
        functions_canvas.bind("<Button-4>", lambda _event: functions_canvas.yview_scroll(-1, "units"))
        functions_canvas.bind("<Button-5>", lambda _event: functions_canvas.yview_scroll(1, "units"))

        tools = ttk.LabelFrame(functions_body, text="设备操作", padding=9)
        tools.pack(fill=tk.X)
        tool_buttons = ttk.Frame(tools)
        tool_buttons.pack(fill=tk.X)
        ttk.Button(tool_buttons, text="重启设备", command=self.reboot_device).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(tool_buttons, text="关机设备", command=self.poweroff_device).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(tool_buttons, text="获取当前应用", command=self.get_current_app).pack(side=tk.LEFT, padx=(24, 0))
        ttk.Button(tool_buttons, text="应用详情", command=self.show_package_info).pack(side=tk.LEFT, padx=(8, 0))
        package_row = ttk.Frame(tools)
        package_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(package_row, text="包名").pack(side=tk.LEFT)
        ttk.Entry(package_row, textvariable=self.package_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.performance_start_button = ttk.Button(package_row, text="开始性能监测", command=self.start_performance_monitoring)
        self.performance_start_button.pack(side=tk.LEFT, padx=(8, 0))
        self.performance_stop_button = ttk.Button(package_row, text="结束并生成报告", command=self.stop_performance_monitoring, state=tk.DISABLED)
        self.performance_stop_button.pack(side=tk.LEFT, padx=(8, 0))
        media = ttk.LabelFrame(functions_body, text="截图、录屏与投屏", padding=9)
        media.pack(fill=tk.X, pady=(10, 0))
        capture_row = ttk.Frame(media)
        capture_row.pack(fill=tk.X)
        self.capture_button = ttk.Button(capture_row, text="截图", style="Accent.TButton", command=self.capture)
        self.capture_button.pack(side=tk.LEFT)
        ttk.Label(capture_row, text="录屏最长").pack(side=tk.LEFT, padx=(24, 5))
        ttk.Spinbox(capture_row, from_=1, to=180, textvariable=self.record_limit_var, width=5).pack(side=tk.LEFT)
        ttk.Label(capture_row, text="秒").pack(side=tk.LEFT, padx=(4, 0))
        self.record_button = ttk.Button(capture_row, text="开始录屏", command=self.toggle_recording)
        self.record_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(capture_row, textvariable=self.record_elapsed_var, foreground="#52606d").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(capture_row, text="电脑投屏").pack(side=tk.LEFT, padx=(18, 0))
        self.mirror_button = ttk.Button(capture_row, text="开始投屏并控制", style="Accent.TButton", command=self.toggle_mirroring)
        self.mirror_button.pack(side=tk.LEFT, padx=(8, 0))

        file_ops = ttk.LabelFrame(functions_body, text="文件操作", padding=9)
        file_ops.pack(fill=tk.X, pady=(10, 0))
        file_row_one = ttk.Frame(file_ops)
        file_row_one.pack(fill=tk.X)
        ttk.Button(file_row_one, text="安装 APK…", command=self.install_apk).pack(side=tk.LEFT)
        ttk.Button(file_row_one, text="卸载应用", command=self.uninstall_package).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(file_row_one, text="清除应用数据", command=self.clear_package_data).pack(side=tk.LEFT, padx=(8, 0))
        file_row_two = ttk.Frame(file_ops)
        file_row_two.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(file_row_two, text="电脑传到手机", command=lambda: self.show_file_transfer_panel("push")).pack(side=tk.LEFT)
        ttk.Button(file_row_two, text="手机传到电脑", command=lambda: self.show_file_transfer_panel("pull")).pack(side=tk.LEFT, padx=(8, 0))
        file_row_three = ttk.Frame(file_ops)
        file_row_three.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(file_row_three, text="日志抓取（当前应用）").pack(side=tk.LEFT)
        self.log_capture_button = ttk.Button(file_row_three, text="开始日志抓取", command=self.toggle_log_capture)
        self.log_capture_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(file_row_three, textvariable=self.log_capture_elapsed_var, foreground="#52606d").pack(side=tk.LEFT, padx=(8, 0))

        bottom = ttk.Frame(left)
        bottom.grid(row=2, column=0, sticky=tk.NSEW, pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=3)
        bottom.rowconfigure(0, weight=1)
        artifact_frame = ttk.LabelFrame(bottom, text="文件（截图 / 录屏 / 报告 / 日志）", padding=6)
        artifact_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        self.artifact_tree = ttk.Treeview(artifact_frame, columns=("kind", "name"), show="headings", height=5)
        self.artifact_tree.heading("kind", text="类型")
        self.artifact_tree.heading("name", text="文件")
        self.artifact_tree.column("kind", width=68, stretch=False)
        self.artifact_tree.column("name", width=170, stretch=True)
        artifact_scroll = ttk.Scrollbar(artifact_frame, orient=tk.VERTICAL, command=self.artifact_tree.yview)
        self.artifact_tree.configure(yscrollcommand=artifact_scroll.set)
        self.artifact_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        artifact_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.artifact_tree.bind("<Button-3>", self.show_artifact_menu)

        operation_frame = ttk.LabelFrame(bottom, text="当前操作", padding=6)
        operation_frame.grid(row=0, column=1, sticky=tk.NSEW)
        self.operation_toolbar = ttk.Frame(operation_frame)
        self.operation_toolbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(self.operation_toolbar, text="复制内容", command=self.copy_operation_text).pack(side=tk.RIGHT)
        self.operation_body = ttk.Frame(operation_frame)
        self.operation_body.pack(fill=tk.BOTH, expand=True)
        self.operation_view = tk.Text(self.operation_body, height=8, width=28, wrap=tk.WORD, font=("Microsoft YaHei UI", 9), undo=False)
        self.operation_view.insert("1.0", "设备信息（当前选择的）\n\n正在等待设备连接…")
        self.operation_view.configure(state=tk.DISABLED, background="#f7f9fb", relief=tk.FLAT)
        self.operation_scroll = ttk.Scrollbar(self.operation_body, orient=tk.VERTICAL, command=self.operation_view.yview)
        self.operation_view.configure(yscrollcommand=self.operation_scroll.set)
        self.operation_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.operation_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.operation_view.bind("<Button-3>", self.show_operation_menu)
        self.device_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_device_info())

        preview_frame = ttk.Frame(right, padding=8)
        preview_frame.grid(row=0, column=0, sticky=tk.NSEW)
        self.preview_host = preview_frame
        self.preview = tk.Label(preview_frame, text="点击“截图”获取设备当前画面\n开始录屏后这里会实时显示设备画面", background="#20252b", foreground="#d9e2ec", font=("Microsoft YaHei UI", 10), justify=tk.CENTER)
        self.preview.pack(fill=tk.BOTH, expand=True)
        self.preview.bind("<Configure>", lambda _event: self.render_preview())
        self.preview.bind("<Button-3>", self.show_image_menu)
        preview_frame.bind("<Configure>", lambda _event: self.root.after_idle(self.resize_embedded_mirror))
        status = ttk.Frame(outer)
        status.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(status, textvariable=self.status_var, foreground="#52606d").pack(side=tk.LEFT)
        ttk.Label(status, text="截图、录屏文件可在右侧列表右键复制", foreground="#7b8794").pack(side=tk.RIGHT)

    def choose_adb(self):
        path = filedialog.askopenfilename(title="选择 adb.exe", filetypes=[("ADB 可执行文件", "adb.exe"), ("所有文件", "*.*")])
        if path:
            self.adb_var.set(path)
            self.refresh_devices()

    def selected_serial(self):
        display = self.device_var.get().strip()
        if not display:
            messagebox.showwarning(APP_TITLE, "请先选择一个状态为 device 的设备。")
            return None
        record = self.device_state_map.get(display)
        if record:
            serial, state = record
            if state != "device":
                if state == "unauthorized":
                    messagebox.showwarning(APP_TITLE, f"设备 {serial} 尚未授权。\n请在手机上确认“允许 USB 调试”，然后点击刷新设备。")
                else:
                    messagebox.showwarning(APP_TITLE, f"设备 {serial} 当前状态为 {state}，请检查连接后点击刷新设备。")
                return None
            return serial
        serial = display
        return serial

    def run_adb(self, args, timeout=15):
        adb = self.adb_var.get().strip().strip('"')
        if not adb:
            raise RuntimeError("ADB 路径为空")
        return subprocess.run([adb] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, creationflags=CREATE_NO_WINDOW)

    @staticmethod
    def command_error(result, fallback):
        detail = result.stderr.decode("utf-8", "replace").strip()
        return detail or fallback

    def start_worker(self, description, worker):
        self.status_var.set(description)
        threading.Thread(target=worker, daemon=True).start()

    def auto_refresh_devices(self):
        self.refresh_devices(silent=True)
        self.root.after(2500, self.auto_refresh_devices)

    def refresh_devices(self, silent=False):
        if self.devices_refreshing:
            return
        self.devices_refreshing = True
        def worker():
            try:
                result = self.run_adb(["devices"], timeout=10)
                if result.returncode != 0:
                    raise RuntimeError(self.command_error(result, "adb devices 执行失败"))
                devices = []
                state_map = {}
                for line in result.stdout.decode("utf-8", "replace").splitlines():
                    parts = line.split()
                    if len(parts) < 2 or parts[0] == "List":
                        continue
                    serial, state = parts[0], parts[1]
                    if state == "device":
                        display = serial
                    elif state == "unauthorized":
                        display = f"{serial}（未授权）"
                    elif state == "offline":
                        display = f"{serial}（离线）"
                    else:
                        display = f"{serial}（{state}）"
                    devices.append(display)
                    state_map[display] = (serial, state)
                self.result_queue.put(("devices", (devices, state_map, silent), None))
            except Exception as exc:
                self.result_queue.put(("devices_error", (silent, str(exc)), None))
        if silent:
            threading.Thread(target=worker, daemon=True).start()
        else:
            self.start_worker("正在读取设备…", worker)

    def connect_wireless(self):
        host, port = self.wifi_host_var.get().strip(), self.wifi_port_var.get().strip() or "5555"
        if not host:
            messagebox.showwarning(APP_TITLE, "请输入设备的 IP 地址。")
            return
        def worker():
            try:
                result = self.run_adb(["connect", f"{host}:{port}"], timeout=15)
                text = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
                if result.returncode != 0:
                    raise RuntimeError(text or "无线连接失败")
                self.result_queue.put(("refresh_after_status", text or "已发送连接请求", None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker(f"正在连接 {host}:{port}…", worker)

    def enable_wireless(self):
        """通过当前 USB ADB 连接把设备切换到经典 TCP/IP ADB 模式。"""
        serial = self.selected_serial()
        if not serial:
            return
        port = self.wifi_port_var.get().strip() or "5555"
        try:
            if not 1 <= int(port) <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_TITLE, "端口必须是 1 到 65535 之间的数字。")
            return

        def worker():
            try:
                result = self.run_adb(["-s", serial, "tcpip", port], timeout=20)
                text = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
                if result.returncode != 0:
                    raise RuntimeError(text or "无法开启无线 ADB，请确认设备当前通过 USB 连接并已授权")
                self.result_queue.put(("status", text or f"无线 ADB 已开启，端口 {port}；现在可拔掉 USB 后点击“连接”", None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker(f"正在通过 USB 开启无线 ADB（端口 {port}）…", worker)

    def capture(self):
        serial = self.selected_serial()
        if not serial or self.capture_busy:
            return
        self.capture_busy = True
        self.capture_button.configure(state=tk.DISABLED)
        def worker():
            try:
                result = self.run_adb(["-s", serial, "exec-out", "screencap", "-p"], timeout=20)
                if result.returncode != 0:
                    raise RuntimeError(self.command_error(result, "截图命令执行失败"))
                image = Image.open(io.BytesIO(result.stdout)).convert("RGB")
                image.load()
                # 每次点击“截图”都自动保存到 captures，并加入文件列表；
                # 投屏时仍不刷新右侧预览，避免打断正在显示的投屏画面。
                os.makedirs(self.output_dir, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
                path = os.path.join(self.output_dir, f"screen-shot-{stamp}.png")
                image.save(path, "PNG")
                self.result_queue.put(("image_saved", (path, image.width, image.height, image), None))
            except Exception as exc:
                self.result_queue.put(("capture_error", None, str(exc)))
        self.start_worker("正在截图…", worker)

    def start_recording(self):
        serial = self.selected_serial()
        if not serial or self.recording:
            return
        try:
            limit = int(self.record_limit_var.get())
            if not 1 <= limit <= 180:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_TITLE, "录屏时长请输入 1 到 180 之间的秒数。")
            return
        os.makedirs(self.output_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.record_remote_path = f"/sdcard/adb-tool-{stamp}.mp4"
        local_path = os.path.join(self.output_dir, f"screen-record-{stamp}.mp4")
        try:
            self.record_process = subprocess.Popen([self.adb_var.get().strip().strip('"'), "-s", serial, "shell", "screenrecord", "--time-limit", str(limit), "--bit-rate", "8000000", self.record_remote_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"无法启动录屏：{exc}")
            return
        self.recording = True
        self.record_started_at = time.monotonic()
        self.record_elapsed_var.set("已录制 0 秒")
        self.record_button.configure(text="结束录屏", state=tk.NORMAL)
        self.update_record_elapsed()
        if self.mirror_process is not None:
            self.status_var.set(f"正在录屏（最长 {limit} 秒，结束后自动保存到文件列表）…")
            self.record_preview_stop_event = None
            self.record_preview_thread = None
        else:
            self.status_var.set(f"正在录屏（最长 {limit} 秒）…")
            self.record_preview_stop_event = threading.Event()
            self.record_preview_thread = threading.Thread(
                target=self.record_preview_worker,
                args=(serial, self.record_preview_stop_event),
                daemon=True,
            )
            self.record_preview_thread.start()
        threading.Thread(target=self.record_wait_worker, args=(self.record_process, serial, self.record_remote_path, local_path), daemon=True).start()

    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def update_record_elapsed(self):
        if not self.recording or not self.record_started_at:
            self.record_timer_after_id = None
            return
        elapsed = max(0, int(time.monotonic() - self.record_started_at))
        self.record_elapsed_var.set(f"已录制 {elapsed} 秒")
        self.record_timer_after_id = self.root.after(250, self.update_record_elapsed)

    def record_preview_worker(self, serial, stop_event):
        """录屏期间低频抓取预览帧，视频文件仍由设备端 screenrecord 负责。"""
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                result = self.run_adb(["-s", serial, "exec-out", "screencap", "-p"], timeout=10)
                if result.returncode == 0:
                    image = Image.open(io.BytesIO(result.stdout)).convert("RGB")
                    image.load()
                    self.result_queue.put(("record_preview", image, None))
            except Exception:
                # 录屏预览失败不影响正在生成的视频，下一轮继续尝试。
                pass
            stop_event.wait(max(0.2, 0.7 - (time.monotonic() - started)))

    def stop_record_preview(self):
        stop_event = self.record_preview_stop_event
        preview_thread = self.record_preview_thread
        self.record_preview_stop_event = None
        self.record_preview_thread = None
        if stop_event:
            stop_event.set()
        if preview_thread and preview_thread is not threading.current_thread():
            preview_thread.join(timeout=3)

    def record_wait_worker(self, process, serial, remote_path, local_path):
        try:
            process.wait()
            self.stop_record_preview()
            result = self.run_adb(["-s", serial, "pull", remote_path, local_path], timeout=120)
            if result.returncode != 0 or not os.path.isfile(local_path) or os.path.getsize(local_path) == 0:
                raise RuntimeError(self.command_error(result, "录屏文件拉取失败"))
            self.result_queue.put(("record_done", local_path, None))
        except Exception as exc:
            self.result_queue.put(("record_error", None, str(exc)))

    def stop_recording(self):
        if not self.recording:
            return
        serial = self.selected_serial()
        if not serial:
            return
        self.record_button.configure(text="正在保存录屏…", state=tk.DISABLED)
        if self.record_preview_stop_event:
            self.record_preview_stop_event.set()
        def worker():
            try:
                result = self.run_adb(["-s", serial, "shell", "pkill", "-INT", "screenrecord"], timeout=12)
                if result.returncode != 0 and self.record_process and self.record_process.poll() is None:
                    self.record_process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
                self.result_queue.put(("status", "正在保存录屏文件…", None))
            except Exception as exc:
                # 即使停止指令失败，进程仍可能已自然结束，等待线程会给出最终结果。
                self.result_queue.put(("status", f"停止指令异常，仍在尝试保存：{exc}", None))
        self.start_worker("正在停止录屏…", worker)

    def start_mirroring(self):
        serial = self.selected_serial()
        if not serial or self.mirror_process is not None:
            return
        scrcpy = self.scrcpy_path
        if not scrcpy or not os.path.isfile(scrcpy):
            self.status_var.set("投屏组件不可用")
            self.set_operation_text("请重新获取完整版本的程序。", "投屏失败")
            return
        try:
            environment = os.environ.copy()
            # scrcpy 会启动自己的 adb 子进程，明确指向同一份随程序提供的 adb。
            environment["ADB"] = self.adb_var.get().strip().strip('"')
            server_path = os.path.join(os.path.dirname(scrcpy), "scrcpy-server")
            if not os.path.isfile(server_path):
                raise RuntimeError("找不到 scrcpy-server")
            # scrcpy 3.x 通过环境变量指定 server，旧版的 --server 参数会导致直接退出。
            environment["SCRCPY_SERVER_PATH"] = server_path
            self.preview_host.update_idletasks()
            initial_width, initial_height = self.get_preview_host_size()
            command = [
                scrcpy,
                "-s",
                serial,
                "--window-borderless",
                f"--window-width={max(320, initial_width)}",
                f"--window-height={max(240, initial_height)}",
                "--window-title",
                f"ADB 投屏 - {serial}",
            ]
            self.mirror_stop_requested = False
            self.mirror_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                env=environment,
                cwd=os.path.dirname(scrcpy),
            )
        except Exception as exc:
            self.mirror_process = None
            self.mirror_button.configure(text="开始投屏并控制", state=tk.NORMAL)
            self.status_var.set("投屏启动失败")
            self.set_operation_text(str(exc), "投屏失败")
            return
        self.mirror_button.configure(text="正在启动投屏…", state=tk.DISABLED)
        self.status_var.set("正在启动投屏并嵌入右侧预览区…")
        threading.Thread(target=self.watch_mirror_process, args=(self.mirror_process,), daemon=True).start()

    def toggle_mirroring(self):
        if self.mirror_process is not None:
            self.stop_mirroring()
        else:
            self.start_mirroring()

    @staticmethod
    def find_mirror_window(process, timeout=10):
        """通过进程 PID 找到 scrcpy 创建的 SDL 窗口。"""
        if sys.platform != "win32":
            return None
        user32 = ctypes.windll.user32
        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [enum_proc_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = []

            def enum_window(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == process.pid:
                    found.append(hwnd)
                    return False
                return True

            callback = enum_proc_type(enum_window)
            user32.EnumWindows(callback, 0)
            if found:
                return found[0]
            if process.poll() is not None:
                break
            time.sleep(0.05)
        return None

    def embed_mirror_window(self, process, hwnd):
        """把 scrcpy 的无边框窗口改成右侧预览框的子窗口。"""
        if process is not self.mirror_process or sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        child_hwnd = wintypes.HWND(hwnd)
        host_hwnd = wintypes.HWND(self.preview_host.winfo_id())
        gwl_style = -16
        ws_child = 0x40000000
        ws_popup = 0x80000000
        ws_caption = 0x00C00000
        ws_thickframe = 0x00040000
        ws_minimizebox = 0x00020000
        ws_maximizebox = 0x00010000
        ws_sysmenu = 0x00080000
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.SetParent.restype = wintypes.HWND
        user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
        user32.MoveWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        style = int(user32.GetWindowLongPtrW(child_hwnd, gwl_style))
        style = (style & ~(ws_popup | ws_caption | ws_thickframe | ws_minimizebox | ws_maximizebox | ws_sysmenu)) | ws_child
        user32.SetWindowLongPtrW(child_hwnd, gwl_style, ctypes.c_void_p(style))
        if not user32.SetParent(child_hwnd, host_hwnd):
            raise RuntimeError("无法把投屏窗口嵌入预览区域")
        self.mirror_window_handle = int(hwnd)
        self.preview.pack_forget()
        self.resize_embedded_mirror()
        user32.ShowWindow(child_hwnd, 5)
        user32.SetFocus(child_hwnd)
        self.status_var.set("投屏已嵌入右侧预览区：可直接用鼠标和键盘控制设备")

    def get_preview_host_size(self):
        """读取预览容器的原生客户区尺寸，避免 DPI 缩放导致投屏只占一半。"""
        width = max(1, self.preview_host.winfo_width())
        height = max(1, self.preview_host.winfo_height())
        if sys.platform != "win32":
            return width, height
        try:
            user32 = ctypes.windll.user32
            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
            user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
            user32.GetClientRect.restype = wintypes.BOOL
            rect = RECT()
            if user32.GetClientRect(wintypes.HWND(self.preview_host.winfo_id()), ctypes.byref(rect)):
                width = max(1, int(rect.right - rect.left))
                height = max(1, int(rect.bottom - rect.top))
        except Exception:
            pass
        return width, height

    def resize_embedded_mirror(self):
        if not self.mirror_window_handle or sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            width, height = self.get_preview_host_size()
            # SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW
            user32.SetWindowPos(wintypes.HWND(self.mirror_window_handle), None, 0, 0, width, height, 0x0004 | 0x0010 | 0x0040)
        except Exception:
            pass

    def clear_preview(self):
        """清空右侧预览缓存，避免录屏/投屏结束后继续显示旧画面。"""
        self.image = None
        self.preview_photo = None
        self.preview.configure(image="", text="点击“截图”获取设备当前画面\n开始录屏后这里会实时显示设备画面")

    def restore_preview_after_mirror(self):
        self.mirror_window_handle = None
        if self.preview.winfo_manager() != "pack":
            self.preview.pack(fill=tk.BOTH, expand=True)
        self.clear_preview()

    def watch_mirror_process(self, process):
        hwnd = self.find_mirror_window(process)
        if hwnd:
            self.result_queue.put(("mirror_embed", (process, hwnd), None))
        process.wait()
        try:
            output = process.stdout.read().decode("utf-8", "replace").strip() if process.stdout else ""
        except Exception:
            output = ""
        self.result_queue.put(("mirror_closed", (process, process.returncode, output), None))

    def stop_mirroring(self):
        if self.mirror_process is not None:
            self.mirror_stop_requested = True
            self.mirror_button.configure(text="正在关闭投屏…", state=tk.DISABLED)
            self.mirror_process.terminate()
            self.status_var.set("正在关闭投屏…")

    def load_device_info(self):
        """自动读取当前选择设备的信息，并显示在底部的当前操作区域。"""
        display = self.device_var.get().strip()
        if not display:
            self.set_operation_text("设备信息（当前选择的）\n\n暂无在线设备。")
            return
        record = self.device_state_map.get(display)
        if record:
            serial, state = record
            if state != "device":
                hint = "请在手机上确认“允许 USB 调试”，确认后点击刷新设备。" if state == "unauthorized" else "请检查设备连接后点击刷新设备。"
                self.set_operation_text(f"设备：{serial}\n状态：{state}\n\n{hint}", "设备信息（当前选择的）")
                return
        else:
            serial = display
        def worker():
            try:
                fields = [("型号", "ro.product.model"), ("Android", "ro.build.version.release"), ("品牌", "ro.product.manufacturer")]
                lines = [f"序列号：{serial}"]
                for label, prop in fields:
                    result = self.run_adb(["-s", serial, "shell", "getprop", prop], timeout=10)
                    lines.append(f"{label}: {result.stdout.decode('utf-8', 'replace').strip()}")
                size = self.run_adb(["-s", serial, "shell", "wm", "size"], timeout=10)
                lines.append(size.stdout.decode("utf-8", "replace").strip())
                self.result_queue.put(("text", ("设备信息（当前选择的）", "\n".join(lines)), None))
            except Exception as exc:
                self.result_queue.put(("operation_error", "设备信息读取失败", str(exc)))
        self.start_worker("正在读取当前设备信息…", worker)

    def restart_adb(self):
        def worker():
            try:
                result = self.run_adb(["kill-server"], timeout=10)
                if result.returncode != 0:
                    raise RuntimeError(self.command_error(result, "无法停止 ADB 服务"))
                self.run_adb(["start-server"], timeout=10)
                self.result_queue.put(("refresh_after_status", "ADB 已重启", None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker("正在重启 ADB…", worker)

    def run_device_power_action(self, args, description):
        serial = self.selected_serial()
        if not serial:
            return
        def worker():
            try:
                result = self.run_adb(["-s", serial] + list(args), timeout=20)
                if result.returncode != 0:
                    raise RuntimeError(self.command_error(result, f"{description}失败"))
                self.result_queue.put(("status", f"已发送{description}指令", None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker(f"正在{description}…", worker)

    def reboot_device(self):
        self.run_device_power_action(["reboot"], "重启设备")

    def poweroff_device(self):
        self.run_device_power_action(["shell", "reboot", "-p"], "关机设备")

    def install_apk(self):
        serial = self.selected_serial()
        if not serial:
            return
        self.show_apk_install_dialog(serial)

    def show_apk_install_dialog(self, serial):
        """在当前操作区域内显示 APK 上传/拖放面板。"""
        if getattr(self, "apk_operation_frame", None) is not None:
            self.close_apk_install_panel()
        self.operation_view.pack_forget()
        self.operation_scroll.pack_forget()
        panel = ttk.Frame(self.operation_body, padding=8)
        panel.pack(fill=tk.BOTH, expand=True)
        self.apk_operation_frame = panel
        self.apk_install_serial = serial
        selected_path = tk.StringVar()
        overwrite_var = tk.BooleanVar(value=False)
        ttk.Label(panel, text="安装 APK", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(panel, text="点击上传，或将 APK 直接拖到下方区域。", foreground="#64748b").pack(anchor=tk.W, pady=(3, 8))
        drop_area = tk.Label(panel, text="将 APK 拖到这里", background="#eef2f6", foreground="#52606d", relief=tk.GROOVE, bd=1, height=4, font=("Microsoft YaHei UI", 10))
        drop_area.pack(fill=tk.BOTH, expand=True)
        ttk.Label(panel, textvariable=selected_path, foreground="#2563eb").pack(fill=tk.X, pady=(8, 0))
        ttk.Checkbutton(panel, text="覆盖安装（勾选为覆盖安装）", variable=overwrite_var).pack(anchor=tk.W, pady=(6, 0))
        buttons = ttk.Frame(panel)
        buttons.pack(fill=tk.X, pady=(10, 0))
        install_button = ttk.Button(buttons, text="开始安装", state=tk.DISABLED)
        install_button.pack(side=tk.RIGHT)
        ttk.Button(buttons, text="上传 APK…", command=lambda: choose_file()).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(buttons, text="取消", command=lambda: self.close_apk_install_panel()).pack(side=tk.LEFT)

        def set_path(path):
            path = os.path.abspath(path) if path else ""
            if not path or not os.path.isfile(path) or not path.lower().endswith(".apk"):
                selected_path.set("请选择 .apk 文件")
                install_button.configure(state=tk.DISABLED)
                return
            selected_path.set(path)
            install_button.configure(state=tk.NORMAL)

        def choose_file():
            path = filedialog.askopenfilename(title="选择 APK", filetypes=[("Android 安装包", "*.apk"), ("所有文件", "*.*")])
            if path:
                set_path(path)

        def install_selected():
            path = selected_path.get().strip()
            if path and os.path.isfile(path) and path.lower().endswith(".apk"):
                self.close_apk_install_panel()
                self.set_operation_text("正在安装 APK…", "APK 安装")
                self.start_apk_install(serial, path, overwrite_var.get())

        install_button.configure(command=install_selected)
        self.enable_native_file_drop(panel, set_path)

    def close_apk_install_panel(self):
        panel = getattr(self, "apk_operation_frame", None)
        if panel is not None:
            panel.destroy()
            self.apk_operation_frame = None
        self.file_directory_view = None
        self.operation_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.operation_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def start_apk_install(self, serial, path, overwrite=False):
        def worker():
            try:
                command = ["-s", serial, "install"]
                if overwrite:
                    command.append("-r")
                command.append(path)
                result = self.run_adb(command, timeout=180)
                text = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
                if result.returncode != 0:
                    raise RuntimeError(text or "APK 安装失败")
                self.result_queue.put(("text", ("APK 安装结果", text or "APK 安装成功"), None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker("正在安装 APK…", worker)

    def run_package_action(self, action):
        serial = self.selected_serial()
        package = self.package_var.get().strip()
        if not serial:
            return
        if not package:
            messagebox.showwarning(APP_TITLE, "请先点击“获取当前应用”，自动填入当前前台应用包名。")
            return
        if action == "uninstall":
            command = ["-s", serial, "uninstall", package]
            title, running = "卸载应用", "正在卸载应用…"
        else:
            command = ["-s", serial, "shell", "pm", "clear", package]
            title, running = "清除应用数据", "正在清除应用数据…"
        def worker():
            try:
                result = self.run_adb(command, timeout=60)
                text = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
                if result.returncode != 0:
                    raise RuntimeError(text or f"{title}失败")
                self.result_queue.put(("text", (f"{title}：{package}", text or f"{title}成功"), None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker(running, worker)

    def uninstall_package(self):
        self.run_package_action("uninstall")

    def clear_package_data(self):
        self.run_package_action("clear")

    def show_file_transfer_panel(self, mode):
        serial = self.selected_serial()
        if not serial:
            return
        if getattr(self, "apk_operation_frame", None) is not None:
            self.close_apk_install_panel()
        self.operation_view.pack_forget()
        self.operation_scroll.pack_forget()
        panel = ttk.Frame(self.operation_body, padding=8)
        panel.pack(fill=tk.BOTH, expand=True)
        self.apk_operation_frame = panel
        self.file_transfer_mode = mode
        self.file_transfer_serial = serial
        local_var = tk.StringVar()
        remote_var = tk.StringVar(value="/sdcard/")
        title = "电脑文件传到手机" if mode == "push" else "手机文件拉到电脑"
        ttk.Label(panel, text=title, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(panel, text="可填写路径后读取设备目录；传输操作会显示在当前操作中。", foreground="#64748b").pack(anchor=tk.W, pady=(3, 8))

        if mode == "push":
            source_label, source_var = "电脑本地路径", local_var
            dest_label, dest_var = "手机目标路径", remote_var
        else:
            source_label, source_var = "手机文件路径", remote_var
            dest_label, dest_var = "电脑保存路径", local_var

        source_row = ttk.Frame(panel)
        source_row.pack(fill=tk.X, pady=3)
        ttk.Label(source_row, text=source_label, width=12).pack(side=tk.LEFT)
        ttk.Entry(source_row, textvariable=source_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        if mode == "push":
            ttk.Button(source_row, text="浏览…", command=lambda: choose_local_file()).pack(side=tk.LEFT, padx=(6, 0))

        dest_row = ttk.Frame(panel)
        dest_row.pack(fill=tk.X, pady=3)
        ttk.Label(dest_row, text=dest_label, width=12).pack(side=tk.LEFT)
        ttk.Entry(dest_row, textvariable=dest_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        if mode == "pull":
            ttk.Button(dest_row, text="保存为…", command=lambda: choose_local_target()).pack(side=tk.LEFT, padx=(6, 0))

        directory_row = ttk.Frame(panel)
        directory_row.pack(fill=tk.X, pady=(8, 3))
        ttk.Button(directory_row, text="读取设备目录", command=lambda: read_directory()).pack(side=tk.LEFT)
        ttk.Label(directory_row, text="目录路径使用上面的手机路径", foreground="#64748b").pack(side=tk.LEFT, padx=(8, 0))
        directory_frame = ttk.Frame(panel)
        directory_frame.pack(fill=tk.BOTH, expand=True, pady=(3, 0))
        directory_view = tk.Text(directory_frame, height=7, wrap=tk.NONE, font=("Consolas", 9), undo=False)
        directory_view.insert("1.0", "点击“读取设备目录”查看手机路径内容。")
        directory_view.configure(state=tk.DISABLED, background="#f7f9fb", relief=tk.FLAT)
        directory_scroll = ttk.Scrollbar(directory_frame, orient=tk.VERTICAL, command=directory_view.yview)
        directory_view.configure(yscrollcommand=directory_scroll.set)
        directory_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        directory_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_directory_view = directory_view

        buttons = ttk.Frame(panel)
        buttons.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(buttons, text="开始传输", command=lambda: start_transfer()).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="取消", command=self.close_apk_install_panel).pack(side=tk.LEFT)

        def choose_local_file():
            path = filedialog.askopenfilename(title="选择电脑文件")
            if path:
                local_var.set(path)

        def choose_local_target():
            initial = os.path.basename(remote_var.get().rstrip("/\\")) or "device-file"
            path = filedialog.asksaveasfilename(title="选择电脑保存路径", initialfile=initial)
            if path:
                local_var.set(path)

        def read_directory():
            path = remote_var.get().strip() or "/sdcard/"
            def worker():
                try:
                    # 递归获取目录，便于选择手机端路径；限制层数避免根目录扫描过久。
                    result = self.run_adb(["-s", serial, "shell", "find", path, "-maxdepth", "3", "-type", "d", "-print"], timeout=60)
                    text = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
                    if result.returncode != 0 or not text:
                        # 少数旧设备的 find 不支持 -maxdepth，至少回退到当前目录列表。
                        fallback = self.run_adb(["-s", serial, "shell", "ls", "-la", path], timeout=30)
                        text = (fallback.stdout + fallback.stderr).decode("utf-8", "replace").strip()
                        if fallback.returncode != 0:
                            raise RuntimeError(text or "读取设备目录失败")
                    self.result_queue.put(("file_directory", (path, text or "目录为空"), None))
                except Exception as exc:
                    self.result_queue.put(("file_directory_error", str(exc), None))
            self.start_worker("正在读取设备目录…", worker)

        def start_transfer():
            source = source_var.get().strip()
            destination = dest_var.get().strip()
            if not source or not destination:
                messagebox.showwarning(APP_TITLE, "请填写完整的传输路径。")
                return
            if mode == "push" and not os.path.exists(source):
                messagebox.showwarning(APP_TITLE, "电脑本地路径不存在。")
                return
            self.close_apk_install_panel()
            self.set_operation_text(f"来源：{source}\n目标：{destination}\n\n正在传输…", title)
            self.start_file_transfer(serial, mode, source, destination)

        # 打开传输面板后立即读取默认手机目录，不需要再额外点击一次。
        read_directory()

    def start_file_transfer(self, serial, mode, source, destination):
        command = ["-s", serial, "push" if mode == "push" else "pull", source, destination]
        def worker():
            try:
                result = self.run_adb(command, timeout=300)
                text = (result.stdout + result.stderr).decode("utf-8", "replace").strip()
                if result.returncode != 0:
                    raise RuntimeError(text or "文件传输失败")
                direction = "电脑文件已传到手机" if mode == "push" else "手机文件已保存到电脑"
                self.result_queue.put(("text", (direction, text or "传输完成"), None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker("正在传输文件…", worker)

    def find_package_pid(self, serial, package):
        result = self.run_adb(["-s", serial, "shell", "pidof", package], timeout=15)
        if result.returncode == 0:
            match = re.search(r"\b(\d+)\b", result.stdout.decode("utf-8", "replace"))
            if match:
                return match.group(1)
        result = self.run_adb(["-s", serial, "shell", "ps", "-A"], timeout=20)
        text = result.stdout.decode("utf-8", "replace")
        package_pattern = re.compile(r"\b(\d+)\b.*\b" + re.escape(package) + r"\b")
        for line in text.splitlines():
            match = package_pattern.search(line)
            if match:
                return match.group(1)
        raise RuntimeError(f"没有找到当前应用进程：{package}。请先保持该应用在前台并重新获取当前应用。")

    def toggle_log_capture(self):
        if self.log_capture_state == "running":
            self.stop_log_capture()
        elif self.log_capture_state == "idle":
            self.start_log_capture()

    def start_log_capture(self):
        serial = self.selected_serial()
        package = self.package_var.get().strip()
        if not serial:
            return
        if not package:
            messagebox.showwarning(APP_TITLE, "请先点击“获取当前应用”，日志只抓取当前应用。")
            return
        self.log_capture_state = "starting"
        self.log_capture_elapsed_var.set("已抓取 0 秒")
        self.log_capture_button.configure(text="正在启动日志抓取…", state=tk.DISABLED)
        self.set_operation_text(f"应用：{package}\n\n正在获取应用进程…", "日志抓取")

        def worker():
            file_handle = None
            try:
                pid = self.find_package_pid(serial, package)
                os.makedirs(self.output_dir, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                safe_package = re.sub(r"[^A-Za-z0-9_.-]+", "_", package)
                path = os.path.join(self.output_dir, f"logcat-{safe_package}-{stamp}.log")
                file_handle = open(path, "wb")
                adb = self.adb_var.get().strip().strip('"')
                started_at = time.monotonic()
                process = subprocess.Popen(
                    [adb, "-s", serial, "logcat", f"--pid={pid}", "-v", "threadtime"],
                    stdout=file_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                )
                self.result_queue.put(("log_started", (process, path, file_handle, pid, package, started_at), None))
                returncode = process.wait()
                file_handle.flush()
                file_handle.close()
                elapsed = time.monotonic() - started_at
                self.result_queue.put(("log_done", (path, elapsed, returncode), None))
            except Exception as exc:
                if file_handle:
                    try:
                        file_handle.close()
                    except Exception:
                        pass
                self.result_queue.put(("log_error", None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def update_log_capture_elapsed(self):
        if self.log_capture_state != "running" or not self.log_capture_started_at:
            self.log_capture_timer_after_id = None
            return
        elapsed = max(0, int(time.monotonic() - self.log_capture_started_at))
        self.log_capture_elapsed_var.set(f"已抓取 {elapsed} 秒")
        self.log_capture_timer_after_id = self.root.after(250, self.update_log_capture_elapsed)

    def stop_log_capture(self):
        if self.log_capture_state != "running":
            return
        self.log_capture_state = "stopping"
        self.log_capture_button.configure(text="正在保存日志…", state=tk.DISABLED)
        self.status_var.set("正在结束日志抓取并保存 .log 文件…")
        process = self.log_capture_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass

    def enable_native_file_drop(self, window, on_path):
        """在 Windows 上给 APK 弹窗接入系统文件拖放消息。"""
        if sys.platform != "win32":
            return
        try:
            window.update_idletasks()
            hwnd = wintypes.HWND(window.winfo_id())
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            wm_dropfiles = 0x0233
            gwlp_wndproc = -4
            lresult = ctypes.c_ssize_t
            wnd_proc_type = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.CallWindowProcW.restype = lresult
            shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
            shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
            shell32.DragQueryFileW.restype = wintypes.UINT
            shell32.DragFinish.argtypes = [wintypes.HANDLE]

            old_proc = user32.GetWindowLongPtrW(hwnd, gwlp_wndproc)
            # 先取出原窗口过程，再安装 Python 回调。
            if not old_proc:
                return

            def wnd_proc(message_hwnd, message, wparam, lparam):
                if message == wm_dropfiles:
                    hdrop = wintypes.HANDLE(wparam)
                    count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                    paths = []
                    for index in range(count):
                        length = shell32.DragQueryFileW(hdrop, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        shell32.DragQueryFileW(hdrop, index, buffer, length + 1)
                        paths.append(buffer.value)
                    shell32.DragFinish(hdrop)
                    apk_paths = [path for path in paths if path.lower().endswith(".apk")]
                    on_path(apk_paths[0] if apk_paths else "")
                    return 0
                return user32.CallWindowProcW(old_proc, message_hwnd, message, wparam, lparam)

            callback = wnd_proc_type(wnd_proc)
            installed_proc = user32.SetWindowLongPtrW(hwnd, gwlp_wndproc, ctypes.cast(callback, ctypes.c_void_p))
            if not installed_proc:
                return
            shell32.DragAcceptFiles(hwnd, True)
            window._native_drop_callback = callback
            window._native_drop_old_proc = old_proc
            window._native_drop_hwnd = hwnd

            def restore(_event=None):
                old = getattr(window, "_native_drop_old_proc", None)
                drop_hwnd = getattr(window, "_native_drop_hwnd", None)
                if old and drop_hwnd:
                    shell32.DragAcceptFiles(drop_hwnd, False)
                    user32.SetWindowLongPtrW(drop_hwnd, gwlp_wndproc, old)
                    window._native_drop_old_proc = None

            window.bind("<Destroy>", restore, add="+")
        except Exception:
            # 非 Windows 环境或系统拖放接口不可用时，仍保留“选择 APK”按钮。
            return

    def get_current_app(self):
        serial = self.selected_serial()
        if not serial:
            return
        def worker():
            try:
                # 不同 Android 版本字段名不同，依次尝试 activity、window 和 top。
                outputs = []
                for args in (
                    ["-s", serial, "shell", "dumpsys", "activity", "activities"],
                    ["-s", serial, "shell", "dumpsys", "window", "windows"],
                    ["-s", serial, "shell", "dumpsys", "activity", "top"],
                ):
                    result = self.run_adb(args, timeout=20)
                    if result.returncode == 0:
                        outputs.append(result.stdout.decode("utf-8", "replace"))

                priority_lines = []
                for text in outputs:
                    priority_lines.extend(
                        line.strip() for line in text.splitlines()
                        if any(key in line for key in ("mResumedActivity", "mTopResumedActivity", "mCurrentFocus", "mFocusedApp", "ResumedActivity", "ACTIVITY "))
                    )
                component_pattern = re.compile(r"(?<![\w.])([A-Za-z_][\w]*(?:\.[A-Za-z0-9_]+)*)/([A-Za-z0-9_.$]+)")
                package = ""
                current = priority_lines[0] if priority_lines else ""
                for line in priority_lines + [line.strip() for text in outputs for line in text.splitlines()]:
                    match = component_pattern.search(line)
                    if match:
                        package = match.group(1)
                        current = line
                        break
                if not package:
                    raise RuntimeError("没有读取到前台 Activity。请确认设备已授权，并保持目标页面在最前面后重试。")
                self.result_queue.put(("current_app", (current, package), None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker("正在获取当前应用…", worker)

    def show_package_info(self):
        serial, package = self.selected_serial(), self.package_var.get().strip()
        if not serial or not package:
            if serial:
                messagebox.showwarning(APP_TITLE, "请输入要查询的应用包名。")
            return
        def worker():
            try:
                result = self.run_adb(["-s", serial, "shell", "dumpsys", "package", package], timeout=25)
                text = result.stdout.decode("utf-8", "replace").strip()
                if result.returncode != 0 or not text:
                    raise RuntimeError(self.command_error(result, "未获取到应用信息"))
                self.result_queue.put(("text", (f"应用详情：{package}", text), None))
            except Exception as exc:
                self.result_queue.put(("error", None, str(exc)))
        self.start_worker("正在读取应用详情…", worker)

    @staticmethod
    def parse_meminfo(text):
        """提取 meminfo 中适合做前后对比的几个字段，单位统一为 KB。"""
        values = {}
        patterns = {
            # Android 版本差异：有的输出 TOTAL PSS:，有的输出 TOTAL 或 TOTAL:。
            # 排除 TOTAL SWAP PSS，避免把交换区数值当成进程 PSS。
            "total_pss_kb": r"^\s*TOTAL(?:\s+PSS)?\s*:?\s*([\d,]+)",
            "native_heap_kb": r"^\s*Native Heap\s+([\d,]+)",
            "dalvik_heap_kb": r"^\s*Dalvik Heap\s+([\d,]+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
            if match:
                values[key] = int(match.group(1).replace(",", ""))
        return values

    def read_performance_sample(self, serial, package):
        try:
            result = self.run_adb(["-s", serial, "shell", "dumpsys", "meminfo", package], timeout=15)
            if result.returncode != 0:
                return None
            return self.parse_meminfo(result.stdout.decode("utf-8", "replace"))
        except Exception:
            return None

    def performance_sample_worker(self, serial, package, stop_event):
        while not stop_event.is_set():
            started = time.monotonic()
            values = self.read_performance_sample(serial, package)
            elapsed = time.monotonic() - self.performance_started_at if self.performance_started_at else 0
            if values:
                self.performance_samples.append({
                    "elapsed": elapsed,
                    "values": values,
                })
            # 通过队列交给 Tk 主线程更新当前操作，避免后台线程直接操作控件。
            self.result_queue.put(("perf_sample", {"elapsed": elapsed, "values": values}, None))
            # 每秒采样一次，避免监测本身明显干扰被测页面。
            stop_event.wait(max(0.1, 1.0 - (time.monotonic() - started)))

    def append_performance_live_log(self, message, elapsed=None):
        """追加一条性能监测实时日志，并同步打印到控制台。"""
        if elapsed is None:
            elapsed = time.monotonic() - self.performance_started_at if self.performance_started_at else 0
        line = f"{elapsed:.1f} 秒：{message}"
        self.performance_live_logs.append(line)
        # 控制台输出保留，便于从命令行启动程序时同步观察采样过程。
        try:
            stream = getattr(sys, "stdout", None)
            if stream is not None and hasattr(stream, "write"):
                stream.write(f"[性能监测] {line}\n")
                if hasattr(stream, "flush"):
                    stream.flush()
        except Exception:
            # windowed EXE 没有标准输出句柄时，实时日志仍保留在当前操作区域。
            pass

    def performance_live_text(self):
        phase = self.performance_live_phase or {
            "starting": "正在初始化",
            "running": "正在采样",
            "stopping": "正在整理最终报告",
        }.get(self.performance_state, "准备中")
        elapsed = time.monotonic() - self.performance_started_at if self.performance_started_at else 0
        lines = [
            f"状态：{phase}",
            f"计时：{elapsed:.1f} 秒",
            "",
            "[实时日志]",
        ]
        lines.extend(self.performance_live_logs or ["正在等待监测初始化…"])
        return "\n".join(lines)

    def start_performance_live_view(self):
        """立即把当前操作切换为性能监测面板，并持续刷新计时/日志。"""
        # 安装 APK 面板与文本面板互斥；开始性能监测时必须立即恢复文本面板。
        if getattr(self, "apk_operation_frame", None) is not None:
            self.close_apk_install_panel()
        self.performance_live_logs = []
        self.performance_live_phase = "正在初始化"
        self.append_performance_live_log("已开始性能监测，正在初始化 gfxinfo…", 0)
        self.set_operation_text(self.performance_live_text(), "性能监测", scroll_end=True)
        if self.performance_ui_after_id is None:
            self.performance_ui_after_id = self.root.after(200, self.update_performance_live_view)

    def update_performance_live_view(self):
        self.performance_ui_after_id = None
        if self.performance_state not in ("starting", "running", "stopping"):
            return
        self.set_operation_text(self.performance_live_text(), "性能监测", scroll_end=True)
        self.performance_ui_after_id = self.root.after(200, self.update_performance_live_view)

    def start_performance_monitoring(self):
        serial = self.selected_serial()
        package = self.package_var.get().strip()
        if not serial:
            return
        if not package:
            messagebox.showwarning(APP_TITLE, "请输入要监测的应用包名；可先点击“获取当前应用”确认包名。")
            return
        if self.performance_state != "idle":
            return
        self.performance_state = "starting"
        self.performance_serial = serial
        self.performance_package = package
        # 从用户点击开始计时，初始化耗时也会在实时面板中体现，不再等到结束才出现。
        self.performance_started_at = time.monotonic()
        self.performance_start_button.configure(state=tk.DISABLED)
        self.performance_stop_button.configure(state=tk.DISABLED)
        self.start_performance_live_view()

        def worker():
            try:
                reset = self.run_adb(["-s", serial, "shell", "dumpsys", "gfxinfo", package, "reset"], timeout=15)
                if reset.returncode != 0:
                    raise RuntimeError(self.command_error(reset, "无法重置 gfxinfo 渲染统计"))
                self.result_queue.put(("perf_log", "已完成 gfxinfo 重置，正在获取内存基线…", None))
                mem = self.run_adb(["-s", serial, "shell", "dumpsys", "meminfo", package], timeout=20)
                baseline = self.parse_meminfo(mem.stdout.decode("utf-8", "replace"))
                self.result_queue.put(("perf_started", baseline, None))
            except Exception as exc:
                self.result_queue.put(("perf_error", None, str(exc)))
        self.start_worker("正在初始化性能监测…", worker)

    def stop_performance_monitoring(self):
        if self.performance_state == "starting":
            messagebox.showinfo(APP_TITLE, "性能监测仍在初始化，请稍后再点击结束。")
            return
        if self.performance_state != "running":
            return
        self.performance_state = "stopping"
        self.performance_live_phase = "正在整理最终报告"
        self.append_performance_live_log("已停止采样，正在获取最终 gfxinfo、内存和 CPU…")
        self.performance_stop_button.configure(state=tk.DISABLED)
        self.status_var.set("正在整理帧耗时和内存数据…")
        if self.performance_stop_event:
            self.performance_stop_event.set()
        threading.Thread(target=self.performance_finish_worker, daemon=True).start()

    @staticmethod
    def parse_gfx_summary(text):
        values = {}
        patterns = {
            "total_frames": r"Total frames rendered:\s*([\d,]+)",
            "janky_frames": r"Janky frames:\s*([\d,]+)\s*\(([\d.]+)%\)",
            "50th_percentile": r"50th percentile:\s*([^\r\n]+)",
            "90th_percentile": r"90th percentile:\s*([^\r\n]+)",
            "95th_percentile": r"95th percentile:\s*([^\r\n]+)",
            "99th_percentile": r"99th percentile:\s*([^\r\n]+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                values[key] = match.groups()
        return values

    def performance_finish_worker(self):
        try:
            if self.performance_thread:
                self.performance_thread.join(timeout=20)
            serial, package = self.performance_serial, self.performance_package
            self.result_queue.put(("perf_log", "正在获取最终 gfxinfo…", None))
            gfx = self.run_adb(["-s", serial, "shell", "dumpsys", "gfxinfo", package], timeout=30)
            self.result_queue.put(("perf_log", "gfxinfo 已获取，正在获取最终内存…", None))
            mem = self.run_adb(["-s", serial, "shell", "dumpsys", "meminfo", package], timeout=20)
            self.result_queue.put(("perf_log", "内存已获取，正在获取 CPU 快照…", None))
            cpu = self.run_adb(["-s", serial, "shell", "dumpsys", "cpuinfo"], timeout=20)
            gfx_text = gfx.stdout.decode("utf-8", "replace")
            final_memory = self.parse_meminfo(mem.stdout.decode("utf-8", "replace"))
            cpu_text = cpu.stdout.decode("utf-8", "replace")
            cpu_line = next((line.strip() for line in cpu_text.splitlines() if package.lower() in line.lower()), "未找到该应用的 CPU 行")
            report = self.build_performance_report(gfx_text, final_memory, cpu_line)
            os.makedirs(self.output_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            report_path = os.path.join(self.output_dir, f"performance-{stamp}.txt")
            with open(report_path, "w", encoding="utf-8") as file:
                file.write(report)
            self.result_queue.put(("perf_done", (report, report_path), None))
        except Exception as exc:
            self.result_queue.put(("perf_error", None, str(exc)))

    def build_performance_report(self, gfx_text, final_memory, cpu_line):
        elapsed = time.monotonic() - self.performance_started_at if self.performance_started_at else 0
        gfx = self.parse_gfx_summary(gfx_text)
        memory_samples = [sample["values"] for sample in self.performance_samples if sample.get("values")]
        if self.performance_baseline:
            memory_samples.insert(0, self.performance_baseline)
        peak_pss = max((item.get("total_pss_kb", 0) for item in memory_samples), default=0)
        baseline_pss = self.performance_baseline.get("total_pss_kb")
        final_pss = final_memory.get("total_pss_kb")
        lines = [
            "ADB 性能监测报告",
            f"设备：{self.performance_serial}",
            f"应用：{self.performance_package}",
            f"监测时长：{elapsed:.1f} 秒",
            "",
            "[帧渲染]",
            f"总渲染帧：{gfx.get('total_frames', ('未获取',))[0]}",
            f"卡顿帧：{gfx.get('janky_frames', ('未获取', ''))[0]} ({gfx.get('janky_frames', ('', '未获取'))[1]}%)",
            f"50% 帧耗时：{gfx.get('50th_percentile', ('未获取',))[0]}",
            f"90% 帧耗时：{gfx.get('90th_percentile', ('未获取',))[0]}",
            f"95% 帧耗时：{gfx.get('95th_percentile', ('未获取',))[0]}",
            f"99% 帧耗时：{gfx.get('99th_percentile', ('未获取',))[0]}",
            "",
            "[内存 PSS]（单位 KB）",
            f"开始：{baseline_pss if baseline_pss is not None else '未获取'}",
            f"峰值：{peak_pss if peak_pss else '未获取'}",
            f"结束：{final_pss if final_pss is not None else '未获取'}",
            f"结束相对开始：{(final_pss - baseline_pss) if final_pss is not None and baseline_pss is not None else '未获取'}",
            f"Native Heap（结束）：{final_memory.get('native_heap_kb', '未获取')}",
            f"Dalvik Heap（结束）：{final_memory.get('dalvik_heap_kb', '未获取')}",
            "",
            "[CPU 快照]",
            cpu_line,
            "",
            "[gfxinfo 原始摘要]",
            gfx_text[-12000:] if gfx_text else "未获取 gfxinfo 输出",
        ]
        return "\n".join(lines)

    def render_preview(self):
        if self.image is None:
            return
        width, height = max(80, self.preview.winfo_width() - 18), max(80, self.preview.winfo_height() - 18)
        scale = min(width / self.image.width, height / self.image.height, 1.0)
        size = (max(1, int(self.image.width * scale)), max(1, int(self.image.height * scale)))
        displayed = self.image.resize(size, Image.Resampling.LANCZOS) if size != self.image.size else self.image
        self.preview_photo = ImageTk.PhotoImage(displayed)
        self.preview.configure(image=self.preview_photo, text="")

    def save_image(self):
        if self.image is None:
            return
        path = filedialog.asksaveasfilename(title="保存截图", defaultextension=".png", filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg;*.jpeg")], initialfile="device-screenshot.png")
        if path:
            try:
                self.image.save(path)
                self.add_artifact("截图", path)
                self.status_var.set(f"截图已保存：{path}")
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"保存失败：{exc}")

    def add_artifact(self, kind, path):
        # 文件列表按创建顺序倒序排列，最新截图/录屏/报告始终置顶。
        item = self.artifact_tree.insert("", 0, values=(kind, os.path.basename(path)))
        self.artifact_paths[item] = path

    def show_image_menu(self, event):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="复制图片", command=self.copy_image_to_clipboard)
        if self.image is not None:
            menu.add_command(label="保存图片…", command=self.save_image)
        menu.tk_popup(event.x_root, event.y_root)

    def show_artifact_menu(self, event):
        item = self.artifact_tree.identify_row(event.y)
        if not item:
            return
        self.artifact_tree.selection_set(item)
        path = self.artifact_paths.get(item)
        if not path:
            return
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="复制文件", command=lambda: self.copy_file_to_clipboard(path))
        menu.add_command(label="复制完整路径", command=lambda: self.copy_text_to_clipboard(path))
        menu.add_command(label="在资源管理器中显示", command=lambda: self.show_in_explorer(path))
        menu.add_separator()
        menu.add_command(label="删除文件", command=lambda: self.delete_artifact(item, path))
        menu.tk_popup(event.x_root, event.y_root)

    def delete_artifact(self, item, path):
        path = os.path.abspath(path)
        if not messagebox.askyesno(APP_TITLE, f"确定删除文件吗？\n\n{path}"):
            return
        try:
            if os.path.isfile(path):
                os.remove(path)
            self.artifact_paths.pop(item, None)
            self.artifact_tree.delete(item)
            self.status_var.set("文件已删除")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"删除文件失败：{exc}")

    def copy_image_to_clipboard(self):
        if self.image is None:
            messagebox.showinfo(APP_TITLE, "请先截取一张图片。")
            return
        try:
            output = io.BytesIO()
            self.image.convert("RGB").save(output, "BMP")
            self.put_clipboard_data(8, output.getvalue()[14:])  # CF_DIB，BMP 文件头不写入剪贴板
            self.status_var.set("截图已复制到剪贴板，可直接粘贴")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"复制图片失败：{exc}")

    def copy_file_to_clipboard(self, path):
        try:
            if sys.platform != "win32":
                raise RuntimeError("当前仅实现了 Windows 文件剪贴板")
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            class DROPFILES(ctypes.Structure):
                _fields_ = [("pFiles", wintypes.DWORD), ("pt", POINT), ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL)]
            header = DROPFILES(ctypes.sizeof(DROPFILES), POINT(0, 0), False, True)
            data = bytes(header) + (os.path.abspath(path) + "\0\0").encode("utf-16le")
            self.put_clipboard_data(15, data)  # CF_HDROP，可在资源管理器和聊天工具中粘贴文件
            self.status_var.set("文件已复制到剪贴板，可直接粘贴或发送")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"复制文件失败：{exc}")

    def copy_text_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("完整路径已复制到剪贴板")

    @staticmethod
    def put_clipboard_data(format_id, data):
        if sys.platform != "win32":
            raise RuntimeError("当前仅实现了 Windows 剪贴板")
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        if not user32.OpenClipboard(None):
            raise RuntimeError("无法打开剪贴板，请关闭正在占用剪贴板的程序后重试")
        try:
            if not user32.EmptyClipboard():
                raise RuntimeError("无法清空剪贴板")
            handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
            if not handle:
                raise RuntimeError("无法分配剪贴板内存")
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                kernel32.GlobalFree(handle)
                raise RuntimeError("无法写入剪贴板")
            ctypes.memmove(pointer, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(format_id, handle):
                kernel32.GlobalFree(handle)
                raise RuntimeError("系统拒绝了剪贴板数据")
        finally:
            user32.CloseClipboard()

    @staticmethod
    def show_in_explorer(path):
        subprocess.Popen(["explorer.exe", "/select,", os.path.abspath(path)])

    def open_output_folder(self):
        os.makedirs(self.output_dir, exist_ok=True)
        subprocess.Popen(["explorer.exe", self.output_dir])

    def set_operation_text(self, text, heading=None, scroll_end=False):
        if not hasattr(self, "operation_view"):
            return
        display_text = text if not heading else f"{heading}\n\n{text}"
        self.operation_view.configure(state=tk.NORMAL)
        self.operation_view.delete("1.0", tk.END)
        self.operation_view.insert("1.0", display_text)
        self.operation_view.configure(state=tk.DISABLED)
        self.operation_view.see(tk.END if scroll_end else "1.0")

    def copy_operation_text(self):
        if not hasattr(self, "operation_view"):
            return
        text = self.operation_view.get("sel.first", "sel.last") if self.operation_view.tag_ranges("sel") else self.operation_view.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo(APP_TITLE, "当前没有可复制的内容。")
            return
        self.copy_text_to_clipboard(text)
        self.status_var.set("当前操作内容已复制到剪贴板")

    def show_operation_menu(self, event):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="复制选中内容", command=self.copy_operation_text)
        menu.add_command(label="复制全部内容", command=lambda: self.copy_text_to_clipboard(self.operation_view.get("1.0", "end-1c")))
        menu.tk_popup(event.x_root, event.y_root)

    def poll_results(self):
        try:
            while True:
                kind, value, error = self.result_queue.get_nowait()
                if kind == "devices":
                    devices, state_map, silent = value
                    previous = list(self.device_combo["values"])
                    self.devices_refreshing = False
                    self.device_state_map = state_map
                    self.device_combo["values"] = devices
                    if self.device_var.get() not in devices:
                        self.device_var.set(devices[0] if devices else "")
                    unauthorized = sum(1 for _display, (_serial, state) in state_map.items() if state == "unauthorized")
                    offline = sum(1 for _display, (_serial, state) in state_map.items() if state == "offline")
                    if unauthorized and not any(state == "device" for _serial, state in state_map.values()):
                        self.status_var.set(f"发现 {unauthorized} 台未授权设备，请在手机上允许 USB 调试")
                    elif not devices:
                        self.status_var.set("未发现设备，请检查 USB 调试或无线连接")
                    elif not silent:
                        self.status_var.set(f"已发现 {sum(1 for _serial, state in state_map.values() if state == 'device')} 台可用设备")
                    if previous != devices:
                        self.load_device_info()
                elif kind == "devices_error":
                    silent, detail = value
                    self.devices_refreshing = False
                    if not silent:
                        self.status_var.set("读取设备失败")
                        messagebox.showerror(APP_TITLE, detail)
                elif kind == "refresh_after_status":
                    self.status_var.set(value)
                    self.root.after(300, self.refresh_devices)
                elif kind == "image":
                    self.image = value
                    self.status_var.set(f"截图成功：{value.width} × {value.height}；右键预览可复制")
                    self.render_preview()
                    self.capture_busy = False
                    self.capture_button.configure(state=tk.NORMAL)
                elif kind == "image_saved":
                    # 截图线程已经完成落盘；这里同时更新预览并把文件加入列表。
                    if len(value) == 4:
                        path, width, height, image = value
                        self.image = image
                    else:
                        path, width, height = value
                    self.add_artifact("截图", path)
                    self.render_preview()
                    self.capture_busy = False
                    self.capture_button.configure(state=tk.NORMAL)
                    self.status_var.set(f"截图已保存：{os.path.basename(path)}（{width} × {height}），已加入文件列表")
                elif kind == "capture_error":
                    self.capture_busy = False
                    self.capture_button.configure(state=tk.NORMAL)
                    self.status_var.set("截图失败")
                    self.set_operation_text(error, "截图失败")
                elif kind == "record_preview":
                    if self.mirror_process is None:
                        self.image = value
                        self.render_preview()
                        if self.recording:
                            self.status_var.set("正在录屏：预览实时刷新中…")
                elif kind == "record_done":
                    self.recording, self.record_process = False, None
                    elapsed = int(time.monotonic() - self.record_started_at) if self.record_started_at else 0
                    self.record_elapsed_var.set(f"已录制 {elapsed} 秒")
                    self.record_button.configure(text="开始录屏", state=tk.NORMAL)
                    self.record_started_at = None
                    self.record_timer_after_id = None
                    self.clear_preview()
                    self.add_artifact("录屏", value)
                    self.status_var.set(f"录屏已保存：{value}；右键可复制文件")
                elif kind == "record_error":
                    self.recording, self.record_process = False, None
                    elapsed = int(time.monotonic() - self.record_started_at) if self.record_started_at else 0
                    self.record_elapsed_var.set(f"已录制 {elapsed} 秒")
                    self.record_button.configure(text="开始录屏", state=tk.NORMAL)
                    self.record_started_at = None
                    self.record_timer_after_id = None
                    self.clear_preview()
                    self.status_var.set("录屏失败")
                    self.set_operation_text(error, "录屏失败")
                elif kind == "file_directory":
                    path, directory_text = value
                    view = self.file_directory_view
                    if view is not None and view.winfo_exists():
                        view.configure(state=tk.NORMAL)
                        view.delete("1.0", tk.END)
                        view.insert("1.0", f"目录：{path}\n\n{directory_text}")
                        view.configure(state=tk.DISABLED)
                        view.see("1.0")
                    self.status_var.set(f"已读取设备目录：{path}")
                elif kind == "file_directory_error":
                    view = self.file_directory_view
                    if view is not None and view.winfo_exists():
                        view.configure(state=tk.NORMAL)
                        view.delete("1.0", tk.END)
                        view.insert("1.0", value)
                        view.configure(state=tk.DISABLED)
                    self.status_var.set("读取设备目录失败")
                elif kind == "log_started":
                    process, path, _file_handle, pid, package, started_at = value
                    self.log_capture_state = "running"
                    self.log_capture_process = process
                    self.log_capture_started_at = started_at
                    self.log_capture_elapsed_var.set("已抓取 0 秒")
                    self.log_capture_button.configure(text="结束日志抓取", state=tk.NORMAL)
                    self.status_var.set(f"正在抓取 {package} 日志（PID {pid}）…")
                    self.set_operation_text(
                        f"应用：{package}\nPID：{pid}\n文件：{path}\n\n正在抓取，只包含当前应用日志…",
                        "日志抓取",
                    )
                    self.update_log_capture_elapsed()
                elif kind == "log_done":
                    path, elapsed, _returncode = value
                    self.log_capture_state = "idle"
                    self.log_capture_process = None
                    self.log_capture_started_at = None
                    self.log_capture_timer_after_id = None
                    self.log_capture_elapsed_var.set(f"已抓取 {int(elapsed)} 秒")
                    self.log_capture_button.configure(text="开始日志抓取", state=tk.NORMAL)
                    self.add_artifact("日志", path)
                    self.status_var.set(f"日志已保存：{path}")
                    self.set_operation_text(f"文件：{path}\n抓取时长：{elapsed:.1f} 秒", "日志抓取完成")
                elif kind == "log_error":
                    self.log_capture_state = "idle"
                    self.log_capture_process = None
                    self.log_capture_started_at = None
                    self.log_capture_timer_after_id = None
                    self.log_capture_elapsed_var.set("已抓取 0 秒")
                    self.log_capture_button.configure(text="开始日志抓取", state=tk.NORMAL)
                    self.status_var.set("日志抓取失败")
                    self.set_operation_text(error, "日志抓取失败")
                elif kind == "perf_log":
                    # 初始化和整理阶段的日志也逐条显示，不等待最终报告。
                    self.append_performance_live_log(value)
                elif kind == "perf_sample":
                    sample = value or {}
                    elapsed = sample.get("elapsed", 0)
                    values = sample.get("values") or {}
                    if values:
                        pss = values.get("total_pss_kb", "未获取")
                        native = values.get("native_heap_kb", "未获取")
                        dalvik = values.get("dalvik_heap_kb", "未获取")
                        self.append_performance_live_log(
                            f"PSS={pss} KB，Native={native} KB，Dalvik={dalvik} KB",
                            elapsed,
                        )
                    else:
                        self.append_performance_live_log("内存采样失败，下一秒继续重试", elapsed)
                elif kind == "perf_started":
                    self.performance_state = "running"
                    self.performance_live_phase = "正在采样"
                    self.performance_baseline = value or {}
                    self.performance_samples = []
                    baseline = self.performance_baseline
                    if baseline:
                        self.append_performance_live_log(
                            "已获取内存基线：PSS={} KB，Native={} KB，Dalvik={} KB".format(
                                baseline.get("total_pss_kb", "未获取"),
                                baseline.get("native_heap_kb", "未获取"),
                                baseline.get("dalvik_heap_kb", "未获取"),
                            )
                        )
                    else:
                        self.append_performance_live_log("内存基线未获取，将继续尝试采样")
                    self.performance_stop_event = threading.Event()
                    self.performance_thread = threading.Thread(
                        target=self.performance_sample_worker,
                        args=(self.performance_serial, self.performance_package, self.performance_stop_event),
                        daemon=True,
                    )
                    self.performance_thread.start()
                    self.performance_stop_button.configure(state=tk.NORMAL)
                    self.status_var.set("性能监测中：请复现卡顿操作，完成后点击“结束并生成报告”")
                elif kind == "perf_done":
                    report, report_path = value
                    self.performance_state = "idle"
                    self.performance_live_phase = ""
                    self.performance_stop_event = None
                    self.performance_thread = None
                    self.performance_start_button.configure(state=tk.NORMAL)
                    self.performance_stop_button.configure(state=tk.DISABLED)
                    self.add_artifact("性能报告", report_path)
                    self.status_var.set(f"性能报告已保存：{report_path}")
                    self.set_operation_text(report, "性能监测报告")
                elif kind == "perf_error":
                    self.performance_state = "idle"
                    self.performance_live_phase = ""
                    if self.performance_stop_event:
                        self.performance_stop_event.set()
                    self.performance_stop_event = None
                    self.performance_thread = None
                    self.performance_start_button.configure(state=tk.NORMAL)
                    self.performance_stop_button.configure(state=tk.DISABLED)
                    self.status_var.set("性能监测失败")
                    self.set_operation_text(error, "性能监测失败")
                elif kind == "mirror_embed":
                    process, hwnd = value
                    if process is self.mirror_process:
                        try:
                            self.embed_mirror_window(process, hwnd)
                            self.mirror_button.configure(text="关闭投屏控制", state=tk.NORMAL)
                        except Exception as exc:
                            self.set_operation_text(str(exc), "投屏嵌入失败")
                            self.status_var.set("投屏嵌入失败")
                            self.mirror_button.configure(text="正在关闭投屏…", state=tk.DISABLED)
                            self.mirror_stop_requested = True
                            process.terminate()
                elif kind == "mirror_closed":
                    process, returncode, output = value if isinstance(value, tuple) else (value, 0, "")
                    if process is self.mirror_process:
                        self.mirror_process = None
                        self.restore_preview_after_mirror()
                        self.mirror_button.configure(text="开始投屏并控制", state=tk.NORMAL)
                        if self.mirror_stop_requested or returncode == 0:
                            self.status_var.set("投屏已关闭")
                        else:
                            detail = output[-1200:] if output else "请确认设备已授权，并检查无线/USB 连接。"
                            self.status_var.set("投屏启动失败")
                            self.set_operation_text(detail, "投屏启动失败")
                        self.mirror_stop_requested = False
                elif kind == "text":
                    self.status_var.set("操作完成")
                    self.set_operation_text(value[1], value[0])
                elif kind == "current_app":
                    current, package = value
                    if package:
                        self.package_var.set(package)
                        self.status_var.set(f"当前应用：{package}（已填入包名）")
                    else:
                        self.status_var.set("已获取当前前台应用")
                    self.set_operation_text(f"{current}\n\n包名：{package or '未识别'}", "当前前台应用")
                elif kind == "operation_error":
                    self.status_var.set(value)
                    self.set_operation_text(f"{value}\n\n{error}")
                elif kind == "status":
                    self.status_var.set(value)
                elif kind == "error":
                    self.status_var.set("操作失败")
                    self.set_operation_text(error or "操作失败", "操作失败")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_results)


def main():
    root = tk.Tk()
    AdbScreenshotTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
