# Build context must be the repository root:
#   docker build -f docker/Dockerfile -t music-dl .
#
# Run the GUI (browser-based):
#   docker run -d --name music-dl \
#     -p 8765:8765 \
#     -v ~/.config/music-dl:/root/.config/music-dl \
#     -v ~/Music:/root/download \
#     music-dl gui
#
# Run CLI commands:
#   docker run --rm -it \
#     -v ~/.config/music-dl:/root/.config/music-dl \
#     -v ~/Music:/root/download \
#     music-dl login
#
#   docker run --rm \
#     -v ~/.config/music-dl:/root/.config/music-dl \
#     -v ~/Music:/root/download \
#     music-dl dl <URL>

FROM python:3.12-slim-bookworm AS base

# Install FFmpeg (waveform generation + transcoding) and clean up
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user — limits blast radius if a dependency is compromised.
# UID/GID 1000 matches the default user on most Linux distros, so
# bind-mounted volumes from the host usually Just Work™.
RUN groupadd -g 1000 musicdl \
    && useradd -u 1000 -g musicdl -m -s /bin/sh musicdl

# Copy only the package source
COPY TIDALDL-PY /app/TIDALDL-PY
WORKDIR /app/TIDALDL-PY

# Install music-dl and its Python dependencies
RUN pip install --no-cache-dir .

# Create volume mount points owned by our non-root user
RUN mkdir -p /home/musicdl/.config/music-dl /home/musicdl/download \
    && chown -R musicdl:musicdl /home/musicdl

USER musicdl

VOLUME ["/home/musicdl/.config/music-dl", "/home/musicdl/download"]

# Bind to 0.0.0.0 so the host can reach the container
ENV MUSIC_DL_BIND_ALL=1
ENV MUSIC_DL_CONFIG_DIR=/home/musicdl/.config/music-dl

EXPOSE 8765

# Health check for GUI mode — container orchestrators can monitor readiness
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8765/ || exit 1

# Default: launch the GUI on all interfaces so it's reachable from the host
# Override with CLI commands: docker run ... music-dl dl <URL>
ENTRYPOINT ["music-dl"]
CMD ["gui", "--no-browser", "--port", "8765"]
