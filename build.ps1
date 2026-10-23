$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = "D:\python\python.exe"
$scriptPath = Join-Path $projectRoot "adb_screenshot_tool.py"
$distPath = Join-Path $projectRoot "dist"
$buildPath = Join-Path $projectRoot "build"
$scrcpyPath = Join-Path $projectRoot "vendor\scrcpy\scrcpy-win64-v3.3.3"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "找不到 Python: $pythonPath"
}

if (-not (Test-Path -LiteralPath $scrcpyPath)) {
    throw "找不到投屏组件目录: $scrcpyPath"
}

# adb.exe 及投屏组件必须保留目录关系，程序启动时会自动从单文件 EXE 解压使用。
$adbFiles = @("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
$bundleArgs = @()
foreach ($fileName in $adbFiles) {
    $filePath = Join-Path $scrcpyPath $fileName
    if (-not (Test-Path -LiteralPath $filePath)) {
        throw "投屏组件文件缺失: $filePath"
    }
    $bundleArgs += "--add-binary"
    $bundleArgs += "$filePath;platform-tools"
}

# scrcpy.exe 还需要同目录的 FFmpeg/SDL DLL 和 scrcpy-server。
foreach ($scrcpyFile in (Get-ChildItem -LiteralPath $scrcpyPath -File)) {
    if ($adbFiles -contains $scrcpyFile.Name) {
        continue
    }
    $destination = "scrcpy"
    if ($scrcpyFile.Extension -in @(".exe", ".dll")) {
        $bundleArgs += "--add-binary"
    } else {
        $bundleArgs += "--add-data"
    }
    $bundleArgs += "$($scrcpyFile.FullName);$destination"
}

& $pythonPath -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "adb_screenshot_tool" `
    --distpath $distPath `
    --workpath $buildPath `
    $bundleArgs `
    $scriptPath

Write-Host "EXE 已生成: $(Join-Path $distPath 'adb_screenshot_tool.exe')"
