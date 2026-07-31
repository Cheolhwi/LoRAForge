#!/usr/bin/env bash

set -u

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/.auto-cat-tmp"

stop_service() {
    local service_name="$1"
    local expected_command="$2"
    local pid_path="$RUNTIME_DIR/${service_name}.pid"

    if [[ ! -f "$pid_path" ]]; then
        echo "[INFO] No recorded ${service_name} process."
        return 0
    fi

    local service_pid
    service_pid="$(tr -d '[:space:]' <"$pid_path")"
    if [[ ! "$service_pid" =~ ^[0-9]+$ ]]; then
        echo "[WARN] Ignoring invalid PID file for ${service_name}."
        rm -f "$pid_path"
        return 0
    fi
    if ! kill -0 "$service_pid" >/dev/null 2>&1; then
        echo "[INFO] ${service_name} is already stopped."
        rm -f "$pid_path"
        return 0
    fi

    local process_command
    process_command="$(ps -p "$service_pid" -o command= 2>/dev/null || true)"
    if [[ "$process_command" != *"$expected_command"* ]]; then
        echo "[WARN] PID ${service_pid} no longer belongs to ${service_name}; leaving it untouched."
        rm -f "$pid_path"
        return 0
    fi

    echo "[INFO] Stopping ${service_name} (PID ${service_pid})..."
    kill "$service_pid"
    local waited=0
    while kill -0 "$service_pid" >/dev/null 2>&1 && (( waited < 10 )); do
        sleep 1
        waited=$((waited + 1))
    done
    if kill -0 "$service_pid" >/dev/null 2>&1; then
        echo "[WARN] ${service_name} did not exit after SIGTERM; PID file was kept."
        return 1
    fi

    rm -f "$pid_path"
    echo "[OK] ${service_name} stopped."
}

status=0
stop_service "frontend" "frontend/server.py" || status=1
stop_service "backend" "uvicorn app.main:app" || status=1
stop_service "locate-anything-mlx" "scripts/locate_anything_server.py" || status=1
exit "$status"
