# macOS Local Installer — Design Spec

**Goal:** Give macOS users an easy, supported install path for the Tauri app without relying on public macOS release binaries or auto-update.

**Target audience:** macOS users willing to run one install command and follow guided dependency setup prompts.

**Scope:** A guided local-build installer that ends with `/Applications/music-dl.app`, plus README/docs updates. Does NOT include public macOS release packaging, notarization, or macOS auto-update.

---

## 1. Product Decision

### Supported macOS path
macOS support is a **manual/local-build workflow**:
- user runs a single installer command
- installer checks prerequisites
- installer prints exact fixes when prerequisites are missing
- user reruns the same command after fixing them
- installer builds the Tauri app locally
- installer copies the result to `/Applications/music-dl.app`

### Explicitly unsupported path
The project does **not** treat GitHub-hosted macOS binaries as the supported install/update path. Linux remains the public release/update target.

---

## 2. User Experience

### Entry command
Primary install command:

```bash
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-macos-local.sh | bash
```

For tagged documentation or release notes, prefer a tag-pinned form so the installer content is stable for that version. The branch form above is acceptable for README "latest" docs, but deterministic reruns only apply once a specific installer revision has been fetched.

The command should be safe to rerun. Re-running is the official recovery flow after dependency installation.

### Success path
On a machine with all prerequisites installed, the script should:
1. create or update a local clone/cache of the repo
2. build the macOS Tauri app locally
3. replace `/Applications/music-dl.app`
4. print success with next-step guidance
5. optionally launch the app (nice-to-have, not required for v1)

### Guided failure path
If a prerequisite is missing, the script should stop immediately and tell the user exactly what to do.

Examples:
- **Missing Xcode Command Line Tools:** trigger `xcode-select --install` when possible, then print: “Finish the Apple installer, then rerun the same command.”
- **Missing Rust:** print the install command or URL, then tell the user to rerun.
- **Missing `uv`:** print the install command, then tell the user to rerun.
- **Missing Node.js + npm:** print the install command, then tell the user to rerun.

The script should not try to hide these requirements or continue in a half-installed state.

---

## 3. Installer Behavior

### OS gate
The script must verify it is running on macOS before doing anything else.

### Dependency checks
Check prerequisites in this order:
1. Xcode Command Line Tools
2. Rust toolchain
3. `uv`
4. Node.js + npm
5. Apple Silicon (`arm64`) runtime

For v1, Node.js is mandatory. Bun is out of scope for the installer to avoid branching the build path.

Rationale:
- CLT is the hardest blocker and may require user interaction
- the rest are ordinary CLI dependencies
- failing fast avoids wasting time cloning/building before the environment is ready

### Repository strategy
Use a deterministic local working directory for repeated installs, for example under the user cache/home directory. Requirements:
- safe to rerun
- updates existing clone instead of recloning every time
- clear enough for troubleshooting

For v1, reruns must be deterministic:
- if the cached clone is missing, clone fresh
- if the cached clone exists, fetch origin, resolve the remote default branch via `origin/HEAD`, hard-reset to that branch tip, and clean untracked build artifacts before building
- do not try to preserve local user edits inside the cache directory

The script should build from the repo’s remote default branch unless the user explicitly overrides it via an environment variable or script flag (nice-to-have, optional for v1).

### Build steps
The installer should follow the documented local build path:

```bash
cd TIDALDL-PY
uv sync
uv pip install pyinstaller
npm install
npx tauri build
```

Use the Node/npm path consistently in the script to reduce branching. Simplicity beats flexibility here.

### Install step
After a successful build:
- locate the generated `.app`
- remove/replace any existing `/Applications/music-dl.app`
- copy the new app into `/Applications/music-dl.app`

For v1, the installer should attempt the copy without `sudo`. If writing to `/Applications` fails, it should stop and print a manual fallback command (for example with `sudo cp -R ... /Applications/music-dl.app`) plus a rerun/update note. The installer should not silently elevate privileges.

---

## 4. Script Shape

### File
Add a checked-in script at:
- `scripts/install-macos-local.sh`

The curl one-liner should only fetch this checked-in script. No hidden remote bootstrap logic.

### Output style
The script should be verbose and human-readable:
- print current step headings
- print exact failing dependency
- print exact rerun instruction
- never dump vague shell errors without context

### Idempotence
Re-running the script should be normal behavior, not a failure mode.

Expected rerun scenarios:
- after CLT install finishes
- after Rust install finishes
- after `uv` install finishes
- after Node.js + npm install finishes
- after a prior partial clone/build failure

---

## 5. Documentation

### README
Update the macOS install story so it says:
- Linux public releases are downloadable
- macOS uses a local-build install command
- updates on macOS are manual: rerun the installer or rebuild locally

### Additional docs
A dedicated doc is optional. For v1, the script header comments plus README may be enough.

### Messaging
Be honest:
- “macOS Tauri app supported via local build”
- not “macOS binary release supported”
- not “auto-update supported on macOS”

---

## 6. Supported macOS Targets

V1 support target:
- macOS on Apple Silicon (`arm64`)

The installer must explicitly gate on `uname -m` and stop with a clear unsupported/untested message on Intel Macs.

Intel macOS support is out of scope unless verified separately. The current documented local Tauri usage on this machine is Apple Silicon, so the installer should be explicit about the tested target instead of implying universal Mac support.

## 7. Error Handling

The script must explicitly handle and message:
- non-macOS execution
- missing CLT
- missing Rust
- missing `uv`
- missing Node.js + npm
- git clone/update failure
- local build failure
- built app not found
- failed copy into `/Applications`

Every failure message should include the next action and a rerun instruction.

---

## 8. Verification

### Minimum verification for implementation
- shell syntax check for the installer script
- dry validation of branch/cache path logic
- local run on this machine through at least one missing-dependency or happy-path branch
- confirmation that a successful run leaves an app at `/Applications/music-dl.app`

### Non-goals for verification
- no claim that public macOS release artifacts are fixed
- no claim of macOS auto-update support
- no Apple signing/notarization work

---

## 9. Out of Scope

- macOS public binary release packaging
- Apple signing/notarization
- macOS auto-update
- Homebrew formula/tap
- background self-resume installer state machine
- cross-platform installer unification

---

## Recommendation

Implement the local installer as a checked-in shell script with a curl entrypoint, fail-fast prerequisite checks, and a deliberate “fix dependency, then rerun” workflow. This is the simplest honest install path that matches current project constraints.
