# Launcher ショートカット作成スクリプト
# 実行: PowerShell で .\create_shortcut.ps1

$launcherDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pywFile     = Join-Path $launcherDir "start.pyw"

# pythonw.exe のパスを解決 (コンソールなし実行用)
$pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($pythonwCmd) {
    $pythonw = $pythonwCmd.Source
} else {
    $pythonExe = (Get-Command python.exe -ErrorAction Stop).Source
    $pythonw   = $pythonExe -replace "python\.exe$", "pythonw.exe"
}

if (-not (Test-Path $pythonw)) {
    Write-Warning "pythonw.exe が見つかりません: $pythonw"
    Write-Warning "python.exe で代用します (コンソールウィンドウが一瞬出ます)"
    $pythonw = (Get-Command python.exe).Source
}

# デスクトップにショートカットを作成
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "Launcher.lnk"

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath      = $pythonw
$sc.Arguments       = "`"$pywFile`""
$sc.WorkingDirectory = $launcherDir
$sc.Description     = "Launcher - Total Commander互換ファイルマネージャー"
$sc.IconLocation    = "$pythonw,0"
$sc.HotKey          = "CTRL+ALT+L"
$sc.Save()

Write-Host ""
Write-Host "✓ デスクトップに Launcher.lnk を作成しました" -ForegroundColor Green
Write-Host "  場所: $lnkPath"
Write-Host ""
Write-Host "【次の手順】"
Write-Host "  1. ダブルクリック起動: デスクトップの「Launcher」をダブルクリック"
Write-Host "  2. タスクバーに追加:   デスクトップの「Launcher」を右クリック"
Write-Host "                         →「タスクバーにピン留めする」"
Write-Host "  3. キーボード起動:     デスクトップのショートカットから Ctrl+Alt+L"
Write-Host "     ※ タスクバーピン留め後は Win+数字キー (Win+1 等) で起動できます"
Write-Host ""
