# arrdash 🎬📺📚

A self-hosted Flask web app that acts as a unified front-end for your **Radarr**, **Sonarr**, and **Readarr** instances. Search, add, and manage movies, TV shows, and books from a single responsive interface — on any device, from anywhere.

![Main screen](/static/images/Screenshot1.png) ![Search results](/static/images/Screenshot2.png) ![Movie detail](/static/images/Screenshot3.png)

---

## What arrdash Does

Instead of logging into Radarr, Sonarr, and Readarr separately, arrdash gives you one place to:

- **Search** movies, TV shows, and books simultaneously
- **Add** them to your library with one tap
- **Browse and manage** everything you already have
- **Read** EPUB and PDF books directly in the browser
- **Monitor downloads** via qBittorrent
- **Access remotely** via Pinggy tunnel or DuckDNS

---

## Prerequisites

Before setting up arrdash, you need at least one of the following running and accessible:

| Service | Purpose | Default Port |
|---------|---------|-------------|
| [Radarr](https://radarr.video) | Movie management | 7878 |
| [Sonarr](https://sonarr.tv) | TV show management | 8989 |
| [Readarr](https://readarr.com) | Book management | 8787 |
| [Prowlarr](https://prowlarr.com) | Indexer search (optional) | 9696 |
| [qBittorrent](https://www.qbittorrent.org) | Download monitoring (optional) | 8080 |

You also need:

- **Python 3.9+**
- A **TMDB API key** (free at [themoviedb.org](https://www.themoviedb.org/settings/api)) — required for posters and trending

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/revvin76/arrdash.git
cd arrdash
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Create your configuration file

```bash
cp demo_env .env
```

Then edit `.env` with your details (see [Configuration](#configuration) below).

### 4. Start arrdash

```bash
python app.py
```

arrdash will start on port `5000` by default. Open `http://localhost:5000` in your browser.

---

## Configuration

All configuration is done in the `.env` file. You can also manage most settings through the in-app **Settings** panel (hamburger menu → Settings) without restarting.

### Required — Media Services

Configure whichever services you use. arrdash works fine with just one.

```env
# Radarr (movies)
RADARR_URL=http://localhost:7878
RADARR_API_KEY=your_radarr_api_key
RADARR_ROOT_FOLDER=E:\Movies
RADARR_QUALITY_PROFILE=4          # Profile ID from Radarr → Settings → Profiles

# Sonarr (TV shows)
SONARR_URL=http://localhost:8989
SONARR_API_KEY=your_sonarr_api_key
SONARR_ROOT_FOLDER=E:\TV
SONARR_QUALITY_PROFILE=4
SONARR_LANGUAGE_PROFILE=1

# Readarr (books — optional)
READARR_URL=http://localhost:8787
READARR_API_KEY=your_readarr_api_key
READARR_ROOT_FOLDER=E:\Books
READARR_QUALITY_PROFILE=1
READARR_METADATA_PROFILE=1
```

**Finding your API key:** In Radarr/Sonarr/Readarr go to Settings → General → Security → API Key.

**Finding profile IDs:** In Radarr/Sonarr go to Settings → Profiles. The ID is shown in the URL when you click a profile, or you can check via the API at `http://localhost:7878/api/v3/qualityprofile?apikey=YOUR_KEY`.

### Required — TMDB

```env
TMDB_KEY=your_tmdb_api_key
```

Used for posters, trailers, and the Trending page. Get a free key at [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api).

### Optional — Prowlarr

```env
PROWLARR_URL=http://localhost:9696
PROWLARR_API_KEY=your_prowlarr_api_key
```

Enables the Prowlarr Search page for direct indexer searches.

### Optional — qBittorrent

```env
QBIT_URL=http://localhost:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=your_password
```

Enables the Downloads page showing active torrents with pause/resume/delete controls.

### Optional — Apify (Goodreads book search)

For richer book search results with cover images, author bios, and ratings:

```env
APIFY_ENABLED=true
APIFY_TOKEN=your_apify_api_token
APIFY_ACTOR=petr_cermak~goodreads-books   # default actor, override if needed
```

Get a free Apify token at [apify.com](https://apify.com). When enabled, book searches use Goodreads via Apify instead of Readarr's built-in lookup. Results are cached locally so subsequent searches don't consume API quota.

### Optional — Authentication

```env
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD=your_secure_password
```

Adds HTTP basic authentication to the entire app. Recommended when exposing arrdash remotely.

### Optional — Remote Access

**DuckDNS** (dynamic DNS — keeps a domain pointed at your home IP):

```env
DUCKDNS_DOMAIN=yoursubdomain       # yoursubdomain.duckdns.org
DUCKDNS_TOKEN=your_duckdns_token
DUCKDNS_ENABLED=true
```

**Pinggy tunnel** (secure HTTPS tunnel — access arrdash from anywhere without port forwarding):

```env
TUNNEL_ENABLED=true
PINGGY_AUTH_TOKEN=your_pinggy_token
PINGGY_RESERVED_SUBDOMAIN=yoursubdomain   # optional — requires Pinggy Pro
```

Both are visible on the **Service Links** page once configured.

### Optional — Auto-updater

```env
GITHUB_REPO=revvin76/arrdash
CHECK_INTERVAL=3600         # seconds between update checks
ENABLE_AUTO_UPDATE=true
UPDATE_CHANNEL=prod         # prod or dev
```

arrdash checks GitHub for new releases and shows a notification when one is available. Updates can be applied from the About panel.

### Flask / App settings

```env
SERVER_PORT=5000
FLASK_SECRET_KEY=change_this_to_something_random
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR
FLASK_DEBUG=false
```

> **Important:** Change `FLASK_SECRET_KEY` to a random string before exposing arrdash to a network.

---

## Features

### Search

Type anything in the search box on the home screen. arrdash queries Radarr (movies), Sonarr (TV), and optionally Readarr/Apify (books) simultaneously and interleaves results. Each card shows:

- Poster, title, year, rating
- Library status badge — **In Library**, **Not Added**, **On Disk**, **Missing**, or **Partial**
- One-tap **Add** button if not already in your library

### Trending

The Trending page shows the current week's popular movies and TV shows from TMDB. Library status is loaded in a single batch request. Filter by media type and/or library status simultaneously.

### Manage Media

Browse everything currently in your Radarr and Sonarr libraries. Features:

- Filter by Movies / TV Shows
- Inline search
- **A–Z quick navigation** — tap the A–Z button to reveal a letter grid and jump straight to that section
- Progressive thumbnail loading (20 at a time)
- Click any item for full details, on-disk status, and delete controls

### Manage Books

Dedicated page for books downloaded to disk via Readarr. Features:

- Thumbnails and author names loaded from local cache (no API calls on repeat visits)
- **Bookmark badges** — shows 🔖 and page number on any book you've bookmarked in the reader
- **A–Z quick navigation**
- Read and Delete buttons per book

### Ebook Reader

Click **Read Now** on any book with a downloaded file to open the full-screen in-browser reader. Supports:

- **EPUB** — tap zones or arrow keys to turn pages, swipe on mobile, table of contents panel, percentage/page progress
- **PDF** — page navigation bar with direct page number input
- **Bookmarks** — tap 🔖 to bookmark your current page. The bookmark persists across sessions. The button turns gold on the bookmarked page; tap again to remove it. An amber highlight marks the bookmarked position in the text.
- Tap the centre of the page to toggle the toolbar/footer

### Downloads

Monitor active qBittorrent downloads without opening the qBittorrent web UI. Shows torrents grouped by state (Downloading, Seeding, Paused, etc.) with per-torrent controls: Pause, Resume, Force Start, Remove.

### Prowlarr Search

Search all your configured indexers directly from arrdash. Filter by category (Movies / TV / Books / Apps). Results open in your configured download client.

### Service Links

Dashboard showing quick-access links to all your configured services (Radarr, Sonarr, Readarr, Prowlarr, qBittorrent) with both local network and remote tunnel URLs where applicable.

---

## Caching

arrdash maintains a local `metadata/` directory for caching:

| Cache file | Contents | Expires |
|-----------|---------|--------|
| `lib_movies.json` | Radarr movie list + status | 5 minutes |
| `lib_series.json` | Sonarr series list + status | 5 minutes |
| `lib_books.json` | Readarr book list + status | 5 minutes |
| `lib_tmdb_movie_{id}.json` | TMDB movie details, poster, trailer | Never |
| `lib_tmdb_tv_{id}.json` | TMDB TV details, poster, trailer | Never |
| `book_{foreignBookId}.json` | Book metadata (author, cover, synopsis) | Never |

Static metadata (posters, titles, descriptions) is written once and never re-fetched. Only library status (downloaded, monitored, missing) refreshes regularly.

---

## Progressive Web App (PWA)

arrdash is installable as a PWA on any device:

- **iPhone/iPad:** Safari → Share → Add to Home Screen
- **Android:** Chrome → ⋮ menu → Install App
- **Desktop (Chrome/Edge):** Address bar install icon

Once installed it behaves like a native app — full screen, home screen icon, no browser chrome.

---

## Accessing from Another Device

**Same network:** Use your computer's local IP address, e.g. `http://192.168.1.10:5000`. Find your IP with `ipconfig` (Windows) or `ifconfig` (Mac/Linux).

**Outside your network:** Enable the Pinggy tunnel (`TUNNEL_ENABLED=true`) or set up DuckDNS with port forwarding. The Service Links page shows all available URLs including the active tunnel address.

---

## Troubleshooting

**arrdash starts but I can't find my Radarr quality profile ID**
Go to `http://your-radarr-host:7878/api/v3/qualityprofile?apikey=YOUR_KEY` — each profile object has an `id` field.

**Search returns no results**
Check that your Radarr/Sonarr URLs are reachable from the machine running arrdash, not just from your browser. Use the Settings panel → Test Connection buttons.

**Book covers not showing**
Covers for library books route through arrdash's image proxy (`/api/readarr/cover`). Make sure arrdash can reach your Readarr instance at `READARR_URL`. Covers from Apify/Goodreads search load directly from the web and don't need the proxy.

**EPUB reader shows blank page**
Ensure the book file path is accessible to Readarr and that Readarr's `bookFile` endpoint returns a valid path. Check `arrdash.log` for errors from the `/api/book/file/<id>` route.

**Bookmark badge not showing on Manage Books**
The badge is read from your browser's `localStorage`. It appears when you switch back to the Manage Books tab after reading. If it still doesn't show, try refreshing the page.

**Tunnel URL not working**
Pinggy free tunnels change address on each restart. A reserved subdomain requires Pinggy Pro. The current tunnel URL is always shown on the Service Links page.

---

## Logs

Application logs are written to `arrdash.log` in the project root and are also viewable in-app at `/logs`. Set `LOG_LEVEL=DEBUG` in `.env` for verbose output.

---

## Project Structure

```
arrdash/
├── app.py              # Application entry point, startup logic
├── routes.py           # All Flask route definitions
├── utils.py            # Shared utility methods (API calls, caching)
├── lazy_config.py      # Attribute-access config wrapper over .env
├── update_manager.py   # GitHub update checker and downloader
├── requirements.txt
├── demo_env            # Template — copy to .env and fill in values
├── metadata/           # Local disk cache (auto-created)
├── static/
│   ├── css/
│   ├── js/main.js      # All client-side logic
│   └── images/
└── templates/
    ├── partials/navbar.html   # Shared navigation bar
    ├── index.html             # Home / search
    ├── results.html           # Search results
    ├── trending.html          # Trending movies & TV
    ├── manage.html            # Manage movies & TV
    ├── manage-books.html      # Manage books
    ├── reader.html            # EPUB/PDF reader
    ├── downloads.html         # qBittorrent downloads
    ├── prowlarr.html          # Prowlarr indexer search
    └── links.html             # Service links dashboard
```

---

## License

MIT License © 2025 Revvin76
