# utils.py
import requests
import os
import json
import logging
from datetime import datetime
import time
import zipfile
import xml.etree.ElementTree as ET
import re
from packaging import version

# ── Book file extensions we recognise ────────────────────────────────────────
BOOK_EXTENSIONS = {'.epub', '.pdf', '.mobi', '.azw3', '.cbz', '.cbr'}


# ── Filesystem scanner ────────────────────────────────────────────────────────

def scan_books_folder(root_folder):
    """Recursively scan *root_folder* for book files.

    Returns a list of dicts:
        file_path, filename, extension, file_size, rel_path
    Sorted by rel_path for stable ordering.
    """
    if not root_folder or not os.path.isdir(root_folder):
        logging.warning("[scan] folder not found or not configured: %r", root_folder)
        return []

    books = []
    for dirpath, dirs, files in os.walk(root_folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for filename in sorted(files):
            ext = os.path.splitext(filename)[1].lower()
            if ext in BOOK_EXTENSIONS:
                full_path = os.path.join(dirpath, filename)
                try:
                    size = os.path.getsize(full_path)
                    rel  = os.path.relpath(full_path, root_folder)
                    books.append({
                        'file_path': full_path,
                        'filename':  filename,
                        'extension': ext,
                        'file_size': size,
                        'rel_path':  rel,
                    })
                except OSError:
                    pass
    return books


def _title_from_filename(filename):
    """Guess a human-readable title from a filename.

    Handles common patterns:
      "Author - Title (Year).epub"  → "Title"
      "Title.epub"                  → "Title"
    """
    stem = os.path.splitext(filename)[0]
    # Strip year in parens at end
    stem = re.sub(r'\s*\(\d{4}\)\s*$', '', stem)
    # If there's an " - " separator, take everything after the first one
    if ' - ' in stem:
        stem = stem.split(' - ', 1)[1].strip()
    return stem.strip() or filename


def extract_epub_metadata(file_path):
    """Extract Dublin Core metadata from an EPUB file.

    Uses only the stdlib `zipfile` and `xml.etree.ElementTree` — no deps.
    Returns a dict with whichever fields could be found.
    """
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            # container.xml → OPF path
            container_xml = z.read('META-INF/container.xml')
            container = ET.fromstring(container_xml)
            ns_c = {'n': 'urn:oasis:names:tc:opendocument:xmlns:container'}
            rootfile = container.find('.//n:rootfile', ns_c)
            if rootfile is None:
                return {}
            opf_path = rootfile.get('full-path', '')
            opf = ET.fromstring(z.read(opf_path))

            DC  = 'http://purl.org/dc/elements/1.1/'
            OPF = 'http://www.idpf.org/2007/opf'

            def dc(tag):
                el = opf.find(f'.//{{{DC}}}{tag}')
                return el.text.strip() if el is not None and el.text else None

            title   = dc('title')
            author  = dc('creator')
            desc    = dc('description')
            date_s  = dc('date')
            year    = None
            if date_s and len(date_s) >= 4:
                try:
                    year = int(date_s[:4])
                except ValueError:
                    pass

            # ISBN
            isbn = None
            for id_el in opf.findall(f'.//{{{DC}}}identifier'):
                scheme = (id_el.get(f'{{{OPF}}}scheme', '')
                          or id_el.get('scheme', '')).lower()
                if 'isbn' in scheme and id_el.text:
                    isbn = id_el.text.strip()
                    break

            # Cover image bytes (best-effort)
            cover_data = None
            manifest = opf.find(f'.//{{{OPF}}}manifest') or opf.find('.//manifest')
            if manifest is not None:
                for item in manifest:
                    item_id  = item.get('id', '').lower()
                    props    = item.get('properties', '')
                    media    = item.get('media-type', '')
                    is_cover = (item_id in ('cover', 'cover-image', 'cover_image')
                                or props == 'cover-image'
                                or ('image' in media and item_id == 'cover'))
                    if is_cover:
                        href = item.get('href', '')
                        opf_dir = os.path.dirname(opf_path)
                        cover_zip_path = '/'.join(
                            p for p in [opf_dir, href] if p
                        )
                        try:
                            cover_data = z.read(cover_zip_path)
                        except Exception:
                            pass
                        break

            # Genre from dc:subject (may have multiple elements)
            genre_parts = []
            for subj in opf.findall(f'.//{{{DC}}}subject'):
                if subj.text and subj.text.strip():
                    genre_parts.append(subj.text.strip())
            genre = ', '.join(genre_parts) if genre_parts else None

            return {
                'title':      title,
                'author':     author,
                'overview':   desc,
                'year':       year,
                'isbn':       isbn,
                'genre':      genre,
                'cover_data': cover_data,
                'source':     'file',
            }
    except Exception as e:
        logging.warning("[epub] metadata extraction error for %r: %s", file_path, e)
        return {}


def extract_pdf_metadata(file_path):
    """Extract basic metadata from a PDF using pypdf (optional dep).

    Falls back gracefully if pypdf is not installed.
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        meta   = reader.metadata or {}
        return {
            'title':  meta.get('/Title') or meta.get('title'),
            'author': meta.get('/Author') or meta.get('author'),
            'pages':  len(reader.pages),
            'source': 'file',
        }
    except ImportError:
        logging.debug("[pdf] pypdf not installed — PDF metadata unavailable")
        return {}
    except Exception as e:
        logging.warning("[pdf] metadata extraction error for %r: %s", file_path, e)
        return {}


def extract_file_metadata(file_path):
    """Dispatch to the right extractor based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.epub':
        return extract_epub_metadata(file_path)
    if ext == '.pdf':
        return extract_pdf_metadata(file_path)
    return {}

# ── Metadata cache ────────────────────────────────────────────────────────────
_APP_DIR      = os.path.dirname(os.path.abspath(__file__))
METADATA_DIR  = os.path.join(_APP_DIR, 'metadata')

def _ensure_metadata_dir():
    os.makedirs(METADATA_DIR, exist_ok=True)

def save_book_metadata(book_data, overwrite=True):
    """Persist a normalised book dict to the local metadata cache.
    Key is foreignBookId (string). Silently ignores errors.

    Static fields (title, author, cover, pages) are permanent — pass
    overwrite=False to skip writing if a cache file already exists.
    """
    try:
        fid = str(book_data.get('foreignBookId', '')).strip()
        if not fid:
            return
        _ensure_metadata_dir()
        path = os.path.join(METADATA_DIR, f'book_{fid}.json')
        if not overwrite and os.path.isfile(path):
            logging.debug(f"[cache] skipped overwrite for book {fid} (permanent cache)")
            return
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(book_data, f, ensure_ascii=False, indent=2)
        logging.debug(f"[cache] saved metadata for book {fid}")
    except Exception as e:
        logging.warning(f"[cache] save_book_metadata error: {e}")

def load_book_metadata(foreign_book_id):
    """Load a cached book dict for foreign_book_id, or return None."""
    try:
        path = os.path.join(METADATA_DIR, f'book_{foreign_book_id}.json')
        if not os.path.isfile(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logging.debug(f"[cache] loaded metadata for book {foreign_book_id}")
        return data
    except Exception as e:
        logging.warning(f"[cache] load_book_metadata error: {e}")
        return None

# ── Generic media library cache (movies / series / books) ─────────────────────
# Static metadata (posters, titles, authors, page counts, TMDB details) never
# expires — once written it is good forever.
# Status data (hasFile, monitored, statistics) refreshes on a short cycle.
STATIC_CACHE_TTL = None   # never expire — write once, read forever
STATUS_CACHE_TTL = 300    # 5 minutes for library/status data (*arr lists)
DISK_CACHE_TTL   = STATUS_CACHE_TTL  # backward-compat alias

def save_media_cache(cache_type, data):
    """Persist a library snapshot to disk.
    cache_type examples: 'movies', 'series', 'books', 'tmdb_movie_123'
    """
    try:
        _ensure_metadata_dir()
        path = os.path.join(METADATA_DIR, f'lib_{cache_type}.json')
        payload = {'timestamp': time.time(), 'data': data}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        logging.debug(f"[cache] saved media cache: {cache_type} ({len(data) if isinstance(data, list) else 1} items)")
    except Exception as e:
        logging.warning(f"[cache] save_media_cache({cache_type}) error: {e}")

def load_media_cache(cache_type):
    """Load a cached library snapshot.
    Returns (data, timestamp) — both None/0 if cache is absent or unreadable.
    """
    try:
        path = os.path.join(METADATA_DIR, f'lib_{cache_type}.json')
        if not os.path.isfile(path):
            return None, 0
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        logging.debug(f"[cache] loaded media cache: {cache_type}")
        return payload.get('data'), payload.get('timestamp', 0)
    except Exception as e:
        logging.warning(f"[cache] load_media_cache({cache_type}) error: {e}")
        return None, 0

def _find_ebook_convert():
    """Return the path to Calibre's ebook-convert executable.

    Tries PATH first, then common Windows install locations.
    Returns None if not found.
    """
    import shutil
    import subprocess

    # 1. Already in PATH?
    cmd = shutil.which('ebook-convert')
    if cmd:
        return cmd

    # 2. Common Windows Calibre install directories
    candidates = [
        r'C:\Program Files\Calibre2\ebook-convert.exe',
        r'C:\Program Files (x86)\Calibre2\ebook-convert.exe',
        r'C:\Program Files\Calibre\ebook-convert.exe',
        r'C:\Program Files (x86)\Calibre\ebook-convert.exe',
    ]
    for path in candidates:
        if os.path.isfile(path):
            logging.info('[AZW3] Found ebook-convert at %s', path)
            return path

    return None


def ensure_azw3(file_path):
    """Ensure an AZW3 version of *file_path* exists in the same directory.

    Uses Calibre's ``ebook-convert`` CLI.  Returns ``(azw3_path, status)``
    where *status* is one of:
      ``'exists'``    — AZW3 already present (or source is already AZW3)
      ``'converted'`` — just created successfully
      ``'failed'``    — ebook-convert ran but failed / timed out / not found
      ``'skipped'``   — source file missing or extension not supported
    """
    import subprocess

    if not file_path or not os.path.isfile(file_path):
        return None, 'skipped'

    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.azw3':
        return file_path, 'exists'

    if ext not in ('.epub', '.mobi', '.pdf'):
        return None, 'skipped'

    azw3_path = os.path.splitext(file_path)[0] + '.azw3'
    if os.path.isfile(azw3_path):
        return azw3_path, 'exists'

    cmd = _find_ebook_convert()
    if not cmd:
        logging.error('[AZW3] ebook-convert not found. '
                      'Install Calibre and ensure it is on PATH '
                      'or in C:\\Program Files\\Calibre2\\')
        return None, 'failed'

    logging.info('[AZW3] Converting %s → %s (using %s)', file_path, azw3_path, cmd)
    try:
        result = subprocess.run(
            [cmd, file_path, azw3_path],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0 and os.path.isfile(azw3_path):
            logging.info('[AZW3] Converted OK: %s (%d bytes)',
                         azw3_path, os.path.getsize(azw3_path))
            return azw3_path, 'converted'
        logging.warning('[AZW3] Conversion failed for %s (rc=%d): %s',
                        file_path, result.returncode, (result.stderr or '')[:500])
    except subprocess.TimeoutExpired:
        logging.error('[AZW3] Conversion timed out for %s', file_path)
    except Exception as e:
        logging.error('[AZW3] Conversion error for %s: %s', file_path, e)
    return None, 'failed'


class SharedUtils:
    def __init__(self, config_manager):
        self.config = config_manager
    
    def fetch_trending_optimized(self, media_type='all'):
        """Memory-optimized trending data fetch"""
        try:
            # Use attribute access instead of dict access
            api_key = self.config.tmdb.key
            if not api_key:
                return {'movies': [], 'tv_shows': []}
            
            trending_data = {'movies': [], 'tv_shows': []}
            limit = 20
            
            if media_type in ['all', 'movie']:
                with requests.get(
                    "https://api.themoviedb.org/3/trending/movie/week",
                    params={'api_key': api_key, 'language': 'en-GB'},
                    timeout=5
                ) as response:
                    if response.status_code == 200:
                        trending_data['movies'] = response.json().get('results', [])[:limit]
            
            if media_type in ['all', 'tv']:
                with requests.get(
                    "https://api.themoviedb.org/3/trending/tv/week", 
                    params={'api_key': api_key, 'language': 'en-GB'},
                    timeout=5
                ) as response:
                    if response.status_code == 200:
                        trending_data['tv_shows'] = response.json().get('results', [])[:limit]
            
            return trending_data
            
        except Exception as e:
            logging.error(f"Error fetching trending data: {str(e)}")
            return {'movies': [], 'tv_shows': []}
    
    def search_radarr(self, query):
        try:
            url = f"{self.config.radarr.url}/api/v3/movie/lookup"
            logging.info(f"[Radarr] searching: {url!r} term={query!r}")
            response = requests.get(url, params={'term': query, 'apikey': self.config.radarr.api_key}, timeout=10)
            results = response.json()
            logging.info(f"[Radarr] search HTTP {response.status_code}, {len(results) if isinstance(results, list) else 'error'} results")
            return results
        except Exception as e:
            logging.error(f"[Radarr] search error: {str(e)}", exc_info=True)
            return []

    def search_sonarr(self, query):
        try:
            url = f"{self.config.sonarr.url}/api/v3/series/lookup"
            logging.info(f"[Sonarr] searching: {url!r} term={query!r}")
            response = requests.get(url, params={'term': query, 'apikey': self.config.sonarr.api_key}, timeout=10)
            results = response.json()
            logging.info(f"[Sonarr] search HTTP {response.status_code}, {len(results) if isinstance(results, list) else 'error'} results")
            return results
        except Exception as e:
            logging.error(f"[Sonarr] search error: {str(e)}", exc_info=True)
            return []

    def add_to_radarr(self, tmdb_id):
        url = f"{self.config.radarr.url}/api/v3/movie"
        headers = {'Content-Type': 'application/json'}
        payload = {
            'tmdbId': tmdb_id,
            'monitored': True,
            'rootFolderPath': self.config.radarr.root_folder,
            'qualityProfileId': self.config.radarr.quality_profile_id,
            'addOptions': {'searchForMovie': True}
        }
        response = requests.post(
            url, 
            json=payload, 
            headers=headers,
            params={'apikey': self.config.radarr.api_key}
        )
        return response.status_code in [200, 201]
    
    def add_to_sonarr(self, series_id, source="tmdb"):
        lookup_url = f"{self.config.sonarr.url}/api/v3/series/lookup"
        params = {'term': f'{source}:{series_id}', 'apikey': self.config.sonarr.api_key}
        
        lookup_res = requests.get(lookup_url, params=params)
        if lookup_res.status_code != 200:
            return False
        
        results = lookup_res.json()
        if not results or len(results) == 0:
            print(f"No series found on Sonarr for {source}:{series_id}")
            return False
        
        series_data = lookup_res.json()[0]
        
        series_data.update({
            'monitored': True,
            'rootFolderPath': self.config.sonarr.root_folder,
            'qualityProfileId': self.config.sonarr.quality_profile_id,
            'languageProfileId': self.config.sonarr.language_profile_id,
            'seasonFolder': True,
            'seriesType': 'standard',
            'addOptions': {
                'searchForMissingEpisodes': True, 
                'monitor': 'all'
            }
        })        
        response = requests.post(
            f"{self.config.sonarr.url}/api/v3/series",
            json=series_data,
            params={'apikey': self.config.sonarr.api_key}
        )
        
        return response.status_code in [200, 201]
    
    def get_radarr_movies(self):
        url = f"{self.config.radarr.url}/api/v3/movie"
        response = requests.get(url, params={'apikey': self.config.radarr.api_key})
        return response.json()
    
    def get_sonarr_series(self):
        url = f"{self.config.sonarr.url}/api/v3/series"
        response = requests.get(url, params={'apikey': self.config.sonarr.api_key})
        return response.json()
    
    def get_radarr_details(self, tmdb_id):
        existing_url = f"{self.config.radarr.url}/api/v3/movie"
        existing = requests.get(existing_url, params={'apikey': self.config.radarr.api_key}).json()
        
        for movie in existing:
            if str(movie.get('tmdbId')) == str(tmdb_id):
                movie_url = f"{self.config.radarr.url}/api/v3/movie/{movie['id']}"
                full_details = requests.get(movie_url, params={'apikey': self.config.radarr.api_key}).json()
                
                if 'images' not in full_details:
                    full_details['images'] = []
                if full_details.get('remotePoster'):
                    full_details['images'].append({
                        'coverType': 'poster',
                        'url': full_details['remotePoster'],
                        'remoteUrl': full_details['remotePoster']
                    })
                
                return {
                    'status': 'existing',
                    'data': full_details,
                    'on_disk': full_details.get('hasFile', False),
                    'monitored': full_details.get('monitored', False)
                }
        
        lookup_url = f"{self.config.radarr.url}/api/v3/movie/lookup/tmdb"
        lookup = requests.get(lookup_url, params={
            'tmdbId': tmdb_id,
            'apikey': self.config.radarr.api_key
        }).json()
        
        if isinstance(lookup, list):
            lookup = lookup[0] if lookup else {}
        
        if 'images' not in lookup:
            lookup['images'] = []
        if lookup.get('remotePoster'):
            lookup['images'].append({
                'coverType': 'poster',
                'url': lookup['remotePoster'],
                'remoteUrl': lookup['remotePoster']
            })
        
        return {
            'status': 'not_added',
            'data': lookup,
            'on_disk': False,
            'monitored': False
        }
    
    def get_sonarr_details(self, tvdb_id):
        existing_url = f"{self.config.sonarr.url}/api/v3/series"
        existing = requests.get(existing_url, params={'apikey': self.config.sonarr.api_key}).json()
        
        source = "tmdb"
        for series in existing:
            if str(series.get('tvdbId')) == str(tvdb_id):
                source = "tvdb"
                status_url = f"{self.config.sonarr.url}/api/v3/series/{series['id']}"
                details = requests.get(status_url, params={'apikey': self.config.sonarr.api_key}).json()
                
                return {
                    'status': 'existing',
                    'data': details,
                    'on_disk': details.get('statistics', {}).get('percentOfEpisodes') > 0,
                    'monitored': details.get('monitored', False),
                    'download_status': f"{details.get('statistics', {}).get('percentOfEpisodes', 0)}% complete",
                    'season_count': details.get('statistics', {}).get('seasonCount'),
                    'episode_count': details.get('statistics', {}).get('episodeCount')
                }
        
        lookup_url = f"{self.config.sonarr.url}/api/v3/series/lookup"
        lookup = requests.get(lookup_url, params={
            'term': f'{source}:{tvdb_id}',
            'apikey': self.config.sonarr.api_key
        }).json()
        
        if lookup:
            return {
                'status': 'not_added',
                'data': lookup[0],
                'on_disk': False,
                'monitored': False,
                'series_status': lookup[0].get('status', 'unknown')
            }
        
        return {'error': 'Series not found'}
    
    def get_tmdb_media_details(self, media_type, tmdb_id):
        base_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        params = {
            'api_key': self.config.tmdb.key,
            'language': 'en-GB',
            'append_to_response': 'videos,images'
        }
        
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        result = {
            'title': data.get('name') or data.get('title'),
            'overview': data.get('overview'),
            'poster_path': data.get('poster_path'),
            'backdrop_path': data.get('backdrop_path'),
            'vote_average': data.get('vote_average'),
            'genres': [g['name'] for g in data.get('genres', [])],
            'first_air_date': data.get('first_air_date'),
            'last_air_date': data.get('last_air_date'),
            'status': data.get('status'),
            'videos': data.get('videos', {}).get('results', []),
            'images': data.get('images', {}).get('posters', [])
        }
        
        result['trailer'] = next(
            (v for v in result['videos']
             if v.get('site') == 'YouTube' 
             and v.get('type') == 'Trailer'
             and v.get('official') is True),
            None
        )
        
        return result

    # ============ GOOGLE BOOKS METHODS ============

    def search_google_books(self, query, max_items=10):
        """Search Google Books API and normalise results to Addarr book format.

        No API key required for up to ~1,000 requests/day.
        Set GOOGLE_BOOKS_API_KEY for a higher quota.

        Docs: https://developers.google.com/books/docs/v1/using#query-params
        """
        import re
        try:
            api_key = (getattr(self.config.google_books, 'api_key', '') or '').strip()
            params  = {
                'q':          query,
                'maxResults': min(max_items, 40),   # API cap is 40
                'printType':  'books',
                'langRestrict': 'en',
            }
            if api_key:
                params['key'] = api_key

            logging.info(f"[GoogleBooks] search q={query!r}")
            response = requests.get(
                'https://www.googleapis.com/books/v1/volumes',
                params=params,
                timeout=15,
            )
            if response.status_code != 200:
                logging.error(f"[GoogleBooks] HTTP {response.status_code}: {response.text[:400]}")
                return []

            data  = response.json()
            items = data.get('items') or []
            logging.info(f"[GoogleBooks] {len(items)} results for q={query!r}")

            results = []
            for item in items:
                info = item.get('volumeInfo') or {}

                # ── Title ──────────────────────────────────────────────────────
                title = info.get('title', '')
                subtitle = info.get('subtitle', '')
                if subtitle:
                    title = f"{title}: {subtitle}"

                # ── Author ─────────────────────────────────────────────────────
                authors = info.get('authors') or []
                author_str = ', '.join(authors) if authors else ''

                # ── Cover image ────────────────────────────────────────────────
                img_links = info.get('imageLinks') or {}
                # Prefer highest-res available; upgrade thumbnail to larger size
                cover_url = (
                    img_links.get('extraLarge') or
                    img_links.get('large') or
                    img_links.get('medium') or
                    img_links.get('thumbnail') or
                    img_links.get('smallThumbnail') or ''
                )
                # Google Books thumbnails use http — force https and strip zoom/edge params
                if cover_url:
                    cover_url = cover_url.replace('http://', 'https://')
                    cover_url = re.sub(r'&?(zoom=\d+|edge=curl)', '', cover_url)
                    # Bump to larger size by removing the zoom restriction
                    cover_url = cover_url.rstrip('&?')

                # ── Publication year ───────────────────────────────────────────
                pub_date = info.get('publishedDate', '')
                yr_match = re.search(r'(\d{4})', pub_date)
                year     = yr_match.group(1) if yr_match else ''

                # ── ISBN / ID ──────────────────────────────────────────────────
                identifiers = info.get('industryIdentifiers') or []
                isbn_13 = next((x['identifier'] for x in identifiers
                                if x.get('type') == 'ISBN_13'), '')
                isbn_10 = next((x['identifier'] for x in identifiers
                                if x.get('type') == 'ISBN_10'), '')
                isbn    = isbn_13 or isbn_10
                # Use Google's volume ID as the foreignBookId
                foreign_id = item.get('id', '') or isbn

                # ── Genres ─────────────────────────────────────────────────────
                categories = info.get('categories') or []
                # Google sometimes returns broad categories like "Fiction / Fantasy"
                # Split and flatten them
                genres = []
                for cat in categories:
                    for part in cat.split('/'):
                        g = part.strip()
                        if g and g not in genres:
                            genres.append(g)

                # ── Page count ─────────────────────────────────────────────────
                pages = 0
                try:
                    pages = int(info.get('pageCount') or 0)
                except (ValueError, TypeError):
                    pages = 0

                images = (
                    [{'coverType': 'poster', 'remoteUrl': cover_url, 'url': cover_url}]
                    if cover_url else []
                )

                book_entry = {
                    'title':        title,
                    'overview':     info.get('description', ''),
                    'foreignBookId': foreign_id,
                    'goodreadsId':  '',          # not available from Google Books
                    'isbn':         isbn,
                    'author': {
                        'authorName':      author_str,
                        'foreignAuthorId': None,
                        'overview':        '',
                        'images':          [],
                    },
                    'releaseDate':  pub_date,
                    'pageCount':    pages,
                    'images':       images,
                    'remotePoster': cover_url,
                    'cover_url':    cover_url,
                    'year':         year,
                    'genres':       genres,
                    'ratings':      {'value': info.get('averageRating', 0)},
                    'media_type':   'book',
                    '_source':      'google_books',
                }
                results.append(book_entry)
                save_book_metadata(book_entry)

            return results

        except Exception as e:
            logging.error(f"[GoogleBooks] search error: {e}", exc_info=True)
            return []

    # ============ READARR METHODS ============

    def search_readarr(self, query):
        """Search Readarr for books"""
        if not self.config.readarr.url:
            logging.warning("[Readarr] search skipped — READARR_URL not configured")
            return []
        try:
            url = f"{self.config.readarr.url}/api/v1/book/lookup"
            params = {'term': query, 'apikey': self.config.readarr.api_key}
            logging.info(f"[Readarr] searching: {url!r} term={query!r}")
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                logging.error(f"[Readarr] search HTTP {response.status_code}: {response.text[:200]}")
                return []
            data = response.json()
            if not isinstance(data, list):
                logging.error(f"[Readarr] unexpected response type: {type(data).__name__} — {str(data)[:200]}")
                return []
            logging.info(f"[Readarr] search HTTP {response.status_code}, {len(data)} results")
            return data
        except Exception as e:
            logging.error(f"[Readarr] search error: {str(e)}", exc_info=True)
            return []

    def add_to_readarr(self, foreign_book_id):
        """Add a book to Readarr by looking up the author then adding via author endpoint.
        Returns (success: bool, message: str).
        """
        logging.info(f"[Readarr] adding book foreignBookId={foreign_book_id}")
        try:
            # Step 1: look up book by Goodreads ID
            lookup_url = f"{self.config.readarr.url}/api/v1/book/lookup"
            params = {'term': f'goodreads:{foreign_book_id}', 'apikey': self.config.readarr.api_key}
            lookup_res = requests.get(lookup_url, params=params, timeout=15)

            if lookup_res.status_code != 200:
                msg = f"Readarr lookup HTTP {lookup_res.status_code}: {lookup_res.text[:200]}"
                logging.error(f"[Readarr] {msg}")
                return False, msg

            results = lookup_res.json()
            if not isinstance(results, list) or not results:
                msg = "Readarr lookup returned no results for this book ID"
                logging.error(f"[Readarr] {msg}")
                return False, msg

            book_data = results[0]
            author_data = book_data.get('author') or {}

            if not author_data:
                msg = f"Book found but author data is missing (foreignBookId={foreign_book_id})"
                logging.error(f"[Readarr] {msg}")
                return False, msg

            if not author_data.get('foreignAuthorId'):
                msg = f"Author object missing foreignAuthorId — Readarr metadata may be incomplete"
                logging.warning(f"[Readarr] {msg}")
                # Still try — Readarr may accept it

            # Step 2: post author with the specific book monitored
            author_data.update({
                'monitored': True,
                'rootFolderPath': self.config.readarr.root_folder,
                'qualityProfileId': int(self.config.readarr.quality_profile_id) if self.config.readarr.quality_profile_id else 1,
                'metadataProfileId': int(self.config.readarr.metadata_profile_id) if self.config.readarr.metadata_profile_id else 1,
                'addOptions': {
                    'monitor': 'specific',
                    'booksToMonitor': [foreign_book_id],
                    'searchForMissingBooks': True
                }
            })

            response = requests.post(
                f"{self.config.readarr.url}/api/v1/author",
                json=author_data,
                params={'apikey': self.config.readarr.api_key},
                timeout=15
            )

            if response.status_code in (200, 201):
                logging.info(f"[Readarr] successfully added book {foreign_book_id}")
                return True, 'Added successfully'

            # 400 often means "author already exists" — try adding the book directly
            if response.status_code == 400:
                logging.info(f"[Readarr] author exists (400), attempting to add book directly")
                # Find the existing author
                authors_res = requests.get(
                    f"{self.config.readarr.url}/api/v1/author",
                    params={'apikey': self.config.readarr.api_key},
                    timeout=10
                )
                if authors_res.status_code == 200:
                    foreign_author_id = author_data.get('foreignAuthorId')
                    existing_author = next(
                        (a for a in authors_res.json()
                         if str(a.get('foreignAuthorId')) == str(foreign_author_id)),
                        None
                    )
                    if existing_author:
                        # Patch the book to be monitored
                        book_post = {
                            **book_data,
                            'monitored': True,
                            'author': existing_author,
                            'addOptions': {'searchForMissingBooks': True}
                        }
                        book_res = requests.post(
                            f"{self.config.readarr.url}/api/v1/book",
                            json=book_post,
                            params={'apikey': self.config.readarr.api_key},
                            timeout=15
                        )
                        if book_res.status_code in (200, 201):
                            return True, 'Book added to existing author'
                        logging.error(f"[Readarr] book POST HTTP {book_res.status_code}: {book_res.text[:300]}")

            msg = f"Readarr returned HTTP {response.status_code}: {response.text[:300]}"
            logging.error(f"[Readarr] {msg}")
            return False, msg

        except Exception as e:
            msg = str(e)
            logging.error(f"[Readarr] add error: {msg}", exc_info=True)
            return False, msg

    def get_readarr_books(self):
        """Get all books from Readarr library"""
        if not self.config.readarr.url:
            logging.warning("[Readarr] get_readarr_books skipped — READARR_URL not configured")
            return []
        try:
            url = f"{self.config.readarr.url}/api/v1/book"
            logging.info(f"[Readarr] fetching library from {url!r}")
            response = requests.get(url, params={'apikey': self.config.readarr.api_key}, timeout=10)
            books = response.json()
            for book in books:
                self._normalise_book_images(book)
                # Cache-only enrichment (no HTTP calls) — fills author/poster from
                # any previously cached Apify search results. api_fallback=False
                # prevents making one Readarr author API call per book in the list.
                self._enrich_book_from_cache(book, book.get('foreignBookId', ''), api_fallback=False)
            return books
        except Exception as e:
            logging.error(f"Error fetching Readarr books: {str(e)}")
            return []

    def _normalise_book_images(self, book):
        """Fix up Readarr image fields in-place.
        - coverType 'cover' → 'poster' (Addarr convention)
        - remoteUrl missing and url is a relative Readarr path →
          route through Addarr's /api/readarr/cover proxy so the
          browser doesn't need direct access to the Readarr host.
        """
        for img in book.get('images', []):
            local = img.get('url', '')
            if not img.get('remoteUrl') and local:
                if local.startswith('/'):
                    img['remoteUrl'] = f"/api/readarr/cover?path={requests.utils.quote(local, safe='/?=&')}"
                else:
                    img['remoteUrl'] = local
            if img.get('coverType') == 'cover':
                img['coverType'] = 'poster'

    def _fetch_readarr_author(self, author_id):
        """Fetch full author object from Readarr by internal author ID (integer).
        Returns the JSON dict on success, None on failure.
        """
        try:
            url = f"{self.config.readarr.url}/api/v1/author/{author_id}"
            r = requests.get(url, params={'apikey': self.config.readarr.api_key}, timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logging.debug(f"[Readarr] author lookup error: {e}")
        return None

    def _enrich_book_from_cache(self, book, foreign_book_id, api_fallback=True):
        """Fill in missing author/overview/poster fields on a Readarr book dict.

        Priority:
          1) already present in the Readarr object
          2) local Apify metadata cache  (always checked — fast disk read)
          3) Readarr /api/v1/author/{id} API call  (only when api_fallback=True)

        Pass api_fallback=False when enriching many books in bulk (e.g. the
        manage-books list) to avoid one HTTP request per book.
        """
        author_obj  = book.get('author') or {}
        if isinstance(author_obj, str):
            author_obj = {'authorName': author_obj}
            book['author'] = author_obj
        author_name = author_obj.get('authorName', '')
        overview    = book.get('overview', '')
        poster_ok   = any(
            img.get('remoteUrl') or img.get('url')
            for img in book.get('images', [])
            if img.get('coverType') in ('poster', 'cover')
        )

        if author_name and overview and poster_ok:
            return book   # nothing to enrich

        # 1. Local disk cache (fast — no HTTP)
        cached = load_book_metadata(str(foreign_book_id))
        if cached:
            if not author_name:
                cached_author = cached.get('author') or {}
                cached_name   = cached_author.get('authorName', '') if isinstance(cached_author, dict) else str(cached_author)
                if cached_name:
                    book.setdefault('author', {})['authorName'] = cached_name
                    author_name = cached_name
                    logging.debug(f"[cache] enriched authorName for {foreign_book_id} from disk cache")
            if not overview and cached.get('overview'):
                book['overview'] = cached['overview']
                overview = book['overview']
            if not poster_ok and cached.get('remotePoster'):
                book.setdefault('images', []).append({
                    'coverType': 'poster',
                    'remoteUrl': cached['remotePoster'],
                    'url': cached['remotePoster'],
                })
                book['remotePoster'] = cached['remotePoster']
                poster_ok = True

        if author_name and overview and poster_ok:
            return book   # fully enriched from cache — done

        if not api_fallback:
            return book   # bulk load mode — no HTTP calls allowed

        # 2. Google Books fallback (when google_books is enabled)
        gb_on = False
        try:
            gb_on = bool(self.config.google_books.enabled)
        except Exception:
            pass

        if gb_on and (not author_name or not poster_ok):
            title = book.get('title', '')
            if title:
                auth_hint = ''
                try:
                    ao = book.get('author') or {}
                    auth_hint = ao.get('authorName', '') if isinstance(ao, dict) else str(ao)
                except Exception:
                    pass
                query = f"{title} {auth_hint}".strip() if auth_hint else title
                try:
                    logging.info(f"[enrich] Google Books fallback for book {foreign_book_id}: {query!r}")
                    results = self.search_google_books(query, max_items=5)
                    # Best match: exact title > first result
                    tl = title.lower()
                    matched = next((r for r in results if r.get('title', '').lower() == tl), None)
                    if not matched and results:
                        matched = results[0]

                    if matched:
                        if not author_name:
                            ma = matched.get('author') or {}
                            mn = ma.get('authorName', '') if isinstance(ma, dict) else str(ma)
                            if mn:
                                book.setdefault('author', {})['authorName'] = mn
                                author_name = mn
                        if not poster_ok:
                            mp = matched.get('remotePoster', '')
                            if not mp:
                                for img in matched.get('images', []):
                                    if img.get('coverType') in ('poster', 'cover'):
                                        mp = img.get('remoteUrl') or img.get('url', '')
                                        if mp: break
                            if mp:
                                book.setdefault('images', []).append({
                                    'coverType': 'poster', 'remoteUrl': mp, 'url': mp,
                                })
                                book['remotePoster'] = mp
                                poster_ok = True
                        # Save under this book's foreignBookId if Google Books returned a different one
                        if str(matched.get('foreignBookId')) != str(foreign_book_id):
                            patched = dict(matched)
                            patched['foreignBookId'] = str(foreign_book_id)
                            save_book_metadata(patched)
                            logging.debug(f"[cache] saved Google Books data for book {foreign_book_id} (title match)")
                except Exception as e:
                    logging.warning(f"[enrich] Google Books fallback error: {e}")

        # 3. Readarr author API — last resort for missing authorName
        if not author_name and self.config.readarr.url:
            author_id = book.get('authorId') or (book.get('author') or {}).get('id')
            if author_id:
                author_data = self._fetch_readarr_author(author_id)
                if author_data and author_data.get('authorName'):
                    book.setdefault('author', {})['authorName'] = author_data['authorName']
                    logging.debug(f"[Readarr] enriched authorName for book {foreign_book_id} from author API")
                    # Persist so the next load finds it in cache
                    if not cached:
                        save_book_metadata({
                            'foreignBookId': str(foreign_book_id),
                            'title': book.get('title', ''),
                            'author': {'authorName': author_data['authorName']},
                            'images': book.get('images', []),
                            'remotePoster': book.get('remotePoster', ''),
                            'overview': book.get('overview', ''),
                        })
                        logging.debug(f"[cache] auto-saved Readarr author entry for book {foreign_book_id}")

        return book

    def get_readarr_details(self, foreign_book_id):
        """Get details for a specific book from Readarr, enriched from local cache."""
        try:
            # Check if it's in the library first
            library_url = f"{self.config.readarr.url}/api/v1/book"
            lib_response = requests.get(library_url, params={'apikey': self.config.readarr.api_key}, timeout=10)
            existing = lib_response.json() if lib_response.status_code == 200 else []
            if not isinstance(existing, list):
                logging.warning(f"[Readarr] /api/v1/book returned non-list ({type(existing).__name__}): {str(existing)[:200]}")
                existing = []

            for book in existing:
                if str(book.get('foreignBookId')) == str(foreign_book_id):
                    self._normalise_book_images(book)
                    self._enrich_book_from_cache(book, foreign_book_id)
                    return {
                        'status': 'existing',
                        'data': book,
                        'on_disk': (book.get('statistics', {}).get('sizeOnDisk', 0) > 0),
                        'monitored': book.get('monitored', False)
                    }

            # Not in library — look it up in Readarr
            lookup_url = f"{self.config.readarr.url}/api/v1/book/lookup"
            lookup_resp = requests.get(lookup_url, params={
                'term': f'goodreads:{foreign_book_id}',
                'apikey': self.config.readarr.api_key
            }, timeout=10)
            lookup = lookup_resp.json() if lookup_resp.status_code == 200 else []
            if not isinstance(lookup, list):
                logging.warning(f"[Readarr] book/lookup returned non-list: {str(lookup)[:200]}")
                lookup = []

            if lookup:
                book = lookup[0]
                self._normalise_book_images(book)
                self._enrich_book_from_cache(book, foreign_book_id)
                return {
                    'status': 'not_added',
                    'data': book,
                    'on_disk': False,
                    'monitored': False
                }

            # Readarr has nothing — try the local Apify metadata cache directly
            cached = load_book_metadata(str(foreign_book_id))
            if cached:
                logging.info(f"[cache] using cached metadata for book {foreign_book_id} (not in Readarr)")
                return {
                    'status': 'not_added',
                    'data': cached,
                    'on_disk': False,
                    'monitored': False
                }

            return {'error': 'Book not found'}

        except Exception as e:
            logging.error(f"Error fetching Readarr details: {str(e)}")
            # Last-resort fallback: serve from local cache if available
            cached = load_book_metadata(str(foreign_book_id))
            if cached:
                return {'status': 'not_added', 'data': cached, 'on_disk': False, 'monitored': False}
            return {'error': str(e)}

    def get_readarr_book_file_path(self, book_id):
        """Return the on-disk path for the first EPUB or PDF file for a book.
        book_id is the Readarr internal integer book ID (not foreignBookId).
        Returns the path string or None.
        """
        try:
            url = f"{self.config.readarr.url}/api/v1/bookFile"
            params = {'bookId': book_id, 'apikey': self.config.readarr.api_key}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                logging.error(f"[Readarr] bookFile HTTP {r.status_code}")
                return None
            files = r.json()
            if not isinstance(files, list) or not files:
                return None
            # Prefer EPUB, then fall back to first file
            for book_file in files:
                path = book_file.get('path', '')
                if path.lower().endswith('.epub'):
                    return path
            for book_file in files:
                path = book_file.get('path', '')
                if path.lower().endswith('.pdf'):
                    return path
            # Any file
            return files[0].get('path')
        except Exception as e:
            logging.error(f"[Readarr] get_book_file_path error: {str(e)}", exc_info=True)
            return None

    # ============ PROWLARR METHODS ============

    def search_prowlarr(self, query, categories=None):
        """Search Prowlarr across all indexers.
        categories: optional list of Newznab category IDs, e.g. [2000] for movies.
        """
        try:
            url = f"{self.config.prowlarr.url}/api/v1/search"
            params = [
                ('query', query),
                ('type', 'search'),
                ('limit', 100),
                ('offset', 0),
                ('apikey', self.config.prowlarr.api_key),
            ]
            if categories:
                for cat in categories:
                    params.append(('categories', cat))
            logging.info(f"[Prowlarr] searching: term={query!r} categories={categories}")
            response = requests.get(url, params=params, timeout=20)
            if response.status_code != 200:
                logging.error(f"[Prowlarr] search HTTP {response.status_code}: {response.text[:200]}")
                return []
            data = response.json()
            logging.info(f"[Prowlarr] search returned {len(data)} results")
            return data
        except Exception as e:
            logging.error(f"[Prowlarr] search error: {str(e)}", exc_info=True)
            return []

    # ============ QBITTORRENT METHODS ============

    def _qbit_login(self):
        """Login to qBittorrent and return a session cookie (SID)"""
        url = f"{self.config.qbit.url}/api/v2/auth/login"
        response = requests.post(url, data={
            'username': self.config.qbit.username,
            'password': self.config.qbit.password
        }, timeout=10)
        if response.text.strip().lower() == 'ok.':
            return response.cookies.get('SID')
        raise Exception(f"qBittorrent login failed: {response.text[:100]}")

    def qbit_test(self):
        """Test qBittorrent connection"""
        try:
            sid = self._qbit_login()
            if not sid:
                return {'status': 'error', 'message': 'Login failed — check credentials'}
            url = f"{self.config.qbit.url}/api/v2/app/version"
            r = requests.get(url, cookies={'SID': sid}, timeout=10)
            if r.status_code == 200:
                return {'status': 'ok', 'version': r.text.strip()}
            return {'status': 'error', 'message': f'HTTP {r.status_code}'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def qbit_add_torrent(self, torrent_url, category=''):
        """Add a torrent to qBittorrent by URL"""
        try:
            sid = self._qbit_login()
            url = f"{self.config.qbit.url}/api/v2/torrents/add"
            data = {'urls': torrent_url}
            if category:
                data['category'] = category
            r = requests.post(url, data=data, cookies={'SID': sid}, timeout=15)
            if r.status_code == 200 and r.text.strip().lower() == 'ok.':
                return {'success': True}
            return {'success': False, 'message': r.text[:200]}
        except Exception as e:
            logging.error(f"[qBit] add torrent error: {str(e)}", exc_info=True)
            return {'success': False, 'message': str(e)}

    def qbit_get_torrents(self):
        """Get all torrents from qBittorrent"""
        try:
            sid = self._qbit_login()
            url = f"{self.config.qbit.url}/api/v2/torrents/info"
            r = requests.get(url, cookies={'SID': sid}, timeout=10)
            if r.status_code == 200:
                return r.json()
            logging.error(f"[qBit] get torrents HTTP {r.status_code}")
            return []
        except Exception as e:
            logging.error(f"[qBit] get torrents error: {str(e)}", exc_info=True)
            return []

    def qbit_action(self, action, hashes):
        """Perform an action on one or more torrents.
        action: 'resume' | 'pause' | 'delete' | 'setForceStart'
        hashes: str or list of torrent hashes
        """
        try:
            sid = self._qbit_login()
            if isinstance(hashes, list):
                hash_str = '|'.join(hashes)
            else:
                hash_str = hashes

            if action == 'setForceStart':
                url = f"{self.config.qbit.url}/api/v2/torrents/setForceStart"
                r = requests.post(url, data={'hashes': hash_str, 'value': 'true'},
                                  cookies={'SID': sid}, timeout=10)
            elif action == 'delete':
                url = f"{self.config.qbit.url}/api/v2/torrents/delete"
                r = requests.post(url, data={'hashes': hash_str, 'deleteFiles': 'false'},
                                  cookies={'SID': sid}, timeout=10)
            else:
                # 'resume' or 'pause'
                url = f"{self.config.qbit.url}/api/v2/torrents/{action}"
                r = requests.post(url, data={'hashes': hash_str},
                                  cookies={'SID': sid}, timeout=10)

            if r.status_code == 200:
                return {'success': True}
            msg = f"qBittorrent returned HTTP {r.status_code}: {r.text[:200]}"
            logging.error(f"[qBit] action={action} {msg}")
            return {'success': False, 'message': msg}
        except Exception as e:
            logging.error(f"[qBit] action={action} error: {str(e)}", exc_info=True)
            return {'success': False, 'message': str(e)}

    def check_auth(self, username, password):
        """Check authentication"""
        if not self.config.auth.enabled:
            return True
        return (username == self.config.auth.username and 
                password == self.config.auth.password)