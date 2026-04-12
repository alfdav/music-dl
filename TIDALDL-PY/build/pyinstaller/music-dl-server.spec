# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for music-dl sidecar binary.

Bundles the full tidal_dl package tree, static assets, and all runtime
dependencies that PyInstaller cannot discover via static analysis
(uvicorn factory import, FastAPI/Starlette internals, tidalapi, etc.).
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_DIR = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# ── tidal_dl is a local source package (not pip-installed).             ──
# ── Python modules are pulled in via hiddenimports below.               ──
# ── We only need to add non-Python data files (static assets) as datas. ──
static_dir = os.path.join(PROJECT_DIR, "tidal_dl", "gui", "static")
tidal_datas = [(static_dir, os.path.join("tidal_dl", "gui", "static"))]

# All tidal_dl submodules as hidden imports (PyInstaller can't trace
# the uvicorn.run("tidal_dl.gui:create_app") dynamic import)
tidal_hidden = [
    "tidal_dl",
    "tidal_dl.api",
    "tidal_dl.cli",
    "tidal_dl.config",
    "tidal_dl.constants",
    "tidal_dl.dash",
    "tidal_dl.download",
    "tidal_dl.gui",
    "tidal_dl.gui.api",
    "tidal_dl.gui.api.albums",
    "tidal_dl.gui.api.downloads",
    "tidal_dl.gui.api.duplicates",
    "tidal_dl.gui.api.home",
    "tidal_dl.gui.api.library",
    "tidal_dl.gui.api.playback",
    "tidal_dl.gui.api.playlists",
    "tidal_dl.gui.api.search",
    "tidal_dl.gui.api.settings",
    "tidal_dl.gui.api.setup",
    "tidal_dl.gui.api.upgrade",
    "tidal_dl.gui.security",
    "tidal_dl.gui.server",
    "tidal_dl.helper",
    "tidal_dl.helper.cache",
    "tidal_dl.helper.camelot",
    "tidal_dl.helper.checkpoint",
    "tidal_dl.helper.cli",
    "tidal_dl.helper.decorator",
    "tidal_dl.helper.decryption",
    "tidal_dl.helper.exceptions",
    "tidal_dl.helper.isrc_index",
    "tidal_dl.helper.library_db",
    "tidal_dl.helper.library_scanner",
    "tidal_dl.helper.path",
    "tidal_dl.helper.playlist_import",
    "tidal_dl.helper.tidal",
    "tidal_dl.helper.waveform",
    "tidal_dl.helper.wrapper",
    "tidal_dl.hifi_api",
    "tidal_dl.metadata",
    "tidal_dl.model",
    "tidal_dl.model.cfg",
    "tidal_dl.model.downloader",
    "tidal_dl.model.meta",
]

# ── Third-party hidden imports: dynamically loaded at runtime ────────
dep_hidden = [
    # --- FastAPI / Starlette ---
    *collect_submodules("fastapi"),
    *collect_submodules("starlette"),

    # --- Uvicorn internals ---
    *collect_submodules("uvicorn"),

    # --- Pydantic (FastAPI depends on it) ---
    *collect_submodules("pydantic"),
    *collect_submodules("pydantic_core"),

    # --- HTTP / networking ---
    "requests",
    "requests.adapters",
    *collect_submodules("urllib3"),

    # --- Tidal API client ---
    *collect_submodules("tidalapi"),

    # --- Audio metadata ---
    *collect_submodules("mutagen"),

    # --- Crypto (decryption pipeline) ---
    *collect_submodules("Crypto"),

    # --- Data serialization ---
    *collect_submodules("dataclasses_json"),
    *collect_submodules("marshmallow"),

    # --- Other deps ---
    "m3u8",
    "toml",
    "pathvalidate",
    "coloredlogs",
    *collect_submodules("rich"),
    *collect_submodules("typer"),
    *collect_submodules("ffmpeg"),

    # --- anyio / sniffio (uvicorn async backend) ---
    *collect_submodules("anyio"),
    "sniffio",

    # --- multipart (starlette form parsing) ---
    "multipart",

    # --- httptools / websockets (optional uvicorn speedups) ---
    "httptools",
    "websockets",

    # --- typing_extensions / annotated_types (pydantic) ---
    "typing_extensions",
    "annotated_types",

    # --- certifi (SSL certs for requests) ---
    "certifi",

    # --- stdlib sometimes missed ---
    "sqlite3",
    "json",
    "xml.etree.ElementTree",
    "email.mime.multipart",
    "email.mime.text",
]

hidden_imports = list(set(tidal_hidden + dep_hidden))

a = Analysis(
    [os.path.join(PROJECT_DIR, "sidecar_entry.py")],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=tidal_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "PIL",
        "IPython",
        "notebook",
        "pytest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="music-dl-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity="-",
    entitlements_file=None,
)
