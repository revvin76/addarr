"""
Restart Monitor Thread - Background daemon for watching .reload file

This module implements a daemon thread that monitors a .reload file and gracefully
restarts the Flask application when the file is touched. Designed for development
and production use on Windows and Unix systems.

Usage:
    from restart_monitor_thread import RestartMonitor

    # Start the monitor in startup_sequence()
    monitor = RestartMonitor(
        reload_file_path='.reload',
        check_interval=1.0,
        on_restart_callback=None
    )
    monitor.start()

    # Stop the monitor in shutdown_sequence()
    monitor.stop()
"""

import os
import sys
import time
import threading
import logging
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class RestartMonitor:
    """
    Daemon thread that monitors a .reload file for changes and restarts Flask.

    Features:
    - Monitors .reload file modification time (1-second polling)
    - Graceful shutdown: calls optional callback before restart
    - Windows-compatible: no bash/shell dependencies
    - Thread-safe: uses daemon thread that dies with Flask process
    - Error handling: logs issues without crashing
    - No port hanging: uses os._exit() instead of os.exec()
    """

    def __init__(
        self,
        reload_file_path: str = '.reload',
        check_interval: float = 1.0,
        on_restart_callback: Optional[Callable] = None
    ):
        """
        Initialize the RestartMonitor.

        Args:
            reload_file_path: Path to the file to monitor (default: '.reload')
            check_interval: Seconds between file checks (default: 1.0)
            on_restart_callback: Optional function to call before restart
        """
        self.reload_file_path = Path(reload_file_path)
        self.check_interval = check_interval
        self.on_restart_callback = on_restart_callback

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_mtime: Optional[float] = None

        logger.info(
            f"RestartMonitor initialized (file={self.reload_file_path}, "
            f"interval={self.check_interval}s)"
        )

    def start(self) -> None:
        """Start the monitor thread as a daemon."""
        if self._running:
            logger.warning("RestartMonitor is already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name='RestartMonitor'
        )
        self._thread.start()
        logger.info("RestartMonitor thread started (daemon=True)")

    def stop(self) -> None:
        """Stop the monitor thread gracefully."""
        if not self._running:
            logger.debug("RestartMonitor is not running")
            return

        self._running = False
        logger.info("RestartMonitor stopping...")

        # Wait for thread to exit (with timeout)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("RestartMonitor thread did not exit cleanly")

    def _monitor_loop(self) -> None:
        """
        Main monitor loop - checks .reload file every interval.

        When .reload is touched, calls optional callback then exits Flask
        via os._exit(0) to avoid hanging ports from os.exec().
        """
        try:
            # Initialize: get current mtime if file exists
            if self.reload_file_path.exists():
                self._last_mtime = self.reload_file_path.stat().st_mtime
                logger.debug(
                    f"Monitoring started (file exists, mtime={self._last_mtime})"
                )
            else:
                logger.debug(
                    f"Monitoring started (file will be created on demand)"
                )

            # Main loop
            while self._running:
                try:
                    time.sleep(self.check_interval)

                    if not self.reload_file_path.exists():
                        # File doesn't exist yet, keep waiting
                        continue

                    # File exists - check if it was touched
                    current_mtime = self.reload_file_path.stat().st_mtime

                    if self._last_mtime is None:
                        # First time we see the file
                        self._last_mtime = current_mtime
                        logger.debug(f"First detection of .reload file")
                        continue

                    if current_mtime > self._last_mtime:
                        # File was touched! Initiate restart
                        logger.info(
                            "🔄 Restart signal detected (.reload file touched)"
                        )
                        self._initiate_restart()
                        return  # Exit the loop after restart

                except OSError as e:
                    logger.warning(
                        f"Error checking .reload file: {e} "
                        "(file may have been deleted)"
                    )
                    self._last_mtime = None
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error in monitor loop: {e}")
                    continue

        except Exception as e:
            logger.error(f"Fatal error in RestartMonitor: {e}", exc_info=True)
        finally:
            logger.debug("RestartMonitor loop exiting")

    def _initiate_restart(self) -> None:
        """
        Gracefully initiate Flask restart.

        - Calls optional callback for cleanup
        - Uses os._exit(0) to terminate Flask process
        - Allows start.cmd to detect exit and restart
        """
        try:
            # Call optional callback (for cleanup if needed)
            if self.on_restart_callback:
                try:
                    logger.debug("Calling restart callback...")
                    self.on_restart_callback()
                except Exception as e:
                    logger.warning(f"Restart callback failed: {e}")

            # Brief pause to let callback finish
            time.sleep(0.5)

            # Exit Flask process via os._exit() (no cleanup, avoids port hanging)
            logger.info("Flask process exiting (os._exit)...")
            print("\n✅ Restart signal received - Flask exiting...")
            os._exit(0)

        except Exception as e:
            logger.error(f"Error during restart initiation: {e}")
            # Even if callback fails, still exit
            os._exit(0)


# ============ CONVENIENCE FUNCTIONS ============

_monitor_instance: Optional[RestartMonitor] = None


def create_restart_monitor(
    reload_file_path: str = '.reload',
    check_interval: float = 1.0,
    on_restart_callback: Optional[Callable] = None
) -> RestartMonitor:
    """
    Create and return a RestartMonitor instance.

    Args:
        reload_file_path: Path to the .reload file
        check_interval: Polling interval in seconds
        on_restart_callback: Optional cleanup callback

    Returns:
        RestartMonitor instance ready to start()
    """
    return RestartMonitor(
        reload_file_path=reload_file_path,
        check_interval=check_interval,
        on_restart_callback=on_restart_callback
    )


def touch_reload_file(reload_file_path: str = '.reload') -> None:
    """
    Touch the .reload file to trigger a restart (for external use).

    Args:
        reload_file_path: Path to the .reload file
    """
    reload_path = Path(reload_file_path)
    try:
        reload_path.touch()
        logger.info(f"Touched {reload_path} - restart will trigger in ~1 second")
    except Exception as e:
        logger.error(f"Failed to touch {reload_path}: {e}")


if __name__ == '__main__':
    # Quick test: run monitor for 10 seconds
    print("Testing RestartMonitor...")
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    monitor = RestartMonitor(check_interval=0.5)
    monitor.start()

    print(f"Monitor running. Touch .reload file to test restart.")
    print(f"Or wait 10s for auto-test exit...")

    time.sleep(10)
    monitor.stop()
    print("Monitor stopped.")
