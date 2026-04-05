# This Dockerfile is kept for backward compatibility.
# The canonical Dockerfile lives at docker/Dockerfile (build context = repo root).
#
# To build from the repo root:
#   docker build -f docker/Dockerfile -t music-dl .
#
# To build from this directory (legacy):
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 musicdl \
    && useradd -u 1000 -g musicdl -m -s /bin/sh musicdl

COPY . /app/TIDALDL-PY
WORKDIR /app/TIDALDL-PY

RUN pip install --no-cache-dir .

RUN mkdir -p /home/musicdl/.config/music-dl /home/musicdl/download \
    && chown -R musicdl:musicdl /home/musicdl

USER musicdl

ENV MUSIC_DL_BIND_ALL=1
ENV MUSIC_DL_CONFIG_DIR=/home/musicdl/.config/music-dl
VOLUME ["/home/musicdl/.config/music-dl", "/home/musicdl/download"]
EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8765/ || exit 1

ENTRYPOINT ["music-dl"]
CMD ["gui", "--no-browser", "--port", "8765"]
