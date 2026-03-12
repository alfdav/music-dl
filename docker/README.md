# Running music-dl with Docker

Docker is the simplest way to run `music-dl` on a machine that does not already have Python and FFmpeg configured.

The image includes:

- Python 3.12
- FFmpeg
- the `music-dl` package and its Python dependencies

The image does **not** include your credentials or personal config. Those are mounted in at runtime.

---

## Quick Start

Build from the repository root:

```shell
docker build -f docker/Dockerfile -t music-dl .
```

Run a download:

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  music-dl https://tidal.com/browse/album/123456789
```

Container paths:

- config: `/root/.config/music-dl`
- downloads: `/root/download`

If you previously used `tidal-dl`, the old `~/.config/tidal-dl/` directory is migrated automatically on first run.

---

## Required Mounts

| Host path | Container path | Purpose |
| --- | --- | --- |
| `~/.config/music-dl` | `/root/.config/music-dl` | settings, token, duplicate index, checkpoints |
| `~/music-downloads` | `/root/download` | downloaded media |

Optional extra mount:

| Host path | Container path | Purpose |
| --- | --- | --- |
| `/path/to/library` | any path | existing library scan input |

---

## Login Flow

The default source is `hifi_api`, so direct URL downloads can work without logging in first.

You still want `music-dl login` when you need:

- favourites downloads
- an OAuth fallback session
- your personal session cached inside the mounted config directory

Run login interactively:

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  music-dl login
```

What happens:

1. the app prints a browser URL
2. you complete the OAuth flow outside the container
3. the token is saved into the mounted config directory
4. future runs reuse that token automatically

---

## Common Docker Commands

### Direct download

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  music-dl https://tidal.com/browse/track/123456789
```

### Batch download from a file

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  -v "$PWD:/work" \
  music-dl dl --list /work/urls.txt
```

### Favourites

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  music-dl dl_fav tracks --since 2026-01-01
```

### Import playlist file

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  -v "$PWD:/work" \
  music-dl import /work/my_playlist.csv
```

### Seed duplicate index from an existing library

```shell
docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  -v "/mnt/nas/Music:/mnt/music:ro" \
  music-dl scan add /mnt/music

# later

docker run --rm -it \
  -v "$HOME/.config/music-dl:/root/.config/music-dl" \
  -v "$HOME/music-downloads:/root/download" \
  -v "/mnt/nas/Music:/mnt/music:ro" \
  music-dl scan
```

---

## Docker Compose

This repo includes [docker/docker-compose.yml](docker/docker-compose.yml).

Examples:

```shell
docker compose -f docker/docker-compose.yml run --rm music-dl https://tidal.com/browse/album/123456789
docker compose -f docker/docker-compose.yml run --rm music-dl login
docker compose -f docker/docker-compose.yml run --rm music-dl cfg
```

Override the default host paths with environment variables:

```shell
MUSIC_DL_CONFIG=/mnt/nas/music-dl-config \
MUSIC_DL_DOWNLOADS=/mnt/nas/Music \
docker compose -f docker/docker-compose.yml run --rm music-dl https://tidal.com/browse/album/123456789
```

The compose file uses:

- service name: `music-dl`
- config env var: `MUSIC_DL_CONFIG`
- download env var: `MUSIC_DL_DOWNLOADS`

---

## Headless Use

For non-interactive scheduled runs, remove `-it` after you have already completed login at least once:

```shell
docker run --rm \
  -v "/mnt/nas/music-dl-config:/root/.config/music-dl" \
  -v "/mnt/nas/Music:/root/download" \
  music-dl https://tidal.com/browse/album/123456789
```

That works well for:

- cron
- systemd timers
- NAS automation
- CI jobs that already have a mounted config directory

---

## Publish the Image

The image is safe to publish because credentials are not baked into it.

```shell
docker tag music-dl youruser/music-dl:latest
docker push youruser/music-dl:latest
```

Consumers still need their own mounted config directory and their own login.

---

## What the Image Does Not Do

The image does not:

- bundle your TIDAL token
- persist downloads unless you mount `/root/download`
- persist settings unless you mount `/root/.config/music-dl`
- auto-discover files on the host without an explicit volume mount
