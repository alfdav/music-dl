$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:MUSIC_DL_INSTALLER_REPO_URL) { $env:MUSIC_DL_INSTALLER_REPO_URL } else { "git@github.com:alfdav/music-dl.git" }
$CacheRoot = if ($env:MUSIC_DL_INSTALLER_CACHE_DIR) {
  $env:MUSIC_DL_INSTALLER_CACHE_DIR
} elseif ($env:LOCALAPPDATA) {
  Join-Path $env:LOCALAPPDATA "music-dl-installer"
} else {
  Join-Path $HOME ".music-dl-installer"
}
$RepoDir = Join-Path $CacheRoot "repo"
$AppName = "music-dl"

function Say($Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Yellow
}

function Ok($Message) {
  Write-Host "==> $Message" -ForegroundColor Green
}

function Fail($Message) {
  Write-Error $Message
  exit 1
}

function Require-Command($Name, $InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Fail "$Name is required. $InstallHint Then rerun this installer."
  }
}

function Require-Tools {
  Say "Checking build tools"
  Require-Command "git" "Install Git for Windows."
  Require-Command "uv" "Install uv from https://docs.astral.sh/uv/."
  Require-Command "bun" "Install Bun from https://bun.sh/docs/installation."
  Require-Command "rustc" "Install Rust from https://rustup.rs."
}

function Sync-Repo {
  Say "Syncing music-dl source"
  New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null

  if ((Test-Path $RepoDir) -and -not (Test-Path (Join-Path $RepoDir ".git"))) {
    Remove-Item -Recurse -Force $RepoDir -ErrorAction Stop
  }

  if (-not (Test-Path (Join-Path $RepoDir ".git"))) {
    git clone $RepoUrl $RepoDir
  }

  git -C $RepoDir remote set-url origin $RepoUrl
  git -C $RepoDir fetch origin --prune
  git -C $RepoDir remote set-head origin -a | Out-Null
  $DefaultRef = (git -C $RepoDir symbolic-ref refs/remotes/origin/HEAD) -replace "^refs/remotes/origin/", ""
  if (-not $DefaultRef) {
    Fail "Could not resolve the remote default branch. Delete $CacheRoot and rerun this installer."
  }

  git -C $RepoDir checkout -B $DefaultRef "origin/$DefaultRef"
  git -C $RepoDir reset --hard "origin/$DefaultRef"
  git -C $RepoDir clean -fdx
}

function Build-Msi {
  Say "Building Windows MSI from source"
  $AppDir = Join-Path $RepoDir "tidaldl-py"
  if (-not (Test-Path $AppDir)) {
    Fail "Could not find $AppDir. Delete $CacheRoot and rerun this installer."
  }

  Push-Location $AppDir
  try {
    uv sync --extra build
    bun install

    $TargetTriple = (rustc --print host-tuple).Trim()
    uv run pyinstaller --clean `
      --distpath src-tauri/binaries `
      --workpath build/pyinstaller `
      --noconfirm `
      build/pyinstaller/music-dl-server.spec

    $SidecarTarget = "src-tauri/binaries/music-dl-server-$TargetTriple.exe"
    Move-Item -Force "src-tauri/binaries/music-dl-server.exe" $SidecarTarget

    bunx tauri build --target $TargetTriple --bundles msi --config src-tauri/tauri.ci.conf.json

    $Msi = Get-ChildItem -Path "src-tauri/target/$TargetTriple/release/bundle/msi" -Filter "*.msi" |
      Sort-Object LastWriteTime -Descending |
      Select-Object -First 1
    if (-not $Msi) {
      Fail "No MSI was produced. Check the Tauri output above, then rerun this installer."
    }

    return $Msi.FullName
  } finally {
    Pop-Location
  }
}

function Install-Msi($MsiPath) {
  Say "Starting Windows installer"
  $Process = Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", "`"$MsiPath`"") -Wait -PassThru
  if ($Process.ExitCode -ne 0) {
    Fail "Windows installer exited with code $($Process.ExitCode)."
  }
  Ok "$AppName installed from source"
}

function Main {
  Require-Tools
  Sync-Repo
  $MsiPath = Build-Msi
  Install-Msi $MsiPath
}

Main
