# 📜 Addarr Changelog

All notable changes to this project will be documented in this file.

---
## [1.1.25] - 2026-04-24

### Added
- **Ebook reader** (`/read/<book_id>`) — full-screen in-browser reader for EPUB files (via epub.js) and PDFs (via pdf.js). Tap/swipe to turn pages, keyboard arrow navigation, percentage progress display for EPUBs, page number nav bar for PDFs. Toolbar can be hidden for distraction-free reading.
- **"Read Now" button** in the book details modal — appears when a book file is on disk, opens the reader in a new tab.
- **Torrent actions** (`/api/torrents/action`) — new endpoint for Force Start, Resume, Pause, and Remove (keep files) actions on individual torrents. Wired to action buttons on the redesigned downloads page.
- **`qbit_action()` utility method** in `utils.py` — handles `resume`, `pause`, `delete`, and `setForceStart` via qBittorrent WebUI API v2.
- **`get_readarr_book_file_path()` utility method** in `utils.py` — queries Readarr `/api/v1/bookFile` to resolve on-disk EPUB or PDF path for a given book ID.
- **Trending link** added to hamburger menu on all pages (index, results, manage, links, prowlarr, downloads).
- **Full metadata enrichment chain** — `_enrich_book_from_cache` now follows a three-step priority: (1) local disk cache (fast, no HTTP); (2) Goodreads via Apify search (if enabled and data still missing); (3) Readarr author API. Results from each step are persisted to disk so subsequent loads are always served from cache.
- **Epub bookmark highlight** — saving a bookmark now adds an amber annotation at the bookmarked CFI via `rendition.annotations.highlight()`. epub.js automatically shows the highlight only on the page that contains the bookmarked position and hides it on all other pages; no custom show/hide logic needed.
- **Bookmark toggle behaviour** — the 🔖 button is now context-aware. When you are on the bookmarked page, the button turns gold and clicking it **removes** the bookmark (and its highlight). On any other page, the button is grey and clicking it **sets** a bookmark at the current position (removing the old highlight first). The button state updates on every page turn via the `relocated` event.
- **Manage Books first-load cache** — on page load, JS now fires a single batch request to the new `/api/book/metadata-cache?ids=…` endpoint. The server reads local metadata cache files (disk only, no HTTP calls) and returns author name + poster URL for every book that has cached data. All cards are patched immediately, before any user interaction.
- **`/api/book/metadata-cache` endpoint** — new route that accepts a comma-separated list of `foreignBookId` values and returns `{id: {authorName, posterUrl, title, overview}}` for all that exist in the local disk cache. Returns in milliseconds regardless of library size.
- **Client-side book data `Map`** — manage-books.html now maintains a JS `Map<foreignBookId, bookData>` that is populated on load (from the batch cache fetch) and after each individual detail click. Subsequent clicks on the same book patch the card instantly from memory — no server round-trip.
- **Auto-save Readarr author data to cache** — `_enrich_book_from_cache()` now writes a minimal cache entry after fetching author data from Readarr's `/api/v1/author/{id}`. This means the *next* page load finds that author in the batch cache and doesn't need any API call.
- **Readarr image proxy** (`/api/readarr/cover?path=…`) — new Addarr route that proxies Readarr media cover images. Readarr stores cover images at relative paths like `/api/v1/mediacover/{id}/cover.jpg` on the Readarr host, which is unreachable from a remote browser. All book cover image URLs are now rewritten to go through this proxy at normalisation time (`_normalise_book_images`).
- **`_normalise_book_images(book)`** — shared helper that fixes `coverType` and sets `remoteUrl` to the Addarr proxy URL for any relative Readarr image path. Used by `get_readarr_books`, library lookup, and Readarr details fetch.
- **Readarr author API fallback in `_enrich_book_from_cache`** — if `authorName` is still missing after checking the Apify cache, the function now calls Readarr's `/api/v1/author/{authorId}` directly to fetch the author object. This fixes author names for library books that were never searched via Apify.
- **Local book metadata cache** — Apify search results are now persisted to `metadata/book_{goodreadsId}.json` immediately after retrieval. Subsequent detail lookups read from this cache instead of calling the Apify API again, preserving rate-limit allocation.
- **Cache-backed author/overview enrichment** — `get_readarr_details()` now calls `_enrich_book_from_cache()` after fetching Readarr data. If `authorName`, overview, or poster are missing from the Readarr response (common for library books), the fields are backfilled from the local cache. If Readarr lookup returns no results at all, the full cached record is served directly.
- **Cache fallback on Readarr error** — if Readarr is unreachable when a book detail request arrives, the server now falls back to the local cache and returns a valid `not_added` response rather than an error.
- **Apify Goodreads book search** — when `APIFY_ENABLED=true` and `APIFY_TOKEN` is set, all book searches use the Goodreads Apify actor (`petr_cermak~goodreads-books` by default) instead of Readarr's book lookup. Results are normalised to the same Addarr book format (title, overview, author, cover image, year, page count, foreignBookId). The actor ID is configurable via `APIFY_ACTOR`.
- **Apify settings section in Config modal** — new "Apify / Goodreads Settings" section with Enable checkbox, API Token field, and Actor ID override field. Collapsible (shows only when enabled).
- **`search_goodreads_apify()` in utils.py** — calls the Apify run-sync endpoint (`POST /v2/acts/{actor}/run-sync-get-dataset-items`), handles flexible field name variants from different Goodreads actors, and extracts the Goodreads numeric book ID from the result URL.
- **Manage Books page** (`/manage-books`) — dedicated page showing only books that have been downloaded to disk (bookFileCount > 0). Includes inline search, Read and Delete buttons per book. Accessible from the hamburger menu when Readarr is configured.
- **Prowlarr category filter** — Movies / TV / Books / Apps / All toggle buttons on the Prowlarr Search page. Selected category is forwarded to Prowlarr's API as Newznab category IDs (2000/5000/7000/4000).
- **Apify Goodreads config field** — `APIFY_TOKEN` added to Settings modal and `lazy_config.py` for upcoming Goodreads metadata integration.
- **Shared navbar partial** (`templates/partials/navbar.html`) — single include replacing the 7 individually-maintained navbar blocks across index, results, manage, trending, links, prowlarr, and downloads. Contains config modal HTML, info modal HTML, notification modal HTML, and all configuration JavaScript.
- **Settings and About** now appear in the hamburger menu on every page (previously only on the home page).

### Fixed
- **Metadata falling through for library books without Apify cache** — books added to Readarr directly (not via Goodreads search) had no local cache entry, so the previous enrichment code found nothing and fell through to "Unknown Author". The new Apify search step fills the gap: it searches by title and saves the enriched record under the correct `foreignBookId` for future cache hits.
- **Manage Books — author/thumbnail persisting across sessions** — library books whose author was resolved via the Readarr author API are now saved to `metadata/book_{id}.json` so the batch cache endpoint can serve them on subsequent visits without any API calls.
- **Manage Books thumbnails not loading** — root cause: Readarr's `/api/v1/book` image `url` field is a relative server path; the old code copied it to `remoteUrl` verbatim, causing the browser to request it from Addarr (404). Fixed by routing all relative image URLs through the new `/api/readarr/cover` proxy.
- **Book author "Unknown Author" in details modal** — for library books, the Apify cache is empty (books were added to Readarr directly, never searched). The author fallback now queries Readarr's author endpoint using the `authorId` present in the book object.
- **Epub reader CORS / caching** — `book_file` route now sends `Access-Control-Allow-Origin: *`, `Cache-Control: no-store`, and `conditional=False` so the ArrayBuffer fetch in epub.js always receives the full file.
- **Book author not populated in details modal** — Readarr's `/api/v1/book` endpoint doesn't embed `authorName` for library books; the author field was always showing "Unknown Author". Fixed by enriching from the Apify metadata cache via `_enrich_book_from_cache()`.
- **Epub reader stuck on "Loading book…"** — epub.js was resolving internal epub paths (e.g. `META-INF/container.xml`) against the server URL, producing requests like `/api/book/file/META-INF/container.xml` (404). Fixed by preloading the epub binary as an `ArrayBuffer` via `fetch()` before passing it to `ePub()`, so JSZip handles all path resolution in-memory with no additional HTTP requests.
- **Downloads page incremental refresh** — `renderAll()` now diffs incoming torrent data against the existing DOM (hash-keyed lookup per group). Existing cards are updated in-place; `expanded` class on cards and `collapsed` class on group headers are preserved across refreshes. Only new/removed torrents cause DOM insertions/removals.
- **Manage page book filter** — `updateMediaDisplay()` in `main.js` was missing the `book-item` case; selecting "Books Only" now correctly shows only book items.
- **Delete media route** — added `DELETE /api/<media_type>/<internal_id>` endpoint in routes.py that proxies deletes to Radarr, Sonarr, or Readarr with `deleteFiles=false`.
- **qbit_action "unknown error"** — `qbit_action()` in utils.py now returns `{'success': False, 'message': "…"}` on non-200 qBittorrent responses instead of `{'success': False}` (no message), preventing the "unknown error" alert in the downloads page.
- `prowlarr.html` was using a non-standard `qbit_enabled` template variable instead of `config.qbit.enabled`; standardised to match all other pages.
- `links.html` had an extra `<div class="d-flex gap-2">` wrapper around the dropdown that caused misalignment; removed by the navbar replacement.
- `results.html` had two orphaned `</div>` closing tags left after the old navbar block was removed; cleaned up.
- **Book details modal always showing "not available"** — `get_readarr_details` now guards against non-list responses from Readarr (e.g. auth errors) and treats them as empty lists. Book search results are also cached in `window.bookCache` (injected by Jinja into `results.html`) so `showDetails` can render from cache if the API call fails.
- **Manage page library status never updating** — added `initializeManageGrid()` in `main.js` that reads `.media-item` elements and calls `/get_media_details` directly, bypassing the broken `initializeMediaGrid()` call that was targeting `.search-result-card` selectors.
- **Manage page card click JS syntax error for books** — `{{ item_id }}` quoted to `'{{ item_id }}'` in onclick handler to handle non-numeric Goodreads IDs safely.
- **Manage page modal title always "Movie Details"** — `showManageDetails` now correctly sets "Book Details" for book type.
- **`manage.html` missing `data-media-type` attribute** on `.media-item` wrapper — added so `initializeManageGrid()` can identify the type of each card.

### Changed
- **Search route** — Apify takes priority over Readarr for book searches when `APIFY_ENABLED=true`. `readarr_enabled` template flag is set `True` when either Readarr or Apify is providing book results, so book tabs/sections still render correctly.
- **`.env`** — added `APIFY_ENABLED`, `APIFY_TOKEN`, and `APIFY_ACTOR` placeholder entries.
- **`lazy_config.py`** — added `apify` config section with `token`, `actor`, and `enabled` fields.
- **Manage Media page** — books removed from the combined movie+TV library view. Book management moved to the dedicated Manage Books page.
- **Downloads page state grouping** — replaced regex-based `stateInfo()` with an exhaustive lookup table covering all qBittorrent API states. `stalledDL`/`stalledUP` → Downloading/Seeding; `forcedDL`/`forcedUP` → Downloading/Seeding; `metaDL` → Downloading; `queuedDL`/`queuedUP` → Paused; `checkingResumeData` → Paused. All previously fall-through "Other" states now land in the correct group.
- **Downloads page expanded details** — stalled / forced / metadata / checking / allocating / queued states now show a colour-coded tag badge in the expanded panel explaining the condition.
- **Downloads page auto-refresh** — 10-second auto-refresh no longer shows the loading spinner; spinner only appears on first load and manual refresh button clicks.
- **Add to Readarr** — `add_to_readarr()` now returns `(success, message)` tuple with full error detail instead of a bare boolean. Falls back to patching the existing author if Readarr returns 400 (author already exists). Error message is surfaced to the browser via the `/add` JSON response.
- **Mobile search layout** — main page container now uses `100dvh` so the search buttons remain visible when the virtual keyboard appears on mobile. Hero text and trending button are hidden via `@media (max-height: 500px)` when keyboard is open.
- **Prowlarr search** — `search_prowlarr()` in utils.py now accepts an optional `categories` list; values are forwarded as repeated `categories=` params to the Prowlarr API.
- **Navbar partial** — "Manage Books" link added (visible when Readarr is configured, hidden on the Manage Books page itself).
- All 7 page templates updated to use `{% set current_page = 'xxx' %}` + `{% include 'partials/navbar.html' %}` in place of their own navbar HTML.
- `index.html` stripped of all duplicated modal HTML and config-related JavaScript (now centralised in the partial).
- **Downloads page completely redesigned** — compact collapsible cards (name + mini-progress bar + % + state badge on one line), grouped by state (Downloading / Seeding / Paused / Other) with collapsible section headers, Collapse All / Expand All buttons, and action buttons (Force Start, Pause/Resume, Remove) inside each expanded card.
- **Hamburger menu "Manage Library" icon** updated from `fa-film` to `fa-list` across all 7 pages.
- **Service Links page** — removed the local/Pinggy address toggle. Pinggy only tunnels Addarr's own port so individual service links are always local. If tunnel is enabled, a note explains the limitation and the Addarr tunnel status is still shown.
- **`make_urls()` in `routes.py`** — now uses the configured service URL directly (replacing `localhost` with the detected LAN IP) instead of reconstructing URLs from scratch.

---
## [1.1.24] - 2026-04-23

### Added
- **Prowlarr control panel** (`/prowlarr`) — search across all configured indexers with results showing title, indexer, size, seeders, leechers, and age. "Add" button opens a category picker (radarr, tv-sonarr, readarr, games, uncategorised) and sends the torrent directly to qBittorrent.
- **Downloads page** (`/downloads`) — live view of all qBittorrent torrents with category-coloured left-border cards (radarr=green, tv-sonarr=cyan, readarr=dark red, games=purple, uncategorised=grey). Shows name, progress bar, download/upload speed, seeds/peers, ratio, ETA, and state. Filter tabs for downloading/seeding/paused. Auto-refreshes every 10 seconds.
- **qBittorrent config section** in the Settings modal — URL, username, and password fields with a Test Connection button.
- **Readarr support** — full search, add, and library management for books via Readarr. Books appear in search results, manage page, and trending alongside movies and TV shows.
- **Links page** (`/links`) — service cards for Radarr, Sonarr, Readarr, and Prowlarr with a toggle to switch between local LAN and Pinggy tunnel addresses.
- **qBittorrent utilities** in `utils.py` — `_qbit_login()`, `qbit_test()`, `qbit_add_torrent()`, `qbit_get_torrents()`.
- **Prowlarr search utility** in `utils.py` — `search_prowlarr()` proxies queries to Prowlarr's `/api/v1/search`.
- **New env vars**: `QBIT_URL`, `QBIT_USERNAME`, `QBIT_PASSWORD` — added to `lazy_config.py`, `.env`, and `demo_env`.
- **Navbar icons** for Prowlarr search and Downloads visible on all pages when the respective services are configured.

### Changed
- Book highlight colour updated from amber (`#e8a838`) to dark red (`#c0392b`) across `styles.css`, `routes.py`, and `index.html`.
- Readarr service card in links page now uses the dark red accent colour to match.
- Replaced the navbar icon row with a single hamburger menu (`☰`) across all pages (index, results, manage, links, trending, prowlarr, downloads). The dropdown shows labelled items with icons, is context-aware per page (Settings/About only on home, conditional Prowlarr/Downloads entries, auth divider when auth is enabled), and prevents nav icons from being pushed off screen on smaller viewports.

### Fixed
- `search_readarr` was calling `response.json()` twice — second call could crash on non-JSON error responses. Now stores result in a variable, checks HTTP status, and validates the response is a list before returning.
- Added detailed error logging to `search_readarr` — non-200 responses now log the status code and response body for easier debugging.
- Duplicate `'status'` key in `get_sonarr_details` return dict (second entry silently overwrote the first) — renamed to `series_status`.

---
## [1.1.23] - 2026-04-17
### Fixed
- Fixed SyntaxError in main.js (line 2736) caused by duplicate function call and closing brace
- Fixed main.js loading issue that prevented showDetails function from being available
- Fixed trending TV shows linking to wrong TV show (TMDB ID vs TVDB ID mismatch issue)
- Removed undefined `redirectToSearch` function call on trending TV show cards
- Fixed trending page TV show library status to accurately reflect library status in Sonarr
- Added episode count display for TV shows on trending page
- TV shows on trending page now use TMDB-only mode since we don't have TVDB IDs from TMDB
- Skip library status checking for TV shows on trending page (TMDB IDs don't map to Sonarr's TVDB requirement)

### Changed
- Updated trending TV show onclick to call `showDetails('tv', id, true)` for TMDB-only display mode
- Library status badge for trending TV shows now shows accurate status ("On Disk", "Missing", or "Not Added")
- Trending TV show cards now display episode count information
- Updated showDetails placeholder function signature in both templates to accept tmdbOnly parameter

---
## [1.1.22] - 2026-04-17
### Fixed
- Fixed "showDetails not defined" ReferenceError that occurred when clicking search result or trending cards
- Moved main.js script loading to `<head>` section (from body footer) to ensure function is available before onclick handlers
- Added YouTube iframe API early to ensure YouTube player support
- Added placeholder showDetails function with retry mechanism for resilience
- Applied fix to both results.html and trending.html for consistency

---
## [1.1.21] - 2026-04-17
### Fixed
- Restored full modal details (poster image, YouTube trailer, gallery) to search results and trending pages
- Removed minimal inline showDetails function that was overriding the comprehensive main.js version
- Modal now displays: poster from TMDB, YouTube trailers, image gallery, certification, ratings, genres, and overview
- Added library status checking integration to the full modal view

---
## [1.1.20] - 2026-04-17
### Fixed
- Fixed "showDetails not defined" error when clicking on search result cards
- Added missing showDetails function to results.html
- Function now properly opens modal and displays media details

---
## [1.1.19] - 2026-04-17
### Fixed
- Simplified badge layout in search results and trending pages
- Removed manage-controls divs that were cluttering the interface
- Badge now displays "On Disk" (green) or "Missing" (red) based on file status

### Changed
- Delete button now appears inline next to status badge instead of separate controls
- Delete button only displays for items that are in library (On Disk or Missing status)
- Simplified JavaScript logic by removing showManageControls and addManageEventListeners

### Improved
- Consistent badge and button styling across results.html and trending.html
- Cleaner interface with focused functionality (status + delete only)

---
## [1.1.18] - 2026-04-17
### Fixed
- Refactored manage page badge layout to fix status badge transitions and card sizing issues
- Fixed "In Library" badge to update existing "Not Added" badge instead of creating duplicate badges
- "On disk" and "Missing" badges now appear as separate badges next to "In Library" badge
- Fixed manage-controls div extending full card width - now compact delete button only
- Improved responsive design for manage page thumbnails (80px desktop, 60px mobile)

### Added
- Created dedicated manage-page.css stylesheet for manage page specific styling
- Added updateExtraBadges() function to properly display file status badges
- Improved badge layout with proper flex containers and spacing

---
## [1.1.17] - 2026-04-16
### Fixed
- Fixed status badges not updating with real-time information from Radarr/Sonarr
- Added comprehensive logging to checkLibraryStatus for debugging badge updates
- Fixed race condition where badge updates might occur before API responses
- Improved error handling and validation in library status checking
- Increased badge refresh delay after adding item from 500ms to 1000ms for API sync
- Added proper error messages in addItem notifications

---
## [1.1.16] - 2026-04-16
### Fixed
- Fixed search results page not updating status badges on page load - was reading data attributes from wrong element
- Fixed status badges not updating after adding item to library - now refreshes badge after successful add
- Improved notification system in addItem function - uses showNotification instead of alert

---
## [1.1.15] - 2026-04-16
### Fixed
- Added missing `/save_config` endpoint that was causing 404 errors when saving configuration

### Added
- Created VERSION file at project root for centralized version management
- Added version.py module for programmatic version access
- Added update_version.py script to automatically update version across all files
- Added version field to PWA manifest.json
- Updated demo_env header and APP_VERSION to 1.1.15

---
## [1.1.14] - 2026-04-16
### Fixed
- Fixed ReferenceError for showManageDetails function on manage page by removing defer attribute from main.js script load

---
## [1.1.13] - 2026-04-16
### Fixed
- Secret key was using the value of FLASK_DEBUG instead of the FLASK_SECRET_KEY
- Startup sequence was running before app.run()
- Imported updateManager to routes.py to fix issue with dismiss notifications
- Download update route that was referencing a function that no longer existed
- Last updated time derived from app.py instead of routes.py
- Tunnel URL race condition in print_welcome
- Changed a bare except to allow error logging instead of silent failures
- Removed redundant import of time module

### Updated
- Trending page now includes a status filter and 20 results per media instead of 10
- Added a 60s TTL in-process cache for check_library_status which was fetching all card data on each card
- Manage_media fetched movies and series sequentially instead of in parallel
- Search_media fetched movies and series sequentially instead of in parallel
- Removed unnecessary garbage collection

## [1.1.11] - 2025-11-25
### Updated
- CSS styles for Desktop browser - small tweaks top layouts
- Lazy loading for the manage media page thumbnails to improve performance

### Added
- Clear field button in the search results for easier new searches

## [1.1.10] - 2025-11-12
### Added
- Update channel selection 'prod' or 'dev'. Set in the .env file. Dev channel may introduce breaking changes and would requite fresh installation to resolve.

### Fixed
- Check for updates button was not working

### Updated
- Version display now includes channel tag dev or prod

## [1.1.9] - 2025-11-12
### Fixed
- Auto-update had been broken by v1.1.7. Fixed and tested working fine now

## [1.1.8] - 2025-11-11
### Fixed
- Dismiss page for new updates was not disappearing

## [1.1.7] - 2025-11-11
### Updated
- Massive overhaul on the memory optimisation. Should be more memory efficient
- Split utility functions, routes, updates and memory management into separate files for easier maintenance

### Known issues
- 'Last updated' is not updating correctly
- 'TestConnection' function not working
- 'View updates' doesn't load
- TV shows on Trending page can not be added to Library. Needs a conversion from TMDB to TVDB
- Loading spinners not loading correctly

## [1.1.6] - 2025-11-09
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
