# Full reset / uninstall for music-dl on Windows 10/11.
# Usage: irm https://raw.githubusercontent.com/STEPPING3DCAD/music-dl/master/scripts/reset.ps1 | iex
#
# Removes: app install, config dir, caches, logs, pip and uv package.
# Does NOT touch your downloaded music library.

$ErrorActionPreference = 'SilentlyContinue'

$AppName  = 'music-dl'
$BundleId = 'com.alfdav.music-dl'

function Say  { param($msg) Write-Host "`n==> $msg" -ForegroundColor Yellow }
function Ok   { param($msg) Write-Host "    $msg"  -ForegroundColor Green }
function Skip { Write-Host '    (not found, skipping)' }

function Remove-IfExists {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
        Ok "Removed: $Path"
    } else {
        Skip
    }
}

Say 'Stopping any running music-dl processes'
Get-Process | Where-Object { $_.Name -like '*music-dl*' -or $_.Name -like '*musicdl*' } |
    Stop-Process -Force
Start-Sleep -Seconds 1

Say 'Removing installed app (MSI)'
$installed = Get-WmiObject Win32_Product | Where-Object { $_.Name -like "*music-dl*" }
if ($installed) {
    $installed | ForEach-Object { $_.Uninstall() | Out-Null }
    Ok 'MSI package uninstalled'
} else { Skip }

Say 'Removing config and credentials'
Remove-IfExists "$env:USERPROFILE\.config\$AppName"
Remove-IfExists "$env:APPDATA\$AppName"
Remove-IfExists "$env:APPDATA\$BundleId"

Say 'Removing caches'
Remove-IfExists "$env:LOCALAPPDATA\$AppName"
Remove-IfExists "$env:LOCALAPPDATA\$BundleId"
Remove-IfExists "$env:LOCALAPPDATA\$BundleId.ShellHost"

Say 'Uninstalling pip package (musicdl)'
try {
    if (& python -m pip show musicdl 2>$null) {
        & python -m pip uninstall -y musicdl
        Ok 'pip package removed'
    } else { Skip }
} catch { Skip }

Say 'Removing uv tool'
try {
    if ((Get-Command uv -ErrorAction SilentlyContinue) -and ((& uv tool list 2>$null) -match 'music-dl')) {
        & uv tool uninstall music-dl
        Ok 'uv tool removed'
    } else { Skip }
} catch { Skip }

Write-Host "`nDone." -ForegroundColor Green
Write-Host 'music-dl has been fully removed. Your music library was not touched.'
Write-Host 'To reinstall: irm https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.ps1 | iex'
