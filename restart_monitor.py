#!/usr/bin/env python3
"""
Reload File Monitor for Flask Restart Button

This script monitors the .reload file and gracefully restarts the Flask process.
Run this ALONGSIDE your Flask app (in a separate process/terminal).

Usage:
    python3 restart_monitor.py

It will:
1. Monitor .reload file for modifications
2. When touched, get the current Flask PID from listening port (default 5000)
3. Kill the Flask process gracefully
4. Wait 2 seconds
5. Flask should be restarted by whatever launcher you're using (startup.sh, systemd, IDE, etc.)
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
RELOAD_FILE = SCRIPT_DIR / '.reload'
PORT = 5000
LOG_FILE = SCRIPT_DIR / 'arrdash.log'

def get_flask_pid():
    """Get Flask process PID listening on the specified port."""
    try:
        # Try Windows first
        result = subprocess.run(
            f'netstat -ano | findstr ":{PORT}"',
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout:
            # Parse Windows netstat output
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 5 and 'LISTENING' in line:
                    try:
                        pid = int(parts[-1])
                        return pid
                    except (ValueError, IndexError):
                        continue
    except Exception:
        pass

    try:
        # Try Unix/Linux
        result = subprocess.run(
            f'lsof -i :{PORT} -sTCP:LISTEN -t',
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                return int(result.stdout.strip().split()[0])
            except (ValueError, IndexError):
                pass
    except Exception:
        pass

    return None

def kill_flask_process(pid):
    """Gracefully kill Flask process."""
    if not pid:
        logger.warning("No Flask PID found to kill")
        return False

    try:
        logger.info(f"Stopping Flask process (PID: {pid})...")

        # Try graceful kill first (SIGTERM)
        try:
            os.kill(pid, 15)  # SIGTERM
        except ProcessLookupError:
            logger.warning(f"PID {pid} not found (already stopped?)")
            return False

        # Wait up to 10 seconds for graceful shutdown
        for i in range(10):
            try:
                os.kill(pid, 0)  # Check if process still exists
            except ProcessLookupError:
                logger.info("Flask process stopped gracefully.")
                return True
            time.sleep(1)

        # Force kill if still running
        try:
            os.kill(pid, 9)  # SIGKILL
            logger.info("Flask process force-killed.")
            return True
        except ProcessLookupError:
            logger.info("Flask process already terminated.")
            return True

    except Exception as e:
        logger.error(f"Error killing process {pid}: {e}")
        return False

def main():
    """Monitor .reload file and trigger restarts."""
    logger.info("=" * 70)
    logger.info("Flask Restart Monitor Started")
    logger.info(f"Monitoring: {RELOAD_FILE}")
    logger.info(f"Port: {PORT}")
    logger.info("=" * 70)

    last_mtime = None
    consecutive_errors = 0
    max_errors = 5

    while True:
        try:
            # Check if .reload file exists and has been modified
            if RELOAD_FILE.exists():
                current_mtime = RELOAD_FILE.stat().st_mtime

                if last_mtime is None:
                    # First check, just record the time
                    last_mtime = current_mtime
                elif current_mtime != last_mtime:
                    # File was modified!
                    logger.info("🔄 Reload signal detected!")
                    logger.info(f"   .reload file modification detected")

                    # Get and kill Flask process
                    flask_pid = get_flask_pid()
                    if flask_pid:
                        logger.info(f"   Found Flask process on port {PORT} (PID: {flask_pid})")
                        kill_flask_process(flask_pid)
                        logger.info("   Waiting 2 seconds before allowing restart...")
                        time.sleep(2)
                        logger.info("   Ready for restart. (Restart should happen automatically)")
                    else:
                        logger.warning(f"   No Flask process found on port {PORT}")

                    # Reset the modified time for next check
                    last_mtime = current_mtime
                    consecutive_errors = 0

            time.sleep(1)
            consecutive_errors = 0

        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Error in monitor loop: {e} (error #{consecutive_errors})")

            if consecutive_errors >= max_errors:
                logger.critical(f"Too many errors ({max_errors}), exiting")
                sys.exit(1)

            time.sleep(2)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nMonitor stopped by user")
        sys.exit(0)
