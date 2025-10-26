# 📜 Addarr Changelog

All notable changes to this project will be documented in this file.

---

## [1.0.5] - 2025-10-26
### Added
- Automated GitHub update system with self-download, apply, and cleanup logic.
- Localhost.run tunnel integration with start/stop/restart endpoints.
- SSH key authentication and hostname persistence for tunnels.
- DuckDNS auto-updater to refresh IP dynamically.
- `/logs` endpoint for real-time log viewing.
- Debug endpoints for tunnel and update state inspection.
- Safe `.env` writer (`set_env`) for runtime environment updates.
- Background threads for update checking and tunnel health monitoring.

### Changed
- Improved logging system with request/response capture and rotating file handler.
- Enhanced environment variable handling and validation.
- Simplified update directory management with cleanup of old files.
- Improved error handling across all API endpoints.
- Enhanced Flask server health checks and tunnel lifecycle management.

### Fixed
- Fixed multiple tunnel processes on restart.
- Fixed `.env` duplication issue when setting variables repeatedly.
- Fixed stale update files remaining after downloads.
- Improved restart stability after applying updates.
- Fixed Radarr/Sonarr lookup edge cases for missing IDs.

### Documentation
- Updated README.md for v1.0.5 with new API references, setup steps, and troubleshooting.
- Added new demo_env template for easy configuration.
- Created structured changelog for long-term version tracking.

---
