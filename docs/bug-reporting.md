# Bug Reporting Guide

Good bug reports let maintainers reproduce the problem without guessing. If you
use an AI assistant, ask it to gather the fields below from real files, command
output, and screenshots on your machine.

Do not paste Tidal tokens, cookies, `.env` files, OAuth URLs, or credentials.

## What to include

- music-dl version: `music-dl --version`, app version text, or release tag
- app mode: desktop app, browser GUI, CLI, Docker/NAS, Discord bot, or installer
- platform: OS version, CPU architecture, and install target
- install/update path: first install, update, reinstall, source build, or edge
- last action before failure: the last thing that worked and the first thing
  that failed
- steps to reproduce: exact clicks, commands, URLs, track IDs, or album IDs
- expected behavior and actual behavior
- screenshots or screen recordings when the GUI is involved
- relevant logs with secrets removed
- workarounds tried, including restarts, reinstalls, config changes, or deleted
  files

## Local state checklist

Many desktop bugs come from local state that survives reinstall. Check the config
directory and report which files exist. Do not paste file contents unless asked.

Config directories:

- macOS/Linux: `~/.config/music-dl/`
- Windows: `%APPDATA%\music-dl\`
- Legacy installs may also have `~/.config/tidal-dl/`

Useful files to list:

- `settings.json`
- `daemon.json`
- `library.db`
- `library.db-wal`
- `library.db-shm`
- `library.db.corrupt-*`

## Safe commands

macOS/Linux:

```shell
music-dl --version
uname -a
ls -la ~/.config/music-dl 2>/dev/null
ls -la ~/.config/tidal-dl 2>/dev/null
```

Windows PowerShell:

```powershell
music-dl --version
[System.Environment]::OSVersion.VersionString
Get-ChildItem "$env:APPDATA\music-dl" -Force -ErrorAction SilentlyContinue
```

These commands list file names and system version information. Review output
before posting and remove anything private.

## Startup failures

For desktop startup failures, include the exact startup error and whether the
problem survives each of these:

1. Quit and reopen the app.
2. Restart the computer.
3. Reinstall the same version.
4. Install the latest release or edge build.

If deleting local files fixes the problem, name the files that were deleted. Do
not delete files only to create a report; the original state is useful evidence.
