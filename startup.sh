#!/bin/bash

# Addarr Flask Server Startup Script with Watchdog-based Reload

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELOAD_FILE="$SCRIPT_DIR/.reload"
PYTHON="${PYTHON:-python3}"
LOG_FILE="$SCRIPT_DIR/addarr.log"

kill_flask_process() {
    if [ -n "$FLASK_PID" ] && kill -0 "$FLASK_PID" 2>/dev/null; then
        echo "Stopping Flask process (PID: $FLASK_PID)..."
        kill -TERM "$FLASK_PID" || true

        for i in {1..10}; do
            if ! kill -0 "$FLASK_PID" 2>/dev/null; then
                echo "Flask process stopped gracefully."
                return 0
            fi
            sleep 1
        done

        kill -9 "$FLASK_PID" 2>/dev/null || true
        echo "Flask process force-killed."
    fi
}

cleanup() {
    echo "Shutting down..."
    kill_flask_process
    exit 0
}

trap cleanup SIGINT SIGTERM

while true; do
    echo "Starting Flask application..."
    rm -f "$RELOAD_FILE"

    cd "$SCRIPT_DIR"
    $PYTHON app.py >> "$LOG_FILE" 2>&1 &
    FLASK_PID=$!

    echo "Flask started with PID: $FLASK_PID"
    echo "Monitoring .reload file for changes..."

    LAST_MTIME=$(stat -c %Y "$RELOAD_FILE" 2>/dev/null || stat -f %m "$RELOAD_FILE" 2>/dev/null || echo 0)

    while true; do
        if ! kill -0 "$FLASK_PID" 2>/dev/null; then
            echo "Flask process exited unexpectedly."
            wait "$FLASK_PID" 2>/dev/null || true
            break
        fi

        if [ -f "$RELOAD_FILE" ]; then
            CURRENT_MTIME=$(stat -c %Y "$RELOAD_FILE" 2>/dev/null || stat -f %m "$RELOAD_FILE" 2>/dev/null || echo 0)
            if [ "$CURRENT_MTIME" != "$LAST_MTIME" ]; then
                echo "Reload signal detected. Restarting Flask..."
                kill_flask_process
                sleep 2
                break
            fi
            LAST_MTIME="$CURRENT_MTIME"
        fi

        sleep 1
    done
done
