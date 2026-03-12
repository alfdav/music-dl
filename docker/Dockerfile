# Build context must be the repository root:
#   docker build -f docker/Dockerfile -t music-dl .

FROM python:3.12-slim-bookworm

# Install FFmpeg and clean up apt cache in one layer
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy only the package source; keeps the layer small
COPY TIDALDL-PY /app/TIDALDL-PY

WORKDIR /app/TIDALDL-PY

# Install music-dl and its Python dependencies
RUN pip install --no-cache-dir .

# Config and downloads are provided by the caller via bind mounts:
#   ~/.config/music-dl  → /root/.config/music-dl
#   <download dir>      → /root/download
VOLUME ["/root/.config/music-dl", "/root/download"]

ENTRYPOINT ["music-dl"]
