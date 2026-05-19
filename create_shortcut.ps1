# create_shortcut.ps1
# Creates a desktop shortcut for original launcher
# Usage: powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1

$launcherDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pywFile     = Join-Path $launcherDir "start.pyw"

# Resolve pythonw.exe (runs without a console window)
$pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($pythonwCmd) {
    $pythonw = $pythonwCmd.Source
} else {
    $pythonExe = (Get-Command python.exe -ErrorAction Stop).Source
    $pythonw   = $pythonExe -replace "python\.exe$", "pythonw.exe"
}

if (-not (Test-Path $pythonw)) {
    Write-Warning "pythonw.exe not found at: $pythonw"
    Write-Warning "Falling back to python.exe (a console window will briefly appear on launch)"
    $pythonw = (Get-Command python.exe).Source
}

# Create shortcut on the desktop
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "original-launcher.lnk"

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath       = $pythonw
$sc.Arguments        = "`"$pywFile`""
$sc.WorkingDirectory = $launcherDir
$sc.Description      = "original launcher - file manager"
$sc.IconLocation     = "$pythonw,0"
$sc.HotKey           = "CTRL+ALT+L"
$sc.Save()

Write-Host ""
Write-Host "Shortcut created: $lnkPath" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Double-click 'original-launcher' on the desktop to launch"
Write-Host "  2. Right-click the shortcut -> Pin to taskbar"
Write-Host "  3. Keyboard shortcut: Ctrl+Alt+L (works from the desktop shortcut)"
Write-Host "     After pinning to taskbar, Win+[number] also works"
Write-Host ""
