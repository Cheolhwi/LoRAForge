#!/usr/bin/env bash

set -u

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.auto-cat-tmp"

cd "$PROJECT_ROOT" || exit 1

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    echo "[ERROR] mac-version requires an Apple Silicon Mac running native arm64 tools."
    exit 1
fi

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return 0
    fi
    for candidate in \
        "${XDG_BIN_HOME:-${HOME}/.local/bin}/uv" \
        "/opt/homebrew/bin/uv" \
        "/usr/local/bin/uv"
    do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

UV_EXE="$(find_uv || true)"
if [[ -z "$UV_EXE" ]]; then
    echo "[WARN] uv was not found. Trying the official installer..."
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        echo "[ERROR] uv installation failed. Install it from https://docs.astral.sh/uv/"
        exit 1
    fi
    UV_EXE="$(find_uv || true)"
    if [[ -z "$UV_EXE" ]]; then
        echo "[ERROR] uv was installed but is not available in this shell."
        echo "        Open a new Terminal window and run ./start_services.sh again."
        exit 1
    fi
fi

if [[ ! -f "$PROJECT_ROOT/pyproject.toml" ]]; then
    echo "[ERROR] pyproject.toml was not found."
    exit 1
fi
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "[ERROR] Required project configuration .env was not found."
    exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] Node.js and npm are required to build the React frontend."
    echo "        Install the current Node.js LTS release and run ./start_services.sh again."
    exit 1
fi

echo "[INFO] Installing and building the React frontend..."
if [[ ! -d "$PROJECT_ROOT/node_modules" ]] || [[ "$PROJECT_ROOT/package-lock.json" -nt "$PROJECT_ROOT/node_modules/.package-lock.json" ]]; then
    npm ci || exit 1
fi
if ! npm run build; then
    echo "[ERROR] React frontend build failed."
    exit 1
fi

mkdir -p "$RUNTIME_DIR"
export UV_CACHE_DIR="$PROJECT_ROOT/.uv-cache"
export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"
export ONNX_MODE="coreml"

echo "[INFO] Installing or updating native arm64 Python 3.11..."
if ! "$UV_EXE" python find 3.11 >/dev/null 2>&1; then
    "$UV_EXE" python install 3.11 || exit 1
fi

echo "[INFO] Syncing MPS, CoreML, and application dependencies..."
if ! "$UV_EXE" sync --extra models; then
    echo "[ERROR] Model dependency installation failed."
    exit 1
fi
echo "[INFO] Syncing the isolated Locate Anything MLX environment..."
if ! "$UV_EXE" sync --project "$PROJECT_ROOT/mlx_service"; then
    echo "[ERROR] Locate Anything MLX dependency installation failed."
    exit 1
fi

echo "[INFO] Verifying Apple acceleration backends..."
if ! "$UV_EXE" run python - <<'PY'
import platform

import onnxruntime
import torch
import torchvision

if platform.machine() != "arm64":
    raise SystemExit("Python is not running natively as arm64")
if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
    raise SystemExit("PyTorch MPS is unavailable")
if "CoreMLExecutionProvider" not in onnxruntime.get_available_providers():
    raise SystemExit("ONNX Runtime CoreMLExecutionProvider is unavailable")

print("[OK] PyTorch device: mps")
print(f"[OK] Torchvision: {torchvision.__version__}")
print("[OK] ONNX provider: CoreMLExecutionProvider")
PY
then
    echo "[ERROR] Apple acceleration verification failed."
    exit 1
fi
if ! "$UV_EXE" run --project "$PROJECT_ROOT/mlx_service" python - <<'PY'
import platform

import mlx.core as mx

if platform.machine() != "arm64":
    raise SystemExit("MLX Python is not running natively as arm64")
print(f"[OK] MLX device: {mx.default_device()}")
PY
then
    echo "[ERROR] MLX acceleration verification failed."
    exit 1
fi

echo "[INFO] Checking and downloading model assets if needed..."
if ! "$UV_EXE" run python scripts/bootstrap_models.py; then
    echo "[ERROR] Model setup is incomplete. Services were not started."
    exit 1
fi

health_contains() {
    local url="$1"
    local expected="$2"
    curl -fsS --max-time 3 "$url" 2>/dev/null | grep -Fq "$expected"
}

port_is_open() {
    nc -z 127.0.0.1 "$1" >/dev/null 2>&1
}

start_service() {
    local service_name="$1"
    local port="$2"
    local health_url="$3"
    local expected="$4"
    local timeout_seconds="$5"
    shift 5

    local log_path="$RUNTIME_DIR/${service_name}.log"
    local pid_path="$RUNTIME_DIR/${service_name}.pid"

    if health_contains "$health_url" "$expected"; then
        echo "[OK] Reusing healthy ${service_name} service on port ${port}."
        return 0
    fi
    if port_is_open "$port"; then
        echo "[ERROR] Port ${port} is occupied, but the ${service_name} health check failed."
        return 1
    fi

    echo "[INFO] Starting ${service_name} on port ${port}..."
    nohup "$@" >"$log_path" 2>&1 &
    local service_pid=$!
    printf '%s\n' "$service_pid" >"$pid_path"

    local waited=0
    while (( waited < timeout_seconds )); do
        if health_contains "$health_url" "$expected"; then
            echo "[OK] ${service_name} is ready."
            return 0
        fi
        if ! kill -0 "$service_pid" >/dev/null 2>&1; then
            echo "[ERROR] ${service_name} exited during startup. Recent log output:"
            tail -n 40 "$log_path"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done

    echo "[ERROR] ${service_name} did not become healthy within ${timeout_seconds} seconds."
    echo "        See $log_path"
    return 1
}

if ! start_service \
    "locate-anything-mlx" \
    9000 \
    "http://127.0.0.1:9000/health" \
    '"status":"ok"' \
    600 \
    "$UV_EXE" run --project "$PROJECT_ROOT/mlx_service" \
    python "$PROJECT_ROOT/scripts/locate_anything_server.py" --host 127.0.0.1 --port 9000
then
    exit 1
fi

if ! start_service \
    "backend" \
    8000 \
    "http://127.0.0.1:8000/api/health" \
    '"runtime":"local_models"' \
    60 \
    "$UV_EXE" run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
then
    exit 1
fi

if ! start_service \
    "frontend" \
    5173 \
    "http://127.0.0.1:5173/" \
    "LoRAForge" \
    30 \
    "$UV_EXE" run python frontend/server.py
then
    exit 1
fi

if [[ -z "${LORAFORGE_NO_BROWSER:-}" ]]; then
    open "http://127.0.0.1:5173"
fi

echo "[OK] Backend:  http://127.0.0.1:8000"
echo "[OK] Frontend: http://127.0.0.1:5173"
echo "[OK] Locate:   http://127.0.0.1:9000/v1/chat/completions (MLX)"
echo "[OK] DINOv3:   PyTorch MPS"
echo "[OK] PixAI:    ONNX CoreML"
echo "[INFO] Run ./stop_services.sh to stop services started by this project."
