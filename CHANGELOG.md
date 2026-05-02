# 📜 Addarr Changelog

All notable changes to this project will be documented in this file.

## [1.1.36] - 2026-05-02

### Updated
- Too many improvements to list!


## [1.1.34] - 2026-04-29

### Added
- **Episode count indicator on manage cards** — TV show cards now display a `[downloaded/total]` episode count in place of the season count when episode data is available (e.g. `[12/15]`). Requires the episode counts to be present in the slim show dict (see Fixed below).
- **Season episode counts on season headers** — each season header in the TV show detail modal now shows a `[downloaded/total]` badge on the far right, colour-coded green (complete), yellow (partial), or grey (none).
- **Seasons collapsed by default** — season cards in the TV show detail modal now use Bootstrap collapse and start closed. Click any season header to expand it. Season 0 is labelled "Specials".

### Fixed
- **Missing Files / Missing Episodes filter not working** — `_slim_movie()` in `routes.py` was not including `hasFile` or `monitored`, so all movies were treated as missing and all monitor states were wrong. `_slim_show()` only kept `seasonCount` in statistics, discarding `episodeCount` and `episodeFileCount`, so the TV missing-episodes filter never matched anything. Both slim functions now include the fields needed by the filter and card display.
- **Auto Search / Choose Source appearing on already-downloaded or unmonitored items** — both buttons now only render in the detail modal when the item is monitored AND has missing content (movie has no file; TV show has fewer downloaded episodes than total episodes).
- **Monitor toggle requiring modal close/reopen to show search buttons** — after a successful monitor API call, the toggle handler now immediately injects or removes the Auto Search and Choose Source buttons in the open modal without any page interaction. Toggling to Monitored on a missing item adds the buttons; toggling to Unmonitored removes them.

### Changed
- **Watermark icons removed from all result cards** — the film (🎬) and TV (📺) icons overlaid on poster thumbnails have been removed from `manage.html`, `trending.html`, and `results.html`. The poster image itself is sufficient to identify media type; the icons added visual noise without useful information.

## [1.1.33] - 2026-04-28

### Added
- **Kindle AZW3 library** — complete replacement of the epub.js Kindle reader with a native AZW3 download flow. At startup a daemon thread scans all books and calls Calibre's `ebook-convert` to produce a sibling `.azw3` file. Kindle's browser downloads the AZW3 (`application/vnd.amazon.ebook`) and auto-imports it — no in-browser rendering required.
- **`ensure_azw3()` + `_find_ebook_convert()`** in `utils.py` — `_find_ebook_convert()` checks `shutil.which` first then a list of common Calibre Windows install paths (`C:\Program Files\Calibre2\`, etc.) so the tool is found even when Calibre is not in PATH. `ensure_azw3()` converts epub / mobi / pdf to AZW3 and returns a `(path, status)` tuple (`exists` / `converted` / `failed` / `skipped`).
- **Background AZW3 scan** — `_background_azw3_scan()` daemon thread in `app.py` starts 8 s after startup, iterates every book in the root folder, and pre-converts files to AZW3 so the Kindle page is ready without waiting.
- **`/kindle` library redesign** — 3-column cover-only poster grid (20 vh header with search input + Filters button + ☀/☾ dark-mode toggle; black bottom bar with white top edge; prev/next paging). Filter overlay exposes Genre, Year, Author, Title, and Size chips. Dark mode stored in `localStorage`; written in ES5 for Kindle WebKit 531.2 compatibility.
- **`/kindle/book/<id>` detail page** (`kindle_book.html`) — cover, title, author, meta row (year, file size, pages), genre chips, synopsis. Shows **Send to Kindle** (`href` to AZW3 download) when an AZW3 exists, or a **Prepare for Kindle** button that triggers on-demand conversion via `POST /api/book/convert/<id>` XHR and swaps to the Send button on success.
- **`GET /api/book/azw3/<id>`** — streams the `.azw3` file as `application/vnd.amazon.ebook` for Kindle auto-import.
- **`POST /api/book/convert/<id>`** — on-demand synchronous AZW3 conversion; returns `{"success": true/false}`.
- **"Refresh online" multi-result picker** — `POST /api/books/search-online/<id>` queries both Google Books (up to 8 results) and Readarr (up to 8 results) and returns the full list without saving anything. In the Edit Metadata modal, clicking **Refresh online** now shows a scrollable grid of cover cards (thumbnail, title, author, year, source badge). Clicking a card fills all form fields — title, author, year, pages, ISBN, genre, overview, cover URL — without saving; the user reviews and clicks Save to apply.
- **"Clear Thumbnail Cache" button** — in the Settings → Readarr section of the navbar; calls `POST /api/books/covers/clear-cache` which deletes all `.jpg` files from the thumbnail cache directory and returns a count.

### Fixed
- **Calibre not in Windows PATH** — Kindle detail page showed "Preparing for Kindle… check back shortly" after Calibre was installed because `ebook-convert.exe` isn't added to PATH by the Calibre installer. Resolved via `_find_ebook_convert()` hardcoded path fallback.
- **AZW3 files appearing as separate books in manage-books** — background conversion created `.azw3` siblings that `scan_books_folder` picked up as independent book entries with no useful metadata. Fixed by filtering manage-books to only list `.epub` / `.pdf` files; AZW3 companions are shown as a status line ("AZW3 ready" / "AZW3 not yet generated") on the card.
- **Desktop reader 415 / error page for AZW3 entries** — clicking "Read" on an AZW3 book that had been inserted into the DB before the filter fix routed to `/read/local/<id>` which returned a 415-equivalent error. Fixed by redirecting non-epub/pdf extensions in `read_local_book()` to `kindle_book_detail` instead.
- **manage-books Edit Metadata broken — `Unexpected end of input`** — two separate JS syntax errors: (1) `book.overview` inserted raw into a template literal; backtick characters in Google Books synopses closed the literal prematurely. Fixed by adding `escHtml()` which escapes `&`, `<`, `>`, `"`, and `` ` `` (→ `&#96;`) and applying it to all user-sourced strings in template literals. (2) `JSON.stringify(book.file_path)` in an `onclick="..."` attribute produced embedded double-quotes that broke the HTML attribute boundary. Fixed by moving data into `data-edit-fp` / `data-edit-id` attributes and using a named `openEditFromModal(btn)` function.
- **Stale thumbnail showing wrong cover after cover_url update** — manage-books cards used `w=174&h=261` while the detail modal used `w=180&h=270`, resulting in different cache files; changing the URL via "Refresh online" busted the new-size cache but left the old-size file serving the stale image. Fixed by standardising cards on `w=180&h=270` and calling `_bust_thumb_cache()` whenever `cover_url` is saved to the DB.
- **Random / wrong cover shown when no cover_url exists** — `book_cover()` had a Priority 3 Google Books fallback that fetched the top result for `intitle:<title>+inauthor:<author>` and persisted it, causing incorrect covers to appear on books with no cover URL in the DB. Removed; the route now returns 404 immediately when no cover is found, and the `onerror` handler on every `<img>` shows `/static/images/apple-touch-icon.png` instead.

### Changed
- **`refreshMetadata()` no longer auto-applies** — previously called `POST /api/books/refresh/<id>` which immediately picked the best match, saved it to the DB, and updated the card. Now calls the new `search-online` route and renders a picker grid; nothing is saved until the user explicitly clicks Save.
- **Thumbnail cache size standardised** — all book cover `<img>` requests in manage-books now use `w=180&h=270` (was `w=174&h=261` on cards, `w=180&h=270` in modal) to share a single cache file per book.

## [1.1.32] - 2026-04-28

### Added
- **Google Books API integration** — replaces Apify/Goodreads as the book metadata source. `search_google_books()` in `utils.py` calls the Google Books Volumes API, normalises results to the same internal book format (title, author, cover, overview, year, pages, ISBN, genres), and falls back gracefully. No API key required for up to ~1,000 requests/day; set `GOOGLE_BOOKS_API_KEY` for a higher quota. Configured via `GOOGLE_BOOKS_ENABLED` and `GOOGLE_BOOKS_API_KEY` env vars. Config section in the settings modal updated accordingly.
- **Fuzzy match enrichment** — `_best_enrichment_match()` helper in `routes.py` uses `difflib.SequenceMatcher` to score each search result (author weight 0.6, title weight 0.4). A minimum combined score of 0.35 is required before a result is accepted. Both `books_enrich()` and `refresh_book_metadata()` use this instead of blindly taking `results[0]`, preventing wrong books from being matched when the file title differs from the canonical title.
- **Goodreads URL hint in Edit Metadata modal** — a "Goodreads URL" field lets the user paste a Goodreads book URL (e.g. `https://www.goodreads.com/book/show/12345-slug-title`) before clicking **Refresh online**. The slug is extracted as a search query and the numeric ID is used for an exact-match pass before falling back to fuzzy matching — resolves cases where the file title and the real book title differ completely (e.g. "Breeding the Babysitter" → "Breeding the Nanny").
- **Cover management endpoints** — three new API routes:
  - `DELETE /api/books/cover/<id>` — clears `cover_url` in DB via direct SQL (bypasses `save_book`'s None-skip behaviour), deletes any uploaded local file, and busts the thumbnail cache.
  - `POST /api/books/cover/upload/<id>` — accepts a multipart image upload, resizes to ≤ 400×600 px with Pillow (JPEG, quality 85), saves to `metadata/covers/<id>.jpg`, and stores the absolute path as `cover_url`.
  - `POST /api/books/refresh/<id>` — re-fetches metadata from Google Books (then Readarr) using the book's existing title + author (or URL hint), updates all fields including genre, and busts the thumbnail cache.
- **Edit Metadata modal — cover management UI** — Delete cover and Refresh online buttons added to the import modal; Upload image file input added alongside the Cover URL text field; cover preview refreshes after each action.
- **Stale thumbnail clearing on no-match** — when `books_enrich()` returns `needs_manual`, the server now busts the thumbnail cache for that book and returns `book_id` in the response. The frontend clears the card's `<img>` to the placeholder icon so a previously wrong cover doesn't persist.

### Fixed
- **Blank epub pages on open** — epub.js renders into a hidden (`display:none`) container, producing a 0×0 iframe that stays blank until navigation forces a reflow. Fixed in both `reader.html` and `reader_kindle.html` by making `#epubViewer` always visible and using a full-screen solid overlay for the loading state instead.
- **Save Metadata not updating the card** — two root causes: (a) CSS attribute selectors with Windows backslash paths failed silently, leaving `_importCard` as `null` so `patchBookCard` was never called. Fixed by adding a `[data-db-id]` integer fallback selector. (b) `patchBookCard` set `img.src` to the raw `cover_url` (a Windows file path, unusable by the browser). Fixed by always using the `/api/book/cover/<id>?t=<timestamp>` endpoint with a cache-bust timestamp.
- **Delete cover showing wrong cover** — `save_book({'cover_url': None})` silently skips `None` values, so the DB column was never NULLed. The thumbnail cache was busted but the old URL remained, causing the cover to reappear on next load. Fixed by using a direct `UPDATE books SET cover_url = NULL` query in `delete_book_cover()`.
- **Genre not showing on previously-enriched cards** — `enrichPendingBooks()` only targeted books with source `file`, `filename`, or `unknown`. Books already enriched via Goodreads/Readarr before the genre field was added had `source='goodreads'` but `genre=NULL`. Fixed by also re-enriching `source=google_books` / `readarr` cards where the `data-genre` attribute is empty.
- **Edit Metadata modal not pre-populating** — the modal showed blank fields on open. Fixed by fetching `/api/books/local/<db_id>` first and populating all fields from the DB record before falling back to file-embedded metadata.
- **Windows file paths losing backslashes in JS** — `data-file-path` values embedded into JS string literals via template literals (e.g. `'${path}'`) caused `\B` and `\A` to be interpreted as JS escape sequences, stripping the backslashes and producing malformed paths like `D:BooksBENEATH…`. Fixed in both detail-modal call sites by switching to `JSON.stringify(path)`, which produces properly escaped string literals.
- **Google Books API key — trailing whitespace/comment** — a comment on the `GOOGLE_BOOKS_API_KEY=` line in `.env` was being read as part of the key value, sending a garbage string to Google and receiving 400. Fixed by blanking the line and adding `.strip()` in both `lazy_config.py` and `utils.py`.
- **Apify actor 404** — the previously configured actor ID `mGuu1Iz5uU02gyvyF` was deleted from Apify. Resolved by replacing Apify/Goodreads with Google Books API entirely.

### Changed
- **Apify → Google Books** — `APIFY_ENABLED`, `APIFY_TOKEN`, and `APIFY_ACTOR` env vars retired; replaced by `GOOGLE_BOOKS_ENABLED` and `GOOGLE_BOOKS_API_KEY`. The `apify` config section in `lazy_config.py` is replaced by `google_books`. All references to `search_goodreads_apify()` replaced with `search_google_books()` throughout `routes.py` and `utils.py`.
- **Book detail modal redesigned** — flex layout with cover on the left and metadata panel on the right; genre shown once as tag badges; synopsis capped at 5 lines with a Show More expander; reading status buttons in their own full-width row (colour-coded: secondary / info / success / danger); file path as a subtle single line; Edit Metadata as a full-width button.
- **`save_book()` cover bust always fires** — `books_save_metadata()` now always busts the thumbnail cache on save regardless of whether `cover_url` was included, ensuring stale cached thumbnails are never served after any metadata change.

## [1.1.31] - 2026-04-28

### Added
- **Genre metadata** — `dc:subject` extracted from EPUB files during scanning; stored in `books.genre` column (SQLite). Displayed on manage-books cards and in the detail modal. Also included in manual-import dialog. Backfilled automatically on next page load for existing records missing the field.
- **Book reading status** — new `reading_status` column (`not_started` / `reading` / `complete` / `dnf`) and `is_wishlist` flag in the books DB. Status badge shown on each manage-books card and kindle library row. `PATCH /api/books/update` endpoint updates either field.
- **Manage-books detail modal** — clicking a card now opens a rich local-DB modal (cover, title, author, year, pages, genre, synopsis, file info) with inline status buttons and a ♥ wishlist toggle. No Readarr API required.
- **Manage-books filter** — status filter dropdown alongside search; filters by Not Started / Reading / Complete / DNF / Wishlist. Search now matches title **and** author **and** genre (previously title-only).
- **Kindle library status filter** — filter strip below search: All / Not Started / Reading / Complete / DNF / Wishlist. Genre shown under meta line. Status and heart badges shown per row.
- **Reader settings panel** — ⚙ button in epub reader toolbar opens a full-screen settings panel: font-size slider (70–200%, A−/A+ step buttons), five font-family choices (Georgia, Arial, Times, Palatino, Verdana), Light/Dark theme toggle. Settings can be saved for the current book only or set as the global default. Applied immediately on open; persisted in `localStorage`.
- **DB migration** — `init_db()` now issues `ALTER TABLE … ADD COLUMN` for `genre`, `reading_status`, and `is_wishlist` so existing databases upgrade automatically on first start.
- **`/api/books/local/<db_id>`** — new endpoint returning a single book record from the local DB; used by the manage-books detail modal.
- **`/api/books/update`** — new `POST` endpoint that patches `reading_status` and/or `is_wishlist` for a book identified by `db_id`.

### Fixed
- **Manage-books keyword filter broken** — filter only matched `data-title`; author searches returned no results. Fixed by adding `data-author` and `data-genre` attributes to every book card and updating the filter to OR-match all three fields.
- **Manage-books cover thumbnails** — book covers now served through the local `/api/book/cover/<id>` proxy (same path as the Kindle page) instead of raw external URLs, so they load correctly through the Pinggy tunnel.

### Changed
- **Trending / search — "Add to Sonarr/Radarr" → "View in Library"** — when an item's detail modal is opened and the item is already in the library, the action button is replaced with a "View in Library" link that navigates to `/manage?open=<id>&type=<type>`.
- **`/manage` deep-link** — accepts `?open=<internal_id>&type=<movie|tv>` query params; scrolls to the matching card and opens its detail modal automatically (used by the "View in Library" button).

## [1.1.30] - 2026-04-27
### Fixed
- **`ERR_CONTENT_LENGTH_MISMATCH` via Pinggy tunnel** — Pinggy's free/pro tunnel injects its own interstitial HTML into responses when the `X-Pinggy-No-Screen` header is absent from the *response*. The injected bytes cause the actual response body to exceed the `Content-Length` Flask declared, so Chrome reports the mismatch and the page is treated as truncated. The truncated page means `startProgressiveLoading()` never executes, which is why thumbnails also failed to load through the tunnel. Fixed by adding an `@app.after_request` handler in `app.py` that stamps `X-Pinggy-No-Screen: bypass` on every Flask response. The header is harmless on direct/LAN requests.

---
## [1.1.29] - 2026-04-27

### Added
- sw.js: bump cache to v3, purge old caches on activate, skip /api/* and cross-origin,
  network-first HTML, stale-while-revalidate static assets. Fixes ERR_CONTENT_LENGTH_MISMATCH
  from a stale/truncated main.js poisoning addarr-cache-v1, which silently killed page JS.
- manage-books: switch from horizontal book-card to the shared .search-result-card poster
  layout used by manage / trending / results; align sticky controls header with manage.html.
  All .book-item JS hooks (search, A-Z, enrichment, import, bookmarks) preserved.
- styles.css: add .book-item .watermark-icon color to match movie/tv pattern.

---
## [1.1.28] - 2026-04-27

### Added
- **Sticky controls header** on all grid pages (Manage, Trending, Results, Manage Books) — filter dropdowns, search input, A-Z navigation, and the back-to-top button now live in a dark sticky bar that stays visible as you scroll through the media grid. The floating back-to-top circle button is removed; replaced by a compact chevron in the sticky bar that fades in after 200 px of scroll.
- **`config.radarr.enabled` / `config.sonarr.enabled`** — added explicit `enabled` boolean to both config sections in `lazy_config.py`, derived from whether the respective URL env var is set (consistent with how `readarr`, `prowlarr`, and `qbit` already work).

### Fixed
- **Navbar "Manage Movies/TV" link never appearing** — `config.radarr.enabled` and `config.sonarr.enabled` didn't exist, so all three navbar conditions silently fell through. Fixed by adding the `enabled` field to both config sections and rewriting the navbar block as a single clean `if/elif/else` that can never fall through silently.
- **Epub reader `GET /api/book/file/local/META-INF/container.xml` 404** — epub.js receives a URL with no `.epub` extension and treated it as a directory, appending `META-INF/container.xml` to the base path. Fixed by passing `{ openAs: 'epub' }` as the second argument to `ePub()` in `reader_kindle.html`.
- **kindle.html missing Year and Pages** — the `/kindle` route's `save_book` call omitted `year` and `pages` from `extract_file_metadata`. Both fields are now passed, so new books scanned on the Kindle page display their metadata immediately.
- **manage-books cards missing Year/Pages for previously-scanned books** — books first seen via the `/kindle` route were saved to the DB without year/pages. The `/manage-books` route now backfills those fields on first load: for any DB record missing both `year` and `pages`, it re-runs `extract_file_metadata` and updates the record in-place.

### Changed
- **Manage page — library status removed from grid cards** — status badges (`On Disk`, `Missing`, `Not Added`) and the background `initializeManageGrid()` fetch loop are removed from the Manage page. Cards now show only thumbnail, title, year, and runtime. Full Sonarr/Radarr details (including status) are still fetched and displayed when a card is clicked to open the detail modal.

---
## [1.1.27] - 2026-04-26

### Added
- Kindle optimised reading screen. When you browse on a Kindle device it kicks in automatically.

---
## [1.1.26] - 2026-04-26

### Added
- **Two-tier library cache** — `get_cached_library()` in `routes.py` now operates across three layers: in-memory (60 s), disk JSON (5 min), and live API fetch. The disk layer (`metadata/lib_movies.json`, `lib_series.json`, `lib_books.json`) survives server restarts, so the first page load after a restart no longer triggers a full Radarr/Sonarr API call.
- **`/api/library/batch-status` endpoint** — accepts `?movie_ids=1,2&tv_ids=3,4` (TMDB IDs) and returns library status for all requested items in a single round trip, including `hasFile`, `statistics`, `internalId`, and `remotePoster`. Replaces the previous N×2 pattern of individual `/check_library_status` + `/get_media_details` calls.
- **TMDB details disk cache** — `/get_tmdb_details` now writes responses to `metadata/lib_tmdb_{type}_{id}.json`. Subsequent calls for the same item are served from disk instantly with no TMDB API call. TMDB data (poster, title, genres, trailer) is treated as permanent and never expires.
- **`save_media_cache()` / `load_media_cache()`** — generic disk-cache helpers in `utils.py`, used by both the library status cache and the TMDB details cache.
- **`STATUS_CACHE_TTL` / `STATIC_CACHE_TTL`** constants in `utils.py` — make the cache lifetime policy explicit: static metadata never expires; status data refreshes every 5 minutes.
- **Trending page progress indicator** — a small spinner bar ("Checking library status for N titles…") appears at the top of the Trending page while the batch status request is in flight and disappears when complete.
- **Trending page dual filter** — the media-type filter and library-status filter now apply together with AND logic. Changing either filter no longer resets the other. The status filter re-evaluates correctly as library status loads asynchronously.
- **Background fetch priority management** — `showDetails()` and `showManageDetails()` now call `_pauseBackgroundFetches()` the moment a card is tapped. Any in-flight background request (batch library status, manage grid detail fetches, book enrichment batches) is aborted via `AbortController`, freeing the browser's connection pool for the detail request. Aborted tasks register a resume callback and restart automatically when the modal closes (`hidden.bs.modal`).
- **Bookmark badge in book details modal** — the book details card now shows a gold 🔖 badge (with page number) when a bookmark is stored for that book. The badge is a clickable button that removes the bookmark immediately from both the modal and the card list.

### Fixed
- **EPUB reader sandbox error** — epub.js sets `sandbox="allow-same-origin"` on its rendering iframe by default, blocking script execution inside it and breaking rendering. Fixed by passing `allowScriptedContent: true` to `book.renderTo()`, which prevents epub.js from adding the sandbox attribute.
- **Bookmark badge not appearing on manage-books page** — `applyBookmarkBadges()` ran only on `DOMContentLoaded`, which fires once on initial page load. If the user opened the reader in a new tab, set a bookmark, then returned to the manage-books tab, the badge never appeared. Fixed by also running `applyBookmarkBadges()` on `visibilitychange` (tab becomes active) and `pageshow` (bfcache restore).
- **Bookmark badge not clearing after removal** — `applyBookmarkBadges()` only added badges and never removed them. If a bookmark was deleted in the reader and the user returned to the manage-books page, the old badge persisted. Fixed by checking each card: if the localStorage key is absent the existing badge is removed; if present the badge is created or updated in-place.
- **Bookmark removal not reflected in open details modal** — `applyBookmarkBadges()` now also checks for `#bmRemoveBtn` (the bookmark badge in the details modal) and removes it if the corresponding localStorage key is gone, so both the card list and any open modal stay in sync.

### Changed
- **Trending page library status** — replaced the previous lazy per-card loop (one `fetch` per card, triggered on scroll) with a single `loadAllStatuses()` call on `DOMContentLoaded`. All 40 cards are now updated in one HTTP request.
- **Search results page library status** — `initializeMediaGrid()` in `main.js` now fires a single batch request to `/api/library/batch-status` instead of one `checkLibraryStatus` call per card. Cards are updated in parallel from the single response with no follow-up `/get_media_details` calls for in-library items.
- **`save_book_metadata()`** — now accepts an `overwrite=False` flag. Callers that know a richer cache entry already exists can skip the write, preserving previously enriched data.
- **Library status disk TTL** — reduced from 1 hour to 5 minutes (`STATUS_CACHE_TTL = 300`). Status fields (`hasFile`, `monitored`, `statistics`) can change when items are added or deleted; 5 minutes balances freshness against API load.
- **TMDB cache TTL** — changed from 1 hour to permanent (no expiry). Poster paths, titles, genres, and trailers never change for a given TMDB ID.

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
