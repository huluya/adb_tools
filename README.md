# ADB 设备工具 1.0.0

一个面向 Windows 的 ADB 图形化工具，提供设备连接、截图、录屏、投屏控制、性能分析和常用文件操作。发布版 EXE 内置 ADB 与 scrcpy，电脑不需要另外安装或配置 ADB。

## 已实现功能

### 设备连接

- 自动刷新并选择已连接的 Android 设备。
- USB ADB 开启无线调试，并支持通过 IP/端口连接无线设备。
- 重启 ADB 服务。
- 设备信息自动读取并显示在当前操作区域。

### 截图、录屏与投屏

- 使用设备原生 `screencap` 截图，截图后自动保存并加入文件列表，最新文件置顶。
- 图片预览支持右键复制和删除。
- 使用设备原生 `screenrecord` 录屏，支持最长时长设置、录制计时和录制期间预览。
- 录屏结束后自动保存视频到文件列表，并清理预览缓存。
- 内嵌 scrcpy 投屏，支持电脑鼠标和键盘操作。
- 投屏窗口根据右侧预览区域动态适配大小，关闭后清理缓存。

### 应用与性能分析

- 获取当前前台应用并自动填入包名。
- 查看应用详情。
- 对指定应用进行性能监测，实时显示计时和日志。
- 生成包含帧渲染、卡顿帧、帧耗时、PSS 内存、Native/Dalvik Heap、CPU 快照和 `gfxinfo` 摘要的报告。
- 性能报告自动保存到文件列表，当前操作和文件内容均支持滚动查看与复制。

### 文件操作

- 安装 APK，支持勾选覆盖安装（`adb install -r`）。
- 卸载应用（`adb uninstall`）。
- 清除应用数据（`adb shell pm clear`）。
- 电脑文件传到手机（`adb push`），支持读取设备目录和选择手机目标路径。
- 手机文件传到电脑（`adb pull`），支持读取设备目录和选择电脑保存路径。
- 抓取当前应用日志，开始时计时，结束后自动生成 `.log` 文件。
- 文件列表支持按时间倒序排列，右键复制或删除文件。

### 设备操作

- 重启设备（`adb reboot`）。
- 关机设备（`adb shell reboot -p`）。

## 使用方式

直接运行发布目录中的 `adb_screenshot_tool_embedded.exe`。首次连接设备时，需要在手机上开启 USB 调试并确认授权提示。

无线连接流程：

1. USB 连接设备并点击“USB 开启”。
2. 在“无线连接”区域填写设备 IP 和端口，点击“连接”。
3. 连接成功后可以拔掉 USB，后续在同一网络下直接使用 IP/端口连接。

## 从源码构建

项目使用 Python、Tkinter、Pillow 和 PyInstaller。Windows PowerShell 中运行：

```powershell
python -m pip install -r requirements.txt
.\build.ps1
```

构建脚本会从 `vendor/scrcpy/scrcpy-win64-v3.3.3` 读取 ADB 与 scrcpy 文件，并生成单文件 EXE。发布版会把这些依赖一起打包，运行时不依赖电脑已有的 ADB 或 scrcpy。

## 目录说明

- `adb_screenshot_tool.py`：主程序。
- `build.ps1`：Windows 构建脚本。
- `adb_screenshot_tool_embedded.spec`：PyInstaller 配置参考。
- `vendor/scrcpy/`：随项目提供的 scrcpy 运行文件和 ADB 文件。

## 版本

当前版本：**1.0.0**
