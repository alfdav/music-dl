$ErrorActionPreference = "Stop"

$Repo = "alfdav/music-dl"
$AppName = "music-dl"

function Say($Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Yellow
}

function Fail($Message) {
  Write-Error $Message
  exit 1
}

try {
  Say "Fetching latest release info"
  $Release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest"
  $Asset = $Release.assets | Where-Object { $_.browser_download_url -like "*.msi" } | Select-Object -First 1
  if (-not $Asset) {
    Fail "No MSI found in the latest release."
  }

  $Digest = [string]$Asset.digest
  if (-not $Digest.StartsWith("sha256:")) {
    Fail "No SHA-256 digest found for the Windows MSI in the latest GitHub release."
  }
  $ExpectedSha256 = $Digest.Substring(7).ToLowerInvariant()

  $TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("music-dl-" + [System.Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
  $Installer = Join-Path $TempDir ([System.IO.Path]::GetFileName($Asset.browser_download_url))

  Say "Downloading $AppName $($Release.tag_name)"
  Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $Installer

  Say "Verifying download checksum"
  $ActualSha256 = (Get-FileHash -Algorithm SHA256 -Path $Installer).Hash.ToLowerInvariant()
  if ($ActualSha256 -ne $ExpectedSha256) {
    Fail "Refusing to install because the downloaded MSI checksum does not match GitHub's release digest."
  }
  Write-Host "==> Checksum verified" -ForegroundColor Green

  Say "Starting Windows installer"
  $Process = Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", "`"$Installer`"") -Wait -PassThru
  if ($Process.ExitCode -ne 0) {
    Fail "Windows installer exited with code $($Process.ExitCode)."
  }

  Write-Host "==> $AppName $($Release.tag_name) installed" -ForegroundColor Green
} finally {
  if ($TempDir -and (Test-Path $TempDir)) {
    Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
  }
}
