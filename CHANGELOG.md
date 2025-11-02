# 📜 Addarr Changelog

All notable changes to this project will be documented in this file.

---
## [1.0.9] - 2025-10-30
### Updated
- Manage media page now just has a small home icon to navigate back to the main page
- Updated PWA Splash screen
- Restyled config panel to match the info panel

### Fixed
- Info page recent changes to show whole recently changed section
- After clicking "Show downloaded updates", modal now disappears
- Radio buttons on config page were not displaying correctly

### Known issues
- Configuration does not save correctly! Manually edit the .env file for now.

## [1.0.8a] - 2025-10-30
### Fixed
- Issue with update interval

## [1.0.8] - 2025-11-01
### Fixed
- Loading spinners for page transitions on PWA were not disappearing
- Fixed auto-update code to apply updates consistently

### Added
- Automatic env file upgrade. Your env file is now rebuilt using the latest template to ensure you always have the available options

## [1.0.7a] - 2025-10-30
### Updated
- README.md updated

## [1.0.7] - 2025-10-30
### Removed
- Dumped localhost.run reverse tunnelling
- Removed Debug API sandbox
- Removed log viewer (to reinstate when working properly)

### Added
- Added Pinggy Pro support - requires manual editing of the .env for now. Will link controls to the settings panel in future.
- Added new in-app information screen to display version, recent changes, and the various addresses
- Added QR code of the public URL to quickly get access on your mobile
- New screenshot added to README.md

### Updated
- Demo_env has new fields:  
    TUNNEL_ENABLED=false
    PINGGY_AUTH_TOKEN=
    PINGGY_RESERVED_SUBDOMAIN=

### Known issues
- I've broken the settings page so it doesnt work properly. This will be fixed in future, but for now stick to editing the .env files to change settings.

## [1.0.6] - 2025-10-28
### Changed
- Refactor tunnel management and logging configuration for improved clarity and performance

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
