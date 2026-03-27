FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY tidal_dl/ tidal_dl/

RUN pip install --no-cache-dir .

ENV MUSIC_DL_CONFIG_DIR=/config

EXPOSE 8765

CMD ["music-dl", "gui", "--no-open", "--port", "8765"]
