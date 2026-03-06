# Running tidal-dl with Docker

Docker lets you run tidal-dl on any machine — including headless servers and NAS devices — without installing Python or FFmpeg on the host.

The image contains:

- Python 3.12 (Debian bookworm-slim base)
- FFmpeg (installed in the image — no host FFmpeg required)
- tidal-dl and all Python dependencies

**Your credentials are never baked into the image.** Config and downloads are supplied via bind mounts at runtime; each user brings their own.

---

## Quick start

### 1. Build the image

Run from the **repository root** (the build context must include `TIDALDL-PY/`):

```shell
docker build -f docker/Dockerfile -t tidal-dl .
```

### 2. Download something

```shell
docker run --rm -it \
  -v "$HOME/.config/tidal-dl:/root/.config/tidal-dl" \
  -v "$HOME/tidal-downloads:/root/download" \
  tidal-dl https://tidal.com/browse/album/123456789
```

Replace `$HOME/tidal-downloads` with wherever you want files to land.

---

## Volume mounts

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `~/.config/tidal-dl` | `/root/.config/tidal-dl` | Settings, OAuth token, ISRC index — persisted across runs |
| `<your download dir>` | `/root/download` | Downloaded tracks, albums, playlists |
| `<your music library>` (optional, read-only) | any path | Library scanning with `tidal-dl scan` |

The config directory is created automatically on first run if it does not exist.

---

## Login (optional)

tidal-dl works **without logging in** when the default Hi-Fi API source is available. On first run you will see:

```
Not logged in. Run 'tidal-dl login' for OAuth fallback and favourites.
```

You can ignore this and download immediately, or log in now or later.

### Logging in

Login uses a browser-based OAuth flow. Run the container interactively with the same config volume:

```shell
docker run --rm -it \
  -v "$HOME/.config/tidal-dl:/root/.config/tidal-dl" \
  tidal-dl login
```

A clickable link will be printed. Open it in your browser, complete the Tidal login, and the token is saved to the mounted config directory. Subsequent runs reuse the stored token automatically.

### Sharing credentials between machines

Copy or sync `~/.config/tidal-dl/` to the other machine and mount it the same way. No re-login needed.

---

## Using docker compose

A `docker-compose.yml` is provided in this folder for convenience.

```shell
# Download a URL
docker compose -f docker/docker-compose.yml run --rm tidal-dl https://tidal.com/browse/album/123456789

# Log in
docker compose -f docker/docker-compose.yml run --rm tidal-dl login

# Show config
docker compose -f docker/docker-compose.yml run --rm tidal-dl cfg
```

Override the config or download paths with environment variables:

```shell
TIDAL_CONFIG=/mnt/nas/tidal-config \
TIDAL_DOWNLOADS=/mnt/nas/Music \
docker compose -f docker/docker-compose.yml run --rm tidal-dl https://tidal.com/browse/album/123456789
```

---

## Headless / server use

For scheduled or non-interactive runs, omit `-it` and ensure `tidal-dl login` has been run at least once with the config volume:

```shell
docker run --rm \
  -v "/mnt/nas/tidal-config:/root/.config/tidal-dl" \
  -v "/mnt/nas/Music:/root/download" \
  tidal-dl https://tidal.com/browse/album/123456789
```

Add this to a cron job or systemd timer as needed.

---

## Library scanning

Mount your existing music library read-only and run `tidal-dl scan` to seed the ISRC duplicate index:

```shell
docker run --rm -it \
  -v "$HOME/.config/tidal-dl:/root/.config/tidal-dl" \
  -v "$HOME/tidal-downloads:/root/download" \
  -v "/mnt/nas/Music:/mnt/music:ro" \
  tidal-dl scan add /mnt/music

docker run --rm -it \
  -v "$HOME/.config/tidal-dl:/root/.config/tidal-dl" \
  -v "$HOME/tidal-downloads:/root/download" \
  -v "/mnt/nas/Music:/mnt/music:ro" \
  tidal-dl scan
```

---

## Publishing the image

Publishing the image to Docker Hub or GHCR is safe. The image contains no credentials. Anyone who pulls the image must supply their own config volume and run their own `tidal-dl login`.

```shell
docker tag tidal-dl youruser/tidal-dl:latest
docker push youruser/tidal-dl:latest
```

Others can then run:

```shell
docker run --rm -it \
  -v "$HOME/.config/tidal-dl:/root/.config/tidal-dl" \
  -v "$HOME/tidal-downloads:/root/download" \
  youruser/tidal-dl:latest https://tidal.com/browse/album/123456789
```
