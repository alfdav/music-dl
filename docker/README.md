# Running music-dl with Docker

Docker is the simplest way to run music-dl on Linux, a NAS, or any machine without Python and FFmpeg configured.

The image includes Python 3.12, FFmpeg, and the music-dl package. It runs as a **non-root user** (UID 1000) and binds to **localhost only** by default.

You need your own active Tidal account. music-dl does not provide access to
Tidal without sign-in.

---

## GUI Mode (recommended)

Launch the browser-based player and library manager:

```shell
curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install-docker.sh | bash
```

Open [http://localhost:8765](http://localhost:8765). Done.

Manual source checkout still works:

```shell
git clone git@github.com:alfdav/music-dl.git
cd music-dl
MUSIC_DL_UI_SECRET="$(openssl rand -hex 32)" \
  docker compose -f docker/docker-compose.yml up gui -d
```

`MUSIC_DL_UI_SECRET` is required. Bind-all will not mint one, and `GET /` does not set a cookie. Keep the value and send it as `X-Music-DL-UI` on mutating and `/api/auth` requests.

The setup wizard walks you through Tidal login and library configuration on first launch.

### Customizing paths

```shell
MUSIC_DL_UI_SECRET="$(openssl rand -hex 32)" \
MUSIC_DL_CONFIG=~/.my-config \
MUSIC_DL_DOWNLOADS=/mnt/nas/music \
  docker compose -f docker/docker-compose.yml up gui -d
```

### LAN access

Direct LAN access is not supported. `MUSIC_DL_HOST=0.0.0.0` can publish the
Docker port on every host interface, but application Host and CORS validation
still accept localhost origins only. Keep the default bind unless you add and
validate an authenticated reverse-proxy deployment.

### Logs, restart, stop

```shell
# View logs
docker compose -f docker/docker-compose.yml logs gui -f

# Restart
docker compose -f docker/docker-compose.yml restart gui

# Stop and remove
docker compose -f docker/docker-compose.yml down
```

### Updating

```shell
cd music-dl
git pull
docker compose -f docker/docker-compose.yml build gui
MUSIC_DL_UI_SECRET="$MUSIC_DL_UI_SECRET" \
  docker compose -f docker/docker-compose.yml up gui -d
```

---

## CLI Mode

For downloads, login, and other terminal commands:

```shell
# Login (interactive — prints a URL for OAuth)
docker compose -f docker/docker-compose.yml run --rm --profile cli cli login

# Download an album
docker compose -f docker/docker-compose.yml run --rm --profile cli cli dl https://tidal.com/browse/album/123456789

# View/edit settings
docker compose -f docker/docker-compose.yml run --rm --profile cli cli cfg
```

### Standalone docker run

If you prefer `docker run` over compose:

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/home/musicdl/.config/music-dl" \
  -v "$HOME/Music:/home/musicdl/download" \
  music-dl login
```

```shell
docker run --rm \
  -v "$HOME/.config/music-dl:/home/musicdl/.config/music-dl" \
  -v "$HOME/Music:/home/musicdl/download" \
  music-dl dl https://tidal.com/browse/track/123456789
```

---

## Volume Mounts

| Host path (default) | Container path | Purpose |
| --- | --- | --- |
| `~/.config/music-dl` | `/home/musicdl/.config/music-dl` | Settings, tokens, duplicate index, DB |
| `~/Music` | `/home/musicdl/download` | Downloaded media and local library |

Optional:

| Host path | Container path | Purpose |
| --- | --- | --- |
| `/mnt/nas/Music` | `/home/musicdl/library:ro` | Existing library (read-only scan) |

---

## Environment Variables

| Variable | Default | What it does |
| --- | --- | --- |
| `MUSIC_DL_HOST` | `127.0.0.1` | Host-side published address; changing it alone does not enable supported LAN access |
| `MUSIC_DL_PORT` | `8765` | Host-side port |
| `MUSIC_DL_CONFIG` | `~/.config/music-dl` | Config volume source path |
| `MUSIC_DL_DOWNLOADS` | `~/Music` | Downloads volume source path |

Inside the container (set automatically by the Dockerfile):

| Variable | Value | What it does |
| --- | --- | --- |
| `MUSIC_DL_BIND_ALL` | `1` | Explicit opt-in to bind `0.0.0.0` inside the container. Outside Docker the server stays on `127.0.0.1`. |
| `MUSIC_DL_UI_SECRET` | _(required)_ | Operator-held secret. Bind-all refuses to start without it. GET `/` does not set a cookie; send `X-Music-DL-UI` on mutating and `/api/auth` requests. |
| `MUSIC_DL_CONFIG_DIR` | `/home/musicdl/.config/music-dl` | Config directory override |

---

## Headless / NAS / Cron

For scheduled downloads without a terminal:

```shell
docker run --rm \
  -v "/mnt/nas/music-dl-config:/home/musicdl/.config/music-dl" \
  -v "/mnt/nas/Music:/home/musicdl/download" \
  music-dl dl https://tidal.com/browse/album/123456789
```

Works with cron, systemd timers, and NAS task schedulers. Login must be completed interactively at least once before headless runs will work.

---

## Building the Image

```shell
docker build -f docker/Dockerfile -t music-dl .
```

The image is safe to publish — no credentials are baked in. Consumers mount their own config directory.

---

## What the Image Does Not Do

- Bundle your TIDAL token — you authenticate after first run
- Persist anything without volume mounts — no mounts = no state
- Auto-discover files on the host — explicit volume mounts only
- Process audio in any way — playback goes direct from file to browser
