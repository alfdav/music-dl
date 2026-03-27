#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

echo "==> GUI and packaging smoke tests"
uv run --project TIDALDL-PY pytest \
  TIDALDL-PY/tests/test_gui_command.py \
  TIDALDL-PY/tests/test_gui_api.py \
  TIDALDL-PY/tests/test_setup.py \
  TIDALDL-PY/tests/test_token_refresh.py \
  TIDALDL-PY/tests/test_public_branding.py \
  TIDALDL-PY/tests/test_packaging.py

echo "==> Package build"
uv build --project TIDALDL-PY

echo "==> Docker build"
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed"
  exit 1
fi

docker info >/dev/null 2>&1 &
docker_info_pid=$!

for _ in 1 2 3 4 5; do
  if ! kill -0 "$docker_info_pid" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if kill -0 "$docker_info_pid" >/dev/null 2>&1; then
  kill "$docker_info_pid" >/dev/null 2>&1 || true
  wait "$docker_info_pid" 2>/dev/null || true
  echo "docker daemon check timed out"
  exit 1
fi

if ! wait "$docker_info_pid"; then
  echo "docker daemon is not available"
  exit 1
fi

docker build -f TIDALDL-PY/Dockerfile TIDALDL-PY
