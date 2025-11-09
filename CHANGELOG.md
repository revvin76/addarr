# 📜 Addarr Changelog

All notable changes to this project will be documented in this file.

---
## [1.1.5] - 2025-11-09
### Fixed
- 'View updates' on the configuration panel now works
- Removed gap above TV results on the Trending page
- Fixed the information panels for TV items in the Trending page. nb, not yet able to check against Sonarr whether they are added. This will be a future update.
- Fixed the 'Managed media' page that was not loading

### Updated
- Updated the CSS styling for Desktop versions of Addarr. Still work to be done on this.

## [1.1.5] - 2025-11-09
### Fixed
- Fixed trending info panel not displaying and added library status.

## [1.1.4] - 2025-11-09
### Added
- Authentication Section: Added to config panel with username/password fields
- Basic Auth Protection: Uses Flask's basic auth with a decorator pattern
- Login/Logout page
- .env Backup System: Creates timestamped backups before any .env modifications
- Trending Feature: New route that fetches trending media from TMDB API
- Trending Template: New HTML template to display trending content
- Security: All main routes are protected when auth is enabled
- The backup system will create files like .env.backup.1635789200 before any .env modifications, which should prevent the blank .env file issue you experienced.

## [1.1.3] - 2025-11-07
### Added
- Automatic check for and install missing modules from requirements.txt

## [1.1.2] - 2025-11-06
### Fixed
- Improved version checking
- Fixed update checks to only run if enabled in .env

### Added
- Added Movie and TV count to Search results
- Updated logos
- Added "Back to top" button for search results and manage media page
- Added search counts and filters to top of search results

## [1.1.1] - 2025-11-04
### Fixed
- Routed calls to Sonarr / Radarr through Flask proxy to allow roaming outside the local network
- Fixed caching issue when saving configuration. Forcing a page refresh
- Grey overlay not closing properly after closing config panel

## [1.1.0] - 2025-11-03
### Fixed
- Configuration page now saves correctly

### Updated
- Tidied configuration panel, adding collapsible cards and descriptions
- Removed alert and replaced with modal box to confirm successful save
- Moved PWA Install button to bottom centre of main page
- Updated readme.md with new features and easier installation guide

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
