# Tauri Deep Link Manual Smoke

This is a manual checklist for desktop protocol handling. Unit tests cover route parsing and navigation string escaping, but OS protocol registration must be checked against an installed app.

## Baseline

- `tauri.conf.json` registers the `music-dl` desktop scheme.
- `src-tauri/src/lib.rs` parses only `music-dl://` launch URLs.
- Installing or mounting the DMG does not start the daemon.
- The daemon starts only when the user launches `music-dl.app` or runs `music-dl gui`.

## macOS

1. Build the DMG:

```shell
cd tidaldl-py
bunx tauri build --bundles dmg
```

2. Install the bundled app to `/Applications/music-dl.app`.
3. Confirm no daemon starts just from mounting or installing the DMG.
4. Launch the app normally and confirm it opens home.
5. With the app closed, run:

```shell
open 'music-dl://open#search'
```

Expected: app opens and lands on Search.

6. With the app already open, run:

```shell
open 'music-dl://open#artist:AC%2FDC'
```

Expected: existing app receives focus and lands on the artist route.

7. Run:

```shell
open "music-dl://open#artist:O'Hara"
```

Expected: navigation does not break from the single quote.

## Linux

Use an installed `.deb` / AppImage integration, or rely on the runtime `register_all()` path in development.

```shell
xdg-open 'music-dl://open#search'
```

Expected: app opens or focuses and lands on Search.

## Windows

Use an installed MSI / packaged app, or rely on the runtime `register_all()` path in development.

```shell
start music-dl://open#search
```

Expected: app opens or focuses and lands on Search.
