# routes.py
from flask import render_template, request, jsonify, Response, session, redirect, url_for, send_from_directory, send_file
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
import logging
import time
import os
from collections import deque
import requests
import re
from datetime import datetime
from update_manager import UpdateManager
import books_db
from PIL import Image
import io, requests as req


# Import shared utilities (will be passed from app.py)
def init_routes(app, config_manager, update_manager, auth_decorator, debug_decorator, shared_utils, network_info_func=None, kindle_detector=None):
    """
    Initialize all routes with shared dependencies
    """
    
    # Store shared utilities for route functions to use
    global CONFIG, requires_auth, conditional_debug_log, utils
    CONFIG = config_manager
    requires_auth = auth_decorator
    conditional_debug_log = debug_decorator
    utils = shared_utils
    update_manager = update_manager
    is_kindle_request = kindle_detector or (lambda: False)

    # ── Kindle / reader request+response logging ──────────────────────────────
    _KINDLE_LOG_PREFIXES = ('/kindle', '/api/book/azw3/', '/api/book/cover/')

    @app.before_request
    def _log_kindle_request():
        if not any(request.path.startswith(p) for p in _KINDLE_LOG_PREFIXES):
            return
        ua  = request.headers.get('User-Agent', '—')
        logging.info(
            '[KindleLog] ▶ %s %s | is_kindle=%s | IP=%s\n'
            '            UA: %s\n'
            '            Headers: %s',
            request.method, request.path,
            is_kindle_request(), request.remote_addr,
            ua,
            dict(request.headers),
        )

    @app.after_request
    def _log_kindle_response(response):
        if not any(request.path.startswith(p) for p in _KINDLE_LOG_PREFIXES):
            return response
        logging.info(
            '[KindleLog] ◀ %s %s → %s | content-type=%s | content-length=%s',
            request.method, request.path,
            response.status_code,
            response.content_type,
            response.headers.get('Content-Length', '—'),
        )
        return response


    # Library status cache — two-tier: in-memory (60s) + disk (5 min)
    # Only status fields (hasFile, monitored, statistics) go stale.
    # Static metadata (posters, titles, etc.) is cached permanently elsewhere.
    library_cache = {
        'movies': {'data': None, 'timestamp': 0},
        'series': {'data': None, 'timestamp': 0},
        'books':  {'data': None, 'timestamp': 0}
    }
    MEM_CACHE_TTL    = 60    # seconds before re-reading disk cache
    STATUS_CACHE_TTL = 300   # 5 minutes — only status can go stale

    def get_cached_library(media_type):
        """Three-tier library cache:
        1. In-memory dict (60 s TTL) — zero I/O
        2. Disk JSON file (1 hr TTL) — no API call
        3. Live API fetch — differential merge + save to disk
        """
        from utils import save_media_cache, load_media_cache

        cache_key = 'movies' if media_type == 'movie' else ('books' if media_type == 'book' else 'series')
        cache_entry = library_cache[cache_key]
        now = time.time()

        # ── Tier 1: in-memory ────────────────────────────────────────────────
        if cache_entry['data'] is not None and (now - cache_entry['timestamp']) < MEM_CACHE_TTL:
            return cache_entry['data']

        # ── Tier 2: disk cache ───────────────────────────────────────────────
        disk_data, disk_ts = load_media_cache(cache_key)
        if disk_data is not None and (now - disk_ts) < STATUS_CACHE_TTL:
            cache_entry['data']      = disk_data
            cache_entry['timestamp'] = now
            return disk_data

        # ── Tier 3: live API fetch with differential update ──────────────────
        try:
            if media_type == 'movie':
                resp = requests.get(f"{CONFIG.radarr.url}/api/v3/movie",
                                    params={'apikey': CONFIG.radarr.api_key}, timeout=15)
            elif media_type == 'book':
                resp = requests.get(f"{CONFIG.readarr.url}/api/v1/book",
                                    params={'apikey': CONFIG.readarr.api_key}, timeout=15)
            else:
                resp = requests.get(f"{CONFIG.sonarr.url}/api/v3/series",
                                    params={'apikey': CONFIG.sonarr.api_key}, timeout=15)

            new_data = resp.json()
            if not isinstance(new_data, list):
                raise ValueError(f"Unexpected response type: {type(new_data)}")

            # Differential merge: start from old disk data, apply only changed records
            if disk_data:
                old_by_id = {str(item.get('id', '')): item for item in disk_data}
                new_by_id = {str(item.get('id', '')): item for item in new_data}
                merged = []
                # Keep all new records (updated or new)
                for item in new_data:
                    merged.append(item)
                # Add any old records that are no longer in the API response (deleted) — skip them
                # (new_data is authoritative; anything not in new_data is gone)
                new_data = merged

            cache_entry['data']      = new_data
            cache_entry['timestamp'] = now
            save_media_cache(cache_key, new_data)
            logging.debug(f"[cache] refreshed {cache_key} from API ({len(new_data)} items)")
            return new_data

        except Exception as e:
            logging.error(f"[cache] Error fetching {media_type} library: {e}")
            # Fallback chain: disk → memory → empty
            if disk_data is not None:
                return disk_data
            return cache_entry['data'] if cache_entry['data'] is not None else []

    # ============ ROUTE DEFINITIONS ============
    @app.route('/')
    @conditional_debug_log
    @requires_auth  
    def index():
        try:
            return render_template('index.html', config=CONFIG._config)
        except Exception as e:
            logging.error(f"Error loading index: {str(e)}")
            return render_template('index.html', error="Page load failed")

    @app.route('/manage-books')
    @conditional_debug_log
    @requires_auth
    def manage_books():
        """Filesystem-first book library.

        Source priority per book:
          1. Local DB (this app)  — instant, no network
          2. (Client) Goodreads via Apify
          3. (Client) Readarr API
          4. (Client) Manual import dialog — pre-populated from file metadata
        """
        # Kindle Paperwhite gets its own simplified template
        if is_kindle_request():
            return redirect(url_for('kindle_books'))
        try:
            from utils import scan_books_folder, extract_file_metadata, _title_from_filename
            books_db.init_db()
            root_folder = CONFIG.readarr.root_folder if CONFIG.readarr.enabled else None

            # ── Scan filesystem ────────────────────────────────────────────────
            scanned = scan_books_folder(root_folder) if root_folder else []

            # Separate AZW3 companion files from readable source files.
            # AZW3s are created by our conversion pipeline and must not appear
            # as independent entries in the browser-readable book list.
            azw3_stems = set()
            source_files = []
            for b in scanned:
                stem = os.path.splitext(b['file_path'])[0]
                if b['extension'] == '.azw3':
                    azw3_stems.add(stem)
                elif b['extension'] in ('.epub', '.pdf'):
                    source_files.append(b)
                # mobi / cbz / cbr — not browser-readable, skip

            # ── Batch DB lookup ────────────────────────────────────────────────
            paths    = [b['file_path'] for b in source_files]
            db_books = books_db.get_books_by_paths(paths)

            # ── Merge: for new files, create a minimal DB record immediately ──
            merged = []
            for fs in source_files:
                fp = fs['file_path']
                if fp in db_books:
                    rec = db_books[fp]
                    # Backfill year/pages/genre if the record was saved without them
                    missing = [k for k in ('year', 'pages', 'genre') if not rec.get(k)]
                    if missing:
                        meta = extract_file_metadata(fp)
                        upd = {k: meta.get(k) for k in missing if meta.get(k)}
                        if upd:
                            rec = books_db.save_book({'file_path': fp, **upd}) or rec
                else:
                    # Extract metadata from the file itself (no network, fast)
                    meta = extract_file_metadata(fp)
                    title = (meta.get('title')
                             or _title_from_filename(fs['filename']))
                    rec = books_db.save_book({
                        'file_path': fp,
                        'title':     title,
                        'author':    meta.get('author'),
                        'overview':  meta.get('overview'),
                        'year':      meta.get('year'),
                        'pages':     meta.get('pages'),
                        'isbn':      meta.get('isbn'),
                        'genre':     meta.get('genre'),
                        'source':    meta.get('source', 'filename'),
                    })

                stem     = os.path.splitext(fp)[0]
                has_azw3 = stem in azw3_stems
                merged.append({
                    **fs,               # file_path, filename, extension, file_size, rel_path
                    **(rec or {}),      # DB fields override / supplement
                    'has_azw3': has_azw3,
                })

            merged.sort(key=lambda b: (b.get('title') or b['filename']).lower())

            return render_template(
                'manage-books.html',
                books=merged,
                config=CONFIG._config,
                total_downloaded=len(merged),
                root_folder=root_folder or '',
            )
        except Exception as e:
            logging.error(f"Error loading manage-books: {e}", exc_info=True)
            return render_template('error.html', error="Failed to load books")


    @app.route('/kindle')
    @conditional_debug_log
    @requires_auth
    def kindle_books():
        logging.info('[KindleLog] /kindle hit | UA=%s', request.headers.get('User-Agent', '—'))
        try:
            from utils import scan_books_folder, extract_file_metadata, _title_from_filename
            books_db.init_db()
            root_folder = CONFIG.readarr.root_folder if CONFIG.readarr.enabled else None
            scanned  = scan_books_folder(root_folder) if root_folder else []

            # Separate AZW3 files from source files; note which stems have AZW3s
            azw3_stems = set()
            source_files = []
            for b in scanned:
                stem = os.path.splitext(b['file_path'])[0]
                if b['extension'] == '.azw3':
                    azw3_stems.add(stem)
                else:
                    source_files.append(b)

            paths    = [b['file_path'] for b in source_files]
            db_books = books_db.get_books_by_paths(paths)
            merged   = []
            for fs in source_files:
                fp = fs['file_path']
                if fp in db_books:
                    rec = db_books[fp]
                else:
                    meta  = extract_file_metadata(fp)
                    title = meta.get('title') or _title_from_filename(fs['filename'])
                    rec   = books_db.save_book({
                        'file_path': fp, 'title': title,
                        'author': meta.get('author'),
                        'year':   meta.get('year'),
                        'pages':  meta.get('pages'),
                        'genre':  meta.get('genre'),
                        'source': meta.get('source', 'filename'),
                    })
                stem     = os.path.splitext(fp)[0]
                has_azw3 = stem in azw3_stems
                merged.append({**fs, **(rec or {}), 'has_azw3': has_azw3})

            merged.sort(key=lambda b: (b.get('title') or b['filename']).lower())

            # Collect filter option lists for the template
            genres  = sorted(set(
                g.strip()
                for b in merged
                for g in (b.get('genre') or '').split(',')
                if g.strip()
            ))
            years   = sorted(set(
                b.get('year') for b in merged if b.get('year')
            ), reverse=True)

            logging.info('[KindleLog] /kindle → kindle.html, %d books (%d with AZW3)',
                         len(merged), sum(1 for b in merged if b['has_azw3']))
            return render_template('kindle.html',
                                   books=merged,
                                   genres=genres,
                                   years=years,
                                   config=CONFIG._config)
        except Exception as e:
            logging.error(f"Kindle route error: {e}", exc_info=True)
            return render_template('error.html', error="Failed to load book library")

    @app.route('/kindle/book/<int:db_id>')
    @requires_auth
    def kindle_book_detail(db_id):
        """Book detail page for the Kindle — cover, metadata, AZW3 download link."""
        book = books_db.get_book_by_id(db_id)
        if not book:
            return render_template('error.html', error="Book not found"), 404
        file_path = book.get('file_path', '')
        azw3_path = os.path.splitext(file_path)[0] + '.azw3' if file_path else ''
        has_azw3  = bool(azw3_path and os.path.isfile(azw3_path))
        # If the source file itself is AZW3
        if not has_azw3 and file_path and os.path.splitext(file_path)[1].lower() == '.azw3':
            has_azw3 = os.path.isfile(file_path)
        file_size = None
        if file_path and os.path.isfile(file_path):
            sz = os.path.getsize(file_path)
            file_size = f"{sz / 1_048_576:.1f} MB"
        return render_template('kindle_book.html',
                               book=book,
                               has_azw3=has_azw3,
                               file_size=file_size,
                               config=CONFIG._config)

    @app.route('/api/book/azw3/<int:db_id>')
    @requires_auth
    def book_azw3(db_id):
        """Serve the AZW3 file for a book so the Kindle can import it."""
        book = books_db.get_book_by_id(db_id)
        if not book or not book.get('file_path'):
            return jsonify({'error': 'Not found'}), 404
        file_path = book['file_path']
        ext       = os.path.splitext(file_path)[1].lower()
        # Prefer derived AZW3 alongside the source file
        if ext != '.azw3':
            azw3_path = os.path.splitext(file_path)[0] + '.azw3'
        else:
            azw3_path = file_path
        if not os.path.isfile(azw3_path):
            return jsonify({'error': 'AZW3 not ready yet — conversion in progress'}), 404
        filename = os.path.basename(azw3_path)
        logging.info('[KindleLog] /api/book/azw3/%d — serving %s (%d bytes)',
                     db_id, azw3_path, os.path.getsize(azw3_path))
        return send_file(
            azw3_path,
            mimetype='application/vnd.amazon.ebook',
            as_attachment=True,
            download_name=filename,
        )

    @app.route('/api/book/convert/<int:db_id>', methods=['POST'])
    @requires_auth
    def book_convert(db_id):
        """Synchronously convert a single book to AZW3 and report the result."""
        from utils import ensure_azw3
        book = books_db.get_book_by_id(db_id)
        if not book or not book.get('file_path'):
            return jsonify({'success': False, 'error': 'Book not found'}), 404
        file_path = book['file_path']
        azw3_path, status = ensure_azw3(file_path)
        if status in ('exists', 'converted'):
            return jsonify({'success': True, 'status': status,
                            'azw3_path': azw3_path})
        return jsonify({'success': False, 'status': status,
                        'error': 'Conversion failed — check server logs for details'})

    @app.route('/trending')
    @conditional_debug_log
    @requires_auth  
    def trending_media():
        try:
            media_type = request.args.get('type', 'all')
            trending_data = utils.fetch_trending_optimized(media_type)
            
            return render_template(
                'trending.html',
                trending_data=trending_data,
                media_type=media_type,
                config=CONFIG._config
            )
        except Exception as e:
            logging.error(f"Error loading trending media: {str(e)}")
            return render_template('error.html', error="Failed to load trending media")

    @app.route('/logs')
    @conditional_debug_log
    @requires_auth  
    def get_logs():
        try:
            log_path = 'addarr.log'
            lines_to_return = min(int(request.args.get('lines', 500)), 2000)
            
            if not os.path.exists(log_path):
                return jsonify({'success': False, 'error': 'Log file not found'})
            
            def generate():
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    buffer = deque(f, maxlen=lines_to_return)
                    yield ''.join(buffer)
            
            return Response(generate(), mimetype='text/plain')
            
        except Exception as e:
            logging.error(f"Error reading logs: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/debug/memory')
    @requires_auth
    def memory_status():
        """Memory monitoring endpoint"""
        try:
            import psutil
            import gc
            
            process = psutil.Process()
            memory_info = process.memory_info()
            system_memory = psutil.virtual_memory()
            
            return jsonify({
                'process_memory': {
                    'rss_mb': memory_info.rss / 1024 / 1024,
                    'vms_mb': memory_info.vms / 1024 / 1024,
                    'percent': process.memory_percent(),
                    'open_files': len(process.open_files()),
                    'threads': process.num_threads(),
                },
                'system_memory': {
                    'total_mb': system_memory.total / 1024 / 1024,
                    'available_mb': system_memory.available / 1024 / 1024,
                    'percent': system_memory.percent
                },
                'garbage_collection': {
                    'collected': gc.get_count(),
                    'thresholds': gc.get_threshold(),
                    'enabled': gc.isenabled()
                }
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/debug/cleanup', methods=['POST'])
    @requires_auth
    def force_cleanup():
        """Force memory cleanup"""
        try:
            import gc
            collected = gc.collect()
            return jsonify({
                'success': True,
                'collected': collected,
                'message': f'Garbage collector collected {collected} objects'
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/search', methods=['GET', 'POST'])
    @conditional_debug_log
    @requires_auth
    def search():
        query = request.args.get('q') or request.form.get('query')
        readarr_enabled    = CONFIG.readarr.enabled
        googlebooks_enabled = CONFIG.google_books.enabled
        logging.info(
            f"[SEARCH] query='{query}' | radarr={bool(CONFIG.radarr.url)} "
            f"sonarr={bool(CONFIG.sonarr.url)} readarr={readarr_enabled} google_books={googlebooks_enabled}"
        )

        try:
            book_search_enabled = readarr_enabled or googlebooks_enabled
            max_workers = 3 if book_search_enabled else 2

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                movie_future = executor.submit(utils.search_radarr, query)
                tv_future    = executor.submit(utils.search_sonarr, query)
                if googlebooks_enabled:
                    book_future = executor.submit(utils.search_google_books, query)
                elif readarr_enabled:
                    book_future = executor.submit(utils.search_readarr, query)
                else:
                    book_future = None

                movie_results = movie_future.result()
                tv_results    = tv_future.result()
                book_results  = book_future.result() if book_future else []

            movie_results = movie_results if isinstance(movie_results, list) else []
            tv_results = tv_results if isinstance(tv_results, list) else []
            book_results = book_results if isinstance(book_results, list) else []

            logging.info(f"[SEARCH] results: {len(movie_results)} movies, {len(tv_results)} TV, {len(book_results)} books")

            for movie in movie_results:
                movie['media_type'] = 'movie'
            for tv_show in tv_results:
                tv_show['media_type'] = 'tv'
            for book in book_results:
                book['media_type'] = 'book'
                # Normalise cover image field
                for img in book.get('images', []):
                    if 'url' in img and 'remoteUrl' not in img:
                        img['remoteUrl'] = img['url']
                    if img.get('coverType') == 'cover':
                        img['coverType'] = 'poster'
                # Set a top-level remotePoster for template convenience
                if not book.get('remotePoster'):
                    for img in book.get('images', []):
                        if img.get('coverType') == 'poster':
                            book['remotePoster'] = img.get('remoteUrl', '')
                            break
                # Set year from releaseDate
                if not book.get('year') and book.get('releaseDate'):
                    try:
                        book['year'] = book['releaseDate'][:4]
                    except Exception:
                        pass

            # Interleave results: TV, Movie, Book
            combined_results = []
            max_length = max(len(movie_results), len(tv_results), len(book_results)) if (movie_results or tv_results or book_results) else 0
            for i in range(max_length):
                if i < len(tv_results):
                    combined_results.append(tv_results[i])
                if i < len(movie_results):
                    combined_results.append(movie_results[i])
                if i < len(book_results):
                    combined_results.append(book_results[i])

            return render_template(
                'results.html',
                results=combined_results,
                media_type='combined',
                movies=len(movie_results),
                tv_shows=len(tv_results),
                books=len(book_results),
                all_results=len(combined_results),
                query=query,
                config=CONFIG._config,
                readarr_enabled=readarr_enabled or googlebooks_enabled
            )

        except Exception as e:
            logging.error(f"[SEARCH] error for '{query}': {str(e)}", exc_info=True)
            return render_template('error.html', error=str(e))

    @app.route('/add', methods=['POST'])
    @conditional_debug_log
    @requires_auth
    def add_to_arr():
        data = request.json
        media_type = data['media_type']
        media_id = data['media_id']

        if media_type == 'movie':
            success = utils.add_to_radarr(media_id)
            return jsonify({'success': success})
        elif media_type == 'book':
            success, message = utils.add_to_readarr(media_id)
            return jsonify({'success': success, 'message': message})
        else:
            success = utils.add_to_sonarr(media_id)
            return jsonify({'success': success})

    @app.route('/manage')
    @conditional_debug_log
    @requires_auth
    def manage_media():
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                movies_future = executor.submit(utils.get_radarr_movies)
                series_future = executor.submit(utils.get_sonarr_series)
                movies = movies_future.result()
                series = series_future.result()

            def _poster_url(images):
                """Return the first poster remoteUrl from an images list, or None."""
                for img in (images or []):
                    if img.get('coverType') == 'poster':
                        return img.get('remoteUrl') or img.get('url')
                return None

            def _slim_movie(m):
                poster = _poster_url(m.get('images', []))
                return {
                    'id':            m.get('id'),
                    'tmdbId':        m.get('tmdbId'),
                    'title':         m.get('title', ''),
                    'year':          m.get('year'),
                    'certification': m.get('certification'),
                    'runtime':       m.get('runtime'),
                    'hasFile':       bool(m.get('hasFile', False)),
                    'monitored':     bool(m.get('monitored', False)),
                    'images':        [{'coverType': 'poster', 'remoteUrl': poster}] if poster else [],
                    'media_type':    'movie',
                }

            def _slim_show(s):
                poster = _poster_url(s.get('images', []))
                stats  = s.get('statistics', {})
                return {
                    'id':            s.get('id'),
                    'tvdbId':        s.get('tvdbId'),
                    'title':         s.get('title', ''),
                    'year':          s.get('year'),
                    'certification': s.get('certification'),
                    'monitored':     bool(s.get('monitored', False)),
                    'statistics':    {
                        'seasonCount':      stats.get('seasonCount', 0),
                        'episodeCount':     stats.get('episodeCount', 0),
                        'episodeFileCount': stats.get('episodeFileCount', 0),
                    },
                    'images':        [{'coverType': 'poster', 'remoteUrl': poster}] if poster else [],
                    'media_type':    'tv',
                }

            combined_media = [_slim_movie(m) for m in movies] + [_slim_show(s) for s in series]
            combined_media.sort(key=lambda x: x.get('title', '').lower())

            return render_template(
                'manage.html',
                media=combined_media,
                config=CONFIG._config,
                readarr_enabled=CONFIG.readarr.enabled
            )
        except Exception as e:
            logging.error(f"Error fetching media: {str(e)}")
            return render_template('error.html', error="Failed to load media library")

    @app.route('/get_media_details')
    @conditional_debug_log
    @requires_auth
    def get_media_details():
        media_type = request.args.get('type')
        media_id = request.args.get('id')

        logging.info(f"Fetching details for {media_type} with ID: {media_id}")

        if media_type == 'movie':
            return jsonify(utils.get_radarr_details(media_id))
        elif media_type == 'book':
            return jsonify(utils.get_readarr_details(media_id))
        else:
            return jsonify(utils.get_sonarr_details(media_id))

    @app.route('/get_tmdb_details')
    @conditional_debug_log
    @requires_auth
    def get_tmdb_details():
        from utils import save_media_cache, load_media_cache, DISK_CACHE_TTL
        media_type = request.args.get('type')
        tmdb_id    = request.args.get('id')

        logging.info(f"Fetching TMDB details for type: {media_type}, ID: {tmdb_id}")

        if not media_type or not tmdb_id:
            return jsonify({'error': 'Missing type or ID'}), 400

        # TMDB details are static (poster, title, genres, trailer) — cache forever.
        cache_key = f"tmdb_{media_type}_{tmdb_id}"
        cached_data, _ = load_media_cache(cache_key)
        if cached_data is not None:
            return jsonify(cached_data)   # permanent cache — never re-fetch

        try:
            data = utils.get_tmdb_media_details(media_type, tmdb_id)
            save_media_cache(cache_key, data)
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    def get_ip_address():
        """Get the local IP address for network access"""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(('10.255.255.255', 1))
                ip_address = s.getsockname()[0]
        except Exception:
            ip_address = '127.0.0.1'
        return ip_address

    # Radarr and Sonarr routes
    @app.route('/api/radarr/rootfolders')
    @conditional_debug_log
    @requires_auth
    def get_radarr_rootfolders():
        """Get Radarr root folders"""
        try:
            url = f"{CONFIG.radarr.url}/api/v3/rootfolder"
            response = requests.get(url, params={'apikey': CONFIG.radarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Radarr root folders: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/radarr/qualityprofile')
    @conditional_debug_log
    @requires_auth
    def get_radarr_qualityprofile():
        """Get Radarr quality profiles"""
        try:
            url = f"{CONFIG.radarr.url}/api/v3/qualityprofile"
            response = requests.get(url, params={'apikey': CONFIG.radarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Radarr quality profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/sonarr/rootfolder')
    @conditional_debug_log
    @requires_auth
    def get_sonarr_rootfolder():
        """Get Sonarr root folders"""
        try:
            url = f"{CONFIG.sonarr.url}/api/v3/rootfolder"
            response = requests.get(url, params={'apikey': CONFIG.sonarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Sonarr root folders: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/sonarr/qualityprofile')
    @conditional_debug_log
    @requires_auth
    def get_sonarr_qualityprofile():
        """Get Sonarr quality profiles"""
        try:
            url = f"{CONFIG.sonarr.url}/api/v3/qualityprofile"
            response = requests.get(url, params={'apikey': CONFIG.sonarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Sonarr quality profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/sonarr/languageprofile')
    @conditional_debug_log
    @requires_auth
    def get_sonarr_languageprofile():
        """Get Sonarr language profiles"""
        try:
            url = f"{CONFIG.sonarr.url}/api/v3/languageprofile"
            response = requests.get(url, params={'apikey': CONFIG.sonarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Sonarr language profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    # ============ READARR API ROUTES ============

    @app.route('/api/readarr/rootfolders')
    @conditional_debug_log
    @requires_auth
    def get_readarr_rootfolders():
        """Get Readarr root folders"""
        try:
            url = f"{CONFIG.readarr.url}/api/v1/rootfolder"
            response = requests.get(url, params={'apikey': CONFIG.readarr.api_key}, timeout=10)
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Readarr root folders: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/readarr/qualityprofile')
    @conditional_debug_log
    @requires_auth
    def get_readarr_qualityprofile():
        """Get Readarr quality profiles"""
        try:
            url = f"{CONFIG.readarr.url}/api/v1/qualityprofile"
            response = requests.get(url, params={'apikey': CONFIG.readarr.api_key}, timeout=10)
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Readarr quality profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/readarr/metadataprofile')
    @conditional_debug_log
    @requires_auth
    def get_readarr_metadataprofile():
        """Get Readarr metadata profiles"""
        try:
            url = f"{CONFIG.readarr.url}/api/v1/metadataprofile"
            response = requests.get(url, params={'apikey': CONFIG.readarr.api_key}, timeout=10)
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Readarr metadata profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/readarr/test')
    @conditional_debug_log
    @requires_auth
    def test_readarr_connection():
        """Test Readarr connection"""
        try:
            url = f"{CONFIG.readarr.url}/api/v1/system/status"
            response = requests.get(url, params={'apikey': CONFIG.readarr.api_key}, timeout=10)
            if response.status_code == 200:
                return jsonify({'success': True, 'status': response.json()})
            return jsonify({'success': False, 'error': f'HTTP {response.status_code}'}), response.status_code
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/book/metadata-cache')
    @requires_auth
    def book_metadata_cache():
        """Return locally-cached author / poster data for a list of foreignBookIds.

        Query string: ?ids=id1,id2,id3,...
        Response: { foreignBookId: { authorName, posterUrl, title, overview } }

        Fast: reads only disk-cached JSON files, no Readarr/Apify HTTP calls.
        Used by manage-books.html to batch-patch cards on first load.
        """
        from utils import load_book_metadata
        raw_ids = request.args.get('ids', '')
        ids = [i.strip() for i in raw_ids.split(',') if i.strip()]
        result = {}
        for fid in ids:
            cached = load_book_metadata(fid)
            if not cached:
                continue
            author_obj  = cached.get('author') or {}
            author_name = (
                author_obj.get('authorName', '')
                if isinstance(author_obj, dict)
                else str(author_obj)
            )
            # Resolve poster URL: remotePoster > images[coverType=poster/cover]
            poster_url = cached.get('remotePoster', '')
            if not poster_url:
                for img in cached.get('images', []):
                    if img.get('coverType') in ('poster', 'cover'):
                        poster_url = img.get('remoteUrl') or img.get('url', '')
                        if poster_url:
                            break
            # Only return entries that actually have something useful
            if author_name or poster_url:
                result[fid] = {
                    'authorName': author_name,
                    'posterUrl':  poster_url,
                    'title':      cached.get('title', ''),
                    'overview':   cached.get('overview', ''),
                }
        return jsonify(result)

    # ── Local book DB API ──────────────────────────────────────────────────────

    # Thumbnail disk-cache directory — lives next to books.db
    _THUMB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'metadata', 'thumb_cache')

    def _bust_thumb_cache(book_id):
        """Delete all cached thumbnail files for a given book_id.

        Called whenever the cover_url is updated so stale resized images
        don't persist in the cache.
        """
        import glob as _glob
        for f in _glob.glob(os.path.join(_THUMB_DIR, f'{book_id}_*.jpg')):
            try:
                os.remove(f)
            except OSError:
                pass

    def _enrichment_match_score(result, title, author):
        """Return a fuzzy title/author match score for an online book result."""
        import difflib

        def _norm(s):
            return (s or '').lower().strip()

        title_n  = _norm(title)
        author_n = _norm(author)

        r_title = _norm(result.get('title', ''))
        r_auth_raw = result.get('author') or {}
        if isinstance(r_auth_raw, dict):
            r_author = _norm(r_auth_raw.get('authorName', ''))
        else:
            r_author = _norm(str(r_auth_raw))

        t_score = (difflib.SequenceMatcher(None, title_n, r_title).ratio()
                   if title_n else 0.5)
        a_score = (difflib.SequenceMatcher(None, author_n, r_author).ratio()
                   if author_n else 0.5)
        score = (a_score * 0.6) + (t_score * 0.4)
        logging.debug("[enrichment_match] '%s' / '%s' → score %.3f", r_title, r_author, score)
        return score

    def _best_enrichment_match(results, title, author):
        """Return the best-matching result from `results` using fuzzy title+author comparison.

        Scoring: author match weighted 0.6, title match weighted 0.4.
        Minimum combined score to accept a result: 0.35.
        Returns None if no result clears the threshold.
        """
        best_score = 0.0
        best_result = None

        for r in results:
            score = _enrichment_match_score(r, title, author)
            if score > best_score:
                best_score = score
                best_result = r

        if best_score >= 0.35:
            return best_result
        logging.debug("[enrichment_match] best score %.3f below threshold — no match", best_score)
        return None

    @app.route('/api/book/cover/<int:book_id>')
    @requires_auth
    def book_cover(book_id):
        try:
            w = int(request.args.get('w', 60))
            h = int(request.args.get('h', 90))

            # ── Cache hit? ─────────────────────────────────────────────────────
            # Cache key encodes book id + requested dimensions.
            # If the cover_url changes (re-enrichment), the caller should DELETE
            # the cached file or the whole thumb_cache dir to force a refresh.
            cache_file = os.path.join(_THUMB_DIR, f'{book_id}_{w}x{h}.jpg')
            if os.path.isfile(cache_file):
                logging.debug(f'[book_cover] HIT  book_{book_id}_{w}x{h}.jpg')
                resp = send_file(cache_file, mimetype='image/jpeg')
                resp.headers['Cache-Control'] = 'public, max-age=604800'  # 7 days
                return resp

            # ── Cache miss — resolve cover URL ─────────────────────────────────
            logging.info(f'[book_cover] MISS book_id={book_id} ({w}×{h}px) — resolving cover')
            # Priority 1: local DB cover_url (set by enrichment or manual import)
            book = books_db.get_book_by_id(book_id)
            cover_url = book.get('cover_url') if book else None

            # Priority 2: Readarr API (covers stored in Readarr's mediacover cache)
            if not cover_url and CONFIG.readarr.enabled:
                try:
                    resp = requests.get(
                        f"{CONFIG.readarr.url}/api/v1/book/{book_id}",
                        params={'apikey': CONFIG.readarr.api_key}, timeout=8
                    )
                    if resp.status_code == 200:
                        rbook = resp.json()
                        cover_url = rbook.get('remotePoster') or next((
                            img.get('remoteUrl') or img.get('url')
                            for img in rbook.get('images', [])
                            if img.get('coverType') in ('poster', 'cover')
                        ), None)
                except Exception as e:
                    logging.debug(f"[book_cover] Readarr fallback failed: {e}")

            if not cover_url:
                logging.debug(f"[book_cover] no cover found for book_id={book_id}")
                return '', 404

            # ── Priority 0: local cover file (uploaded via UI) ─────────────────
            if os.path.isabs(cover_url) and os.path.isfile(cover_url):
                try:
                    img = Image.open(cover_url).convert('RGB')
                    img.thumbnail((w, h), Image.LANCZOS)
                    os.makedirs(_THUMB_DIR, exist_ok=True)
                    tmp = cache_file + '.tmp'
                    img.save(tmp, format='JPEG', quality=72, optimize=True)
                    os.replace(tmp, cache_file)
                    response = send_file(cache_file, mimetype='image/jpeg')
                    response.headers['Cache-Control'] = 'public, max-age=604800'
                    return response
                except Exception as exc:
                    logging.warning(f"[book_cover] local file read failed book_id={book_id}: {exc}")
                    return '', 404

            # ── Fetch remote image ─────────────────────────────────────────────
            if cover_url.startswith('/'):
                img_resp = requests.get(
                    CONFIG.readarr.url.rstrip('/') + cover_url,
                    params={'apikey': CONFIG.readarr.api_key}, timeout=8
                )
            else:
                img_resp = requests.get(cover_url, timeout=8)

            if img_resp.status_code != 200:
                return '', 404

            # ── Resize + write to disk cache ───────────────────────────────────
            try:
                img = Image.open(io.BytesIO(img_resp.content)).convert('RGB')
                img.thumbnail((w, h), Image.LANCZOS)
                os.makedirs(_THUMB_DIR, exist_ok=True)
                tmp = cache_file + '.tmp'
                img.save(tmp, format='JPEG', quality=72, optimize=True)
                os.replace(tmp, cache_file)
                logging.info(f'[book_cover] SAVE book_{book_id}_{w}x{h}.jpg')
                response = send_file(cache_file, mimetype='image/jpeg')
            except Exception as exc:
                # Pillow failed (corrupt image, etc.) — stream raw bytes, don't cache
                logging.warning(f"[book_cover] resize failed for book_id={book_id}: {exc}")
                response = Response(img_resp.content,
                                    content_type=img_resp.headers.get('content-type', 'image/jpeg'))

            response.headers['Cache-Control'] = 'public, max-age=604800'  # 7 days
            return response

        except Exception as e:
            logging.error(f"[book_cover] Error for book_id={book_id}: {e}", exc_info=True)
            return '', 404
            
    @app.route('/api/books/enrich', methods=['POST'])
    @requires_auth
    def books_enrich():
        """Enrich a single book: Goodreads → Readarr.

        Request JSON: { file_path, title, author }
        Response:     { status: 'ok'|'needs_manual', book: {...} }
        """
        data      = request.get_json(force=True, silent=True) or {}
        file_path = data.get('file_path', '').strip()
        title     = data.get('title', '').strip()
        author    = data.get('author', '').strip()

        if not file_path:
            return jsonify({'error': 'file_path required'}), 400

        query = f"{title} {author}".strip() or os.path.splitext(
            os.path.basename(file_path))[0]

        # ── 1. Google Books ────────────────────────────────────────────────────
        gb_result = None
        if CONFIG.google_books.enabled and query:
            try:
                results = utils.search_google_books(query)
                if results:
                    gb_result = _best_enrichment_match(results, title, author)
                    if gb_result is None:
                        logging.info("[books/enrich] Google Books results present but no confident match for '%s'", query)
            except Exception as e:
                logging.warning("[books/enrich] Google Books error: %s", e)

        if gb_result:
            _gb_genres = gb_result.get('genres') or []
            _gb_genre  = ', '.join(_gb_genres[:3]) if _gb_genres else None
            book = books_db.save_book({
                'file_path':   file_path,
                'title':       gb_result.get('title') or title,
                'author':      (gb_result.get('author', {}) or {}).get('authorName') or author,
                'cover_url':   gb_result.get('remotePoster') or gb_result.get('cover_url'),
                'overview':    gb_result.get('overview'),
                'year':        gb_result.get('year'),
                'pages':       gb_result.get('pageCount'),
                'isbn':        gb_result.get('isbn'),
                'genre':       _gb_genre,
                'source':      'google_books',
            })
            if book and book.get('id'):
                _bust_thumb_cache(book['id'])
            return jsonify({'status': 'ok', 'book': book})

        # ── 2. Readarr ─────────────────────────────────────────────────────────
        readarr_result = None
        if CONFIG.readarr.enabled and query:
            try:
                results = utils.search_readarr(query)
                if results:
                    readarr_result = _best_enrichment_match(results, title, author)
                    if readarr_result is None:
                        logging.info("[books/enrich] Readarr results present but no confident match for '%s'", query)
            except Exception as e:
                logging.warning("[books/enrich] Readarr error: %s", e)

        if readarr_result:
            author_obj = readarr_result.get('author') or {}
            author_name = (author_obj.get('authorName') if isinstance(author_obj, dict)
                           else str(author_obj)) or author
            images = readarr_result.get('images') or []
            cover_url = next(
                (img.get('remoteUrl') or img.get('url')
                 for img in images
                 if img.get('coverType') in ('poster', 'cover')),
                None
            )
            _ra_genres = readarr_result.get('genres') or []
            _ra_genre  = ', '.join(_ra_genres[:3]) if _ra_genres else None
            book = books_db.save_book({
                'file_path':      file_path,
                'title':          readarr_result.get('title') or title,
                'author':         author_name,
                'cover_url':      cover_url,
                'overview':       readarr_result.get('overview'),
                'year':           (readarr_result.get('releaseDate') or '')[:4] or None,
                'pages':          readarr_result.get('pageCount'),
                'genre':          _ra_genre,
                'foreign_book_id': str(readarr_result.get('foreignBookId', '')),
                'source':         'readarr',
            })
            if book and book.get('id'):
                _bust_thumb_cache(book['id'])
            return jsonify({'status': 'ok', 'book': book})

        # ── 3. Nothing found — caller should show manual import ────────────────
        # Bust the thumb cache so any stale thumbnail from a previous wrong
        # enrichment doesn't keep appearing on the card.
        existing = books_db.get_book_by_path(file_path)
        book_id  = existing['id'] if existing else None
        if book_id:
            _bust_thumb_cache(book_id)
        return jsonify({'status': 'needs_manual', 'book_id': book_id})

    @app.route('/api/books/file-metadata')
    @requires_auth
    def books_file_metadata():
        """Extract and return raw metadata from a book file.

        Used to pre-populate the manual import dialog.
        Query: ?path=<absolute_file_path>
        """
        from utils import extract_file_metadata, _title_from_filename
        file_path = request.args.get('path', '').strip()
        if not file_path or not os.path.isfile(file_path):
            return jsonify({'error': 'File not found'}), 404

        # Validate path is within the configured root folder
        root = CONFIG.readarr.root_folder if CONFIG.readarr.enabled else ''
        if root:
            try:
                os.path.commonpath([root, file_path])
                if not os.path.abspath(file_path).startswith(
                        os.path.abspath(root)):
                    return jsonify({'error': 'Path outside root folder'}), 403
            except Exception:
                return jsonify({'error': 'Invalid path'}), 400

        meta = extract_file_metadata(file_path)
        filename = os.path.basename(file_path)
        meta.setdefault('title', _title_from_filename(filename))
        meta.pop('cover_data', None)   # don't send binary over JSON
        meta['filename']  = filename
        meta['file_path'] = file_path
        meta['extension'] = os.path.splitext(filename)[1].lower()
        return jsonify(meta)

    @app.route('/api/books/save-metadata', methods=['POST'])
    @requires_auth
    def books_save_metadata():
        """Save (or overwrite) book metadata to the local DB.

        Used by the manual import dialog and the enrichment chain.
        Request JSON: { file_path, title, author, cover_url, overview,
                        year, pages, isbn, goodreads_id, ... }
        """
        data = request.get_json(force=True, silent=True) or {}
        if not data.get('file_path'):
            return jsonify({'error': 'file_path required'}), 400

        # Force source='manual' when called from the UI dialog
        if not data.get('source'):
            data['source'] = 'manual'

        try:
            book = books_db.save_book(data)
            # Always bust thumb cache — the caller may have changed the cover
            # URL or any metadata that affects rendering, and stale thumbnails
            # would otherwise persist until the next server-side cache miss.
            if book and book.get('id'):
                _bust_thumb_cache(book['id'])
            return jsonify({'success': True, 'book': book})
        except Exception as e:
            logging.error("[books/save-metadata] error: %s", e)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/books/local/<int:db_id>')
    @requires_auth
    def books_get_local(db_id):
        """Return a single book record from the local DB by integer id."""
        book = books_db.get_book_by_id(db_id)
        if not book:
            return jsonify({'error': 'not found'}), 404
        return jsonify(book)

    @app.route('/api/books/update', methods=['POST'])
    @requires_auth
    def books_update():
        """Patch reading_status or is_wishlist (or both) for a book.

        Request JSON: { db_id: int, reading_status?: str, is_wishlist?: 0|1 }
        reading_status values: 'not_started' | 'reading' | 'complete' | 'dnf'
        """
        data = request.get_json(force=True, silent=True) or {}
        db_id = data.get('db_id')
        if not db_id:
            return jsonify({'error': 'db_id required'}), 400

        book = books_db.get_book_by_id(int(db_id))
        if not book:
            return jsonify({'error': 'book not found'}), 404

        update = {'file_path': book['file_path']}
        VALID_STATUSES = {'not_started', 'reading', 'complete', 'dnf'}
        if 'reading_status' in data:
            if data['reading_status'] not in VALID_STATUSES:
                return jsonify({'error': 'invalid reading_status'}), 400
            update['reading_status'] = data['reading_status']
        if 'is_wishlist' in data:
            update['is_wishlist'] = 1 if data['is_wishlist'] else 0

        try:
            updated = books_db.save_book(update)
            return jsonify({'success': True, 'book': updated})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── Cover management ──────────────────────────────────────────────────────

    # Directory for user-uploaded full-res covers
    _COVERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'metadata', 'covers')

    @app.route('/api/books/covers/clear-cache', methods=['POST'])
    @requires_auth
    def clear_thumb_cache():
        """Delete all cached thumbnail files so they regenerate on next request."""
        import glob as _glob
        deleted = 0
        for f in _glob.glob(os.path.join(_THUMB_DIR, '*.jpg')):
            try:
                os.remove(f)
                deleted += 1
            except OSError:
                pass
        logging.info('[thumb_cache] Cleared %d cached thumbnail files', deleted)
        return jsonify({'success': True, 'deleted': deleted})

    @app.route('/api/books/cover/<int:db_id>', methods=['DELETE'])
    @requires_auth
    def delete_book_cover(db_id):
        """Remove the cover image for a local book.

        Clears cover_url in DB, deletes the uploaded cover file (if local),
        and busts the thumbnail cache.
        """
        book = books_db.get_book_by_id(db_id)
        if not book:
            return jsonify({'error': 'not found'}), 404

        cover_url = book.get('cover_url') or ''
        # Delete local cover file if one was uploaded
        if os.path.isabs(cover_url) and os.path.isfile(cover_url):
            try:
                os.remove(cover_url)
            except OSError as e:
                logging.warning(f"[delete_cover] could not delete file {cover_url}: {e}")

        # Directly NULL the cover_url column — can't use save_book() here because
        # it skips None values (they mean "don't touch this field" in that API).
        from datetime import datetime as _dt
        with books_db._connect() as conn:
            conn.execute(
                'UPDATE books SET cover_url = NULL, updated_at = ? WHERE id = ?',
                (_dt.utcnow().isoformat(), db_id)
            )
            conn.commit()
        _bust_thumb_cache(db_id)
        updated = books_db.get_book_by_id(db_id)
        return jsonify({'success': True, 'book': updated})

    @app.route('/api/books/cover/upload/<int:db_id>', methods=['POST'])
    @requires_auth
    def upload_book_cover(db_id):
        """Upload a local image file as the book cover.

        Resizes to a maximum of 400×600 px (preserving aspect ratio),
        saves to metadata/covers/<db_id>.jpg, stores the absolute path
        in the DB's cover_url, and busts the thumbnail cache.
        """
        book = books_db.get_book_by_id(db_id)
        if not book:
            return jsonify({'error': 'not found'}), 404

        if 'cover' not in request.files:
            return jsonify({'error': 'No file field named "cover"'}), 400
        f = request.files['cover']
        if not f or not f.filename:
            return jsonify({'error': 'Empty file'}), 400

        os.makedirs(_COVERS_DIR, exist_ok=True)
        cover_path = os.path.join(_COVERS_DIR, f'{db_id}.jpg')
        try:
            img = Image.open(f.stream).convert('RGB')
            img.thumbnail((400, 600), Image.LANCZOS)
            tmp = cover_path + '.tmp'
            img.save(tmp, format='JPEG', quality=85, optimize=True)
            os.replace(tmp, cover_path)
        except Exception as exc:
            return jsonify({'error': f'Image processing failed: {exc}'}), 400

        updated = books_db.save_book({'file_path': book['file_path'], 'cover_url': cover_path})
        _bust_thumb_cache(db_id)
        return jsonify({'success': True, 'book': updated})

    @app.route('/api/books/refresh/<int:db_id>', methods=['POST'])
    @requires_auth
    def refresh_book_metadata(db_id):
        """Re-fetch metadata (including cover and genre) from Goodreads or Readarr.

        Uses the book's existing title + author as the search query.
        Response: { status: 'ok'|'no_match', book: {...} }
        """
        book = books_db.get_book_by_id(db_id)
        if not book:
            return jsonify({'error': 'not found'}), 404

        req_data      = request.get_json(force=True, silent=True) or {}
        goodreads_url = (req_data.get('goodreads_url') or '').strip()

        title  = book.get('title', '')
        author = book.get('author', '')

        # ── Extract hint from a Goodreads URL if provided ─────────────────────
        # URL form: https://www.goodreads.com/en/book/show/12345-slug-title
        # or        https://www.goodreads.com/book/show/12345-slug-title
        import re as _re
        _gr_id_from_url   = None
        _title_from_slug  = None
        if goodreads_url:
            _id_m = _re.search(r'/show/(\d+)', goodreads_url)
            if _id_m:
                _gr_id_from_url = _id_m.group(1)
            _slug_m = _re.search(r'/show/\d+[-/](.+?)(?:\?|$)', goodreads_url)
            if _slug_m:
                _title_from_slug = _slug_m.group(1).replace('-', ' ').strip()
                logging.info("[books/refresh] URL slug title: '%s', GR id: %s",
                             _title_from_slug, _gr_id_from_url)

        # Build the search query — prefer URL-derived slug title for better matching
        search_title = _title_from_slug or title
        query        = f"{search_title} {author}".strip()

        # ── Google Books ───────────────────────────────────────────────────────
        if CONFIG.google_books.enabled and query:
            try:
                results = utils.search_google_books(query)
                if results:
                    r = _best_enrichment_match(results, search_title, author)
                    if r is not None:
                        _genres  = r.get('genres') or []
                        _genre   = ', '.join(_genres[:3]) if _genres else None
                        updated  = books_db.save_book({
                            'file_path':  book['file_path'],
                            'title':      r.get('title') or title,
                            'author':     (r.get('author', {}) or {}).get('authorName') or author,
                            'cover_url':  r.get('remotePoster') or r.get('cover_url'),
                            'overview':   r.get('overview'),
                            'year':       r.get('year'),
                            'pages':      r.get('pageCount'),
                            'isbn':       r.get('isbn'),
                            'genre':      _genre,
                            'source':     'google_books',
                        })
                        if updated and updated.get('id'):
                            _bust_thumb_cache(updated['id'])
                        return jsonify({'status': 'ok', 'book': updated})
            except Exception as e:
                logging.warning("[books/refresh] Google Books error: %s", e)

        # ── Readarr ────────────────────────────────────────────────────────────
        if CONFIG.readarr.enabled and query:
            try:
                results = utils.search_readarr(query)
                if results:
                    r = _best_enrichment_match(results, search_title, author)
                    if r is not None:
                        author_obj  = r.get('author') or {}
                        author_name = (author_obj.get('authorName') if isinstance(author_obj, dict)
                                       else str(author_obj)) or author
                        images    = r.get('images') or []
                        cover_url = next(
                            (img.get('remoteUrl') or img.get('url')
                             for img in images
                             if img.get('coverType') in ('poster', 'cover')),
                            None
                        )
                        _genres  = r.get('genres') or []
                        _genre   = ', '.join(_genres[:3]) if _genres else None
                        updated  = books_db.save_book({
                            'file_path':       book['file_path'],
                            'title':           r.get('title') or title,
                            'author':          author_name,
                            'cover_url':       cover_url,
                            'overview':        r.get('overview'),
                            'year':            (r.get('releaseDate') or '')[:4] or None,
                            'pages':           r.get('pageCount'),
                            'genre':           _genre,
                            'foreign_book_id': str(r.get('foreignBookId', '')),
                            'source':          'readarr',
                        })
                        if updated and updated.get('id'):
                            _bust_thumb_cache(updated['id'])
                        return jsonify({'status': 'ok', 'book': updated})
            except Exception as e:
                logging.warning("[books/refresh] Readarr error: %s", e)

        return jsonify({'status': 'no_match', 'message': 'No matching book found online'})

    @app.route('/api/books/search-online/<int:db_id>', methods=['POST'])
    @requires_auth
    def search_online_all(db_id):
        """Return ALL search results from Google Books + Readarr for the user to pick from.

        Response: { results: [ { source, title, author, year, pages, cover_url,
                                  overview, genres, isbn, foreign_book_id } ] }
        """
        book = books_db.get_book_by_id(db_id)
        if not book:
            return jsonify({'error': 'not found'}), 404

        req_data = request.get_json(force=True, silent=True) or {}
        override_query = (req_data.get('query') or '').strip()
        req_title = (req_data.get('title') or '').strip()
        req_author = (req_data.get('author') or '').strip()
        goodreads_url = (req_data.get('goodreads_url') or '').strip()

        title = req_title or book.get('title', '')
        author = req_author or book.get('author', '')

        import re as _re
        slug_title = ''
        if goodreads_url:
            _slug_m = _re.search(r'/show/\d+[-/](.+?)(?:\?|$)', goodreads_url)
            if _slug_m:
                slug_title = _slug_m.group(1).replace('-', ' ').strip()

        search_title = slug_title or title
        query = override_query or f"{search_title} {author}".strip()

        all_results = []

        # ── Google Books ───────────────────────────────────────────────────────
        if CONFIG.google_books.enabled and query:
            try:
                gb_results = utils.search_google_books(query, max_items=8)
                for r in gb_results:
                    _genres = r.get('genres') or []
                    all_results.append({
                        'source':          'Google Books',
                        'source_key':      'google_books',
                        'title':           r.get('title') or '',
                        'author':          (r.get('author') or {}).get('authorName') or '',
                        'year':            r.get('year') or '',
                        'pages':           r.get('pageCount') or 0,
                        'cover_url':       r.get('cover_url') or r.get('remotePoster') or '',
                        'overview':        r.get('overview') or '',
                        'genres':          _genres,
                        'genre_str':       ', '.join(_genres[:3]) if _genres else '',
                        'isbn':            r.get('isbn') or '',
                        'foreign_book_id': r.get('foreignBookId') or '',
                    })
            except Exception as e:
                logging.warning("[search_online_all] Google Books error: %s", e)

        # ── Readarr ────────────────────────────────────────────────────────────
        if CONFIG.readarr.enabled and query:
            try:
                ra_results = utils.search_readarr(query)
                for r in (ra_results or [])[:8]:
                    author_obj  = r.get('author') or {}
                    author_name = (author_obj.get('authorName') if isinstance(author_obj, dict)
                                   else str(author_obj)) or ''
                    images    = r.get('images') or []
                    cover_url = next(
                        (img.get('remoteUrl') or img.get('url')
                         for img in images
                         if img.get('coverType') in ('poster', 'cover')),
                        r.get('remotePoster') or ''
                    )
                    _genres = r.get('genres') or []
                    all_results.append({
                        'source':          'Readarr',
                        'source_key':      'readarr',
                        'title':           r.get('title') or '',
                        'author':          author_name,
                        'year':            (r.get('releaseDate') or '')[:4] or '',
                        'pages':           r.get('pageCount') or 0,
                        'cover_url':       cover_url,
                        'overview':        r.get('overview') or '',
                        'genres':          _genres,
                        'genre_str':       ', '.join(_genres[:3]) if _genres else '',
                        'isbn':            r.get('isbn') or '',
                        'foreign_book_id': str(r.get('foreignBookId') or ''),
                    })
            except Exception as e:
                logging.warning("[search_online_all] Readarr error: %s", e)

        for result in all_results:
            result['_score'] = _enrichment_match_score(
                {
                    'title': result.get('title'),
                    'author': {'authorName': result.get('author', '')},
                },
                search_title,
                author,
            )
        all_results.sort(key=lambda r: (r.get('_score', 0), r.get('source_key') == 'readarr'), reverse=True)
        for result in all_results:
            result.pop('_score', None)

        return jsonify({'results': all_results})

    # ── Reader route for local (non-Readarr) books ─────────────────────────────

    @app.route('/read/local/<int:db_id>')
    @requires_auth
    def read_local_book(db_id):
        """Open the reader for a book identified by its local DB id."""
        if is_kindle_request():
            return redirect(url_for('kindle_book_detail', db_id=db_id))

        book = books_db.get_book_by_id(db_id)
        if not book or not book.get('file_path'):
            return render_template('error.html', error='Book not found in library.'), 404
        file_path = book['file_path']
        if not os.path.isfile(file_path):
            return render_template('error.html',
                                   error=f'File not found on disk: {os.path.basename(file_path)}'), 404
        ext = os.path.splitext(file_path)[1].lower()
        file_type = 'epub' if ext == '.epub' else 'pdf' if ext == '.pdf' else None
        if not file_type:
            # AZW3 / MOBI / etc. — not browser-readable; send to Kindle page instead
            return redirect(url_for('kindle_book_detail', db_id=db_id))
        return render_template('reader.html', book_id=f'local_{db_id}', file_type=file_type, config=CONFIG._config)

    @app.route('/api/book/file/local/<int:db_id>')
    @requires_auth
    def book_file_local(db_id):
        """Stream a book file by local DB id (for the reader)."""
        logging.info('[KindleLog] /api/book/file/local/%s | UA=%s | Range=%s',
                     db_id,
                     request.headers.get('User-Agent', '—'),
                     request.headers.get('Range', '—'))
        book = books_db.get_book_by_id(db_id)
        if not book or not book.get('file_path'):
            logging.warning('[KindleLog] book_file_local/%s — DB record not found', db_id)
            return jsonify({'error': 'Not found'}), 404
        file_path = book['file_path']
        if not os.path.isfile(file_path):
            logging.warning('[KindleLog] book_file_local/%s — file missing: %s', db_id, file_path)
            return jsonify({'error': 'File not found on disk'}), 404
        ext  = os.path.splitext(file_path)[1].lower()
        mime = 'application/epub+zip' if ext == '.epub' else 'application/pdf'
        file_size = os.path.getsize(file_path)
        logging.info('[KindleLog] book_file_local/%s — streaming %s (%s bytes, mime=%s)',
                     db_id, file_path, file_size, mime)
        try:
            resp = send_file(file_path, mimetype=mime,
                             as_attachment=False, conditional=False)
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Cache-Control'] = 'no-store'
            return resp
        except Exception as e:
            logging.error('[KindleLog] book_file_local/%s — send_file error: %s', db_id, e)
            return jsonify({'error': str(e)}), 500

    # ── General image proxy with disk cache ───────────────────────────────────
    _IMG_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'metadata', 'img_cache')

    @app.route('/api/img')
    @requires_auth
    def img_proxy():
        """Caching image proxy — redirect-on-miss with background fetch.

        Cache HIT  → served from disk instantly, no outbound request.
        Cache MISS → browser redirected to the optimised source URL immediately;
                     a daemon thread fetches, resizes and writes to disk so the
                     next request is always a hit.

        All events logged at INFO with the item title so addarr.log is readable.
        """
        import hashlib, threading

        title = request.args.get('t', '')       # human-readable label for logs
        url   = request.args.get('url', '').strip()
        try:
            w = min(int(request.args.get('w', 174)), 800)
            h = min(int(request.args.get('h', 261)), 1200)
        except (ValueError, TypeError):
            w, h = 174, 261

        label = f'"{title}"' if title else url[:60]

        try:
            if not url or not url.startswith('http'):
                logging.warning(f'[img_proxy] Bad URL for {label}: {url!r}')
                return '', 400

            # Normalise all TMDB size variants → /w342/ before fetching
            norm_url   = re.sub(r'(image\.tmdb\.org/t/p/)[^/]+/', r'\1w342/', url)
            cache_key  = hashlib.md5(norm_url.encode()).hexdigest()[:12]
            cache_file = os.path.join(_IMG_CACHE_DIR, f'{cache_key}_{w}x{h}.jpg')

            # ── Cache hit: serve from disk ─────────────────────────────────────
            if os.path.isfile(cache_file):
                logging.info(f'[img_proxy] HIT  {label} — serving from cache')
                resp = send_file(cache_file, mimetype='image/jpeg')
                resp.headers['Cache-Control'] = 'public, max-age=604800'
                return resp

            # ── Cache miss: redirect browser; fetch+save in background ─────────
            logging.info(f'[img_proxy] MISS {label} — redirecting to source, caching in background')

            def _fetch_and_cache(fetch_url, dest, tw, th, name):
                try:
                    r = requests.get(fetch_url, timeout=15,
                                     headers={'User-Agent': 'addarr/1.0'})
                    if r.status_code != 200:
                        logging.warning(f'[img_proxy] Fetch failed {name!r}: HTTP {r.status_code}')
                        return
                    img = Image.open(io.BytesIO(r.content)).convert('RGB')
                    img.thumbnail((tw, th), Image.LANCZOS)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    tmp = dest + '.tmp'
                    img.save(tmp, format='JPEG', quality=75, optimize=True)
                    os.replace(tmp, dest)
                    logging.info(f'[img_proxy] SAVE {name!r} → cache updated ({tw}×{th}px)')
                except Exception as exc:
                    logging.warning(f'[img_proxy] Cache error {name!r}: {exc}')

            threading.Thread(
                target=_fetch_and_cache,
                args=(norm_url, cache_file, w, h, title or url[:60]),
                daemon=True,
                name=f'img-{cache_key}'
            ).start()

            return redirect(norm_url, 302)

        except Exception as exc:
            logging.error(f'[img_proxy] CRASH for {label}: {exc}', exc_info=True)
            return '', 500

    @app.route('/api/readarr/cover')
    @requires_auth
    def readarr_cover_proxy():
        """Proxy a Readarr mediacover image so the browser doesn't need direct
        access to the Readarr host (which may be localhost or an internal address).
        Usage: /api/readarr/cover?path=/api/v1/mediacover/39/cover.jpg?lastWrite=...
        """
        path = request.args.get('path', '')
        if not path or '/mediacover' not in path:
            return '', 404
        try:
            # Strip the leading /api/v1 prefix — requests wants the full URL
            readarr_url = CONFIG.readarr.url.rstrip('/')
            full_url = readarr_url + path
            r = requests.get(full_url, params={'apikey': CONFIG.readarr.api_key},
                             timeout=10, stream=False)
            if r.status_code == 200:
                content_type = r.headers.get('content-type', 'image/jpeg')
                return Response(r.content, content_type=content_type)
            return '', r.status_code
        except Exception as e:
            logging.debug(f"[cover proxy] {e}")
            return '', 500

    # ============ LINKS PAGE ============

    @app.route('/links')
    @conditional_debug_log
    @requires_auth
    def links_page():
        """Service links dashboard"""
        try:
            return render_template('links.html', config=CONFIG._config)
        except Exception as e:
            logging.error(f"Error loading links page: {str(e)}")
            return render_template('error.html', error="Failed to load links page")

    @app.route('/api/links/services')
    @conditional_debug_log
    @requires_auth
    def get_links_services():
        """Return service URLs and network info for the links page"""
        try:
            from urllib.parse import urlparse
            net = network_info_func() if network_info_func else {}
            local_ip = net.get('local_ip', '127.0.0.1')
            tunnel_url = net.get('tunnel_url', '') or ''
            tunnel_enabled = CONFIG.tunnel.enabled
            tunnel_active = net.get('tunnel_active', False)

            # Extract Pinggy hostname/scheme for per-service URL substitution
            pinggy_host = ''
            pinggy_scheme = 'https'
            if tunnel_url:
                try:
                    p = urlparse(tunnel_url)
                    pinggy_host = p.netloc   # e.g. abc.a.pinggy.io
                    pinggy_scheme = p.scheme  # https
                except Exception:
                    pass

            def make_urls(svc_url):
                """Return the configured service URL as 'local'.
                   Pinggy only tunnels Addarr's own port — individual service ports
                   are NOT forwarded, so no Pinggy URL is provided for services.
                   If the URL uses 'localhost' or '127.0.0.1', substitute the LAN IP
                   so the link is reachable from the same device that opened the page.
                """
                if not svc_url:
                    return {'local': '', 'pinggy': ''}
                try:
                    parsed = urlparse(svc_url)
                    host = parsed.hostname or 'localhost'
                    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
                    scheme = parsed.scheme or 'http'
                    # Replace loopback address with the actual LAN IP so the
                    # link works when opened from a browser on the same machine.
                    if host in ('localhost', '127.0.0.1', '::1'):
                        host = local_ip
                    local = f"{scheme}://{host}:{port}"
                    return {'local': local, 'pinggy': ''}
                except Exception:
                    return {'local': svc_url, 'pinggy': ''}

            services = [
                {
                    'name': 'Radarr',
                    'icon': 'fas fa-film',
                    'color': '#6ab759',
                    'configured': bool(CONFIG.radarr.url),
                    **make_urls(CONFIG.radarr.url)
                },
                {
                    'name': 'Sonarr',
                    'icon': 'fas fa-tv',
                    'color': '#35c5f4',
                    'configured': bool(CONFIG.sonarr.url),
                    **make_urls(CONFIG.sonarr.url)
                },
                {
                    'name': 'Readarr',
                    'icon': 'fas fa-book',
                    'color': '#c0392b',
                    'configured': bool(CONFIG.readarr.url),
                    **make_urls(CONFIG.readarr.url)
                },
                {
                    'name': 'Prowlarr',
                    'icon': 'fas fa-search',
                    'color': '#ff6b35',
                    'configured': bool(CONFIG.prowlarr.url),
                    **make_urls(CONFIG.prowlarr.url)
                },
            ]

            return jsonify({
                'services': services,
                'tunnel_enabled': tunnel_enabled,
                'tunnel_active': tunnel_active,
                'tunnel_url': tunnel_url,
                'local_ip': local_ip
            })
        except Exception as e:
            logging.error(f"Error building links services: {str(e)}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/library/batch-status')
    @requires_auth
    def library_batch_status():
        """Return library status for multiple items in one round trip.

        Query params:
          movie_ids  — comma-separated TMDB IDs
          tv_ids     — comma-separated TMDB IDs (Sonarr uses tmdbId for lookup)

        Response shape:
        {
          "movie": { "<tmdbId>": { "in_library": bool, "hasFile": bool,
                                   "internalId": int, "monitored": bool,
                                   "remotePoster": str, "title": str } },
          "tv":    { "<tmdbId>": { "in_library": bool, "statistics": {},
                                   "internalId": int, "monitored": bool,
                                   "remotePoster": str, "title": str } }
        }
        """
        result = {'movie': {}, 'tv': {}}

        movie_ids = [i.strip() for i in request.args.get('movie_ids', '').split(',') if i.strip()]
        tv_ids    = [i.strip() for i in request.args.get('tv_ids',    '').split(',') if i.strip()]

        if movie_ids:
            movies   = get_cached_library('movie')
            by_tmdb  = {str(m.get('tmdbId', '')): m for m in movies}
            for mid in movie_ids:
                m = by_tmdb.get(str(mid))
                if m:
                    # Resolve best poster URL
                    poster = m.get('remotePoster', '')
                    if not poster:
                        for img in m.get('images', []):
                            if img.get('coverType') == 'poster':
                                poster = img.get('remoteUrl') or img.get('url', '')
                                if poster: break
                    result['movie'][mid] = {
                        'in_library': True,
                        'hasFile':    m.get('hasFile', False),
                        'internalId': m.get('id'),
                        'monitored':  m.get('monitored', False),
                        'remotePoster': poster,
                        'title':      m.get('title', ''),
                    }
                else:
                    result['movie'][mid] = {'in_library': False}

        if tv_ids:
            series  = get_cached_library('tv')
            by_tmdb = {str(s.get('tmdbId', '')): s for s in series}
            for tid in tv_ids:
                s = by_tmdb.get(str(tid))
                if s:
                    poster = s.get('remotePoster', '')
                    if not poster:
                        for img in s.get('images', []):
                            if img.get('coverType') == 'poster':
                                poster = img.get('remoteUrl') or img.get('url', '')
                                if poster: break
                    result['tv'][tid] = {
                        'in_library': True,
                        'internalId': s.get('id'),
                        'monitored':  s.get('monitored', False),
                        'statistics': s.get('statistics', {}),
                        'remotePoster': poster,
                        'title':      s.get('title', ''),
                    }
                else:
                    result['tv'][tid] = {'in_library': False}

        return jsonify(result)

    @app.route('/api/<string:media_type>/<int:internal_id>/monitor', methods=['PUT'])
    @requires_auth
    def update_media_monitor(media_type, internal_id):
        """Toggle monitored state for movies and TV series."""
        if media_type not in ('movie', 'tv'):
            return jsonify({'error': 'unsupported media type'}), 400

        data = request.get_json(silent=True) or {}
        monitored = bool(data.get('monitored'))

        try:
            if media_type == 'movie':
                if not CONFIG.radarr.enabled:
                    return jsonify({'error': 'Radarr not configured'}), 503
                base_url = f"{CONFIG.radarr.url}/api/v3/movie/{internal_id}"
                params = {'apikey': CONFIG.radarr.api_key}
            else:
                if not CONFIG.sonarr.enabled:
                    return jsonify({'error': 'Sonarr not configured'}), 503
                base_url = f"{CONFIG.sonarr.url}/api/v3/series/{internal_id}"
                params = {'apikey': CONFIG.sonarr.api_key}

            existing = requests.get(base_url, params=params, timeout=15)
            if existing.status_code != 200:
                return jsonify({'error': f'lookup failed: HTTP {existing.status_code}'}), existing.status_code

            payload = existing.json()
            payload['monitored'] = monitored

            updated = requests.put(base_url, params=params, json=payload, timeout=15)
            if updated.status_code not in (200, 202):
                return jsonify({'error': updated.text[:400] or 'update failed'}), updated.status_code

            return jsonify({'success': True, 'monitored': monitored})
        except Exception as e:
            logging.error("[monitor] %s %s failed: %s", media_type, internal_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/<string:media_type>/<int:internal_id>/search', methods=['POST'])
    @requires_auth
    def search_media_missing(media_type, internal_id):
        """Trigger the standard Arr automatic search for a movie or TV series."""
        if media_type not in ('movie', 'tv'):
            return jsonify({'error': 'unsupported media type'}), 400

        try:
            if media_type == 'movie':
                if not CONFIG.radarr.enabled:
                    return jsonify({'error': 'Radarr not configured'}), 503
                url = f"{CONFIG.radarr.url}/api/v3/command"
                params = {'apikey': CONFIG.radarr.api_key}
                payload = {'name': 'MoviesSearch', 'movieIds': [internal_id]}
            else:
                if not CONFIG.sonarr.enabled:
                    return jsonify({'error': 'Sonarr not configured'}), 503
                url = f"{CONFIG.sonarr.url}/api/v3/command"
                params = {'apikey': CONFIG.sonarr.api_key}
                payload = {'name': 'SeriesSearch', 'seriesId': internal_id}

            r = requests.post(url, params=params, json=payload, timeout=20)
            if r.status_code not in (200, 201):
                return jsonify({'error': r.text[:400] or 'search failed'}), r.status_code
            return jsonify({'success': True, 'result': r.json()})
        except Exception as e:
            logging.error("[auto_search] %s %s failed: %s", media_type, internal_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/<string:media_type>/<int:internal_id>/interactive-search')
    @requires_auth
    def interactive_search_media(media_type, internal_id):
        """Return manual-search release candidates from Radarr/Sonarr."""
        if media_type not in ('movie', 'tv'):
            return jsonify({'error': 'unsupported media type'}), 400

        try:
            if media_type == 'movie':
                if not CONFIG.radarr.enabled:
                    return jsonify({'error': 'Radarr not configured'}), 503
                url = f"{CONFIG.radarr.url}/api/v3/release"
                params = {'apikey': CONFIG.radarr.api_key, 'movieId': internal_id}
            else:
                if not CONFIG.sonarr.enabled:
                    return jsonify({'error': 'Sonarr not configured'}), 503
                url = f"{CONFIG.sonarr.url}/api/v3/release"
                params = {'apikey': CONFIG.sonarr.api_key, 'seriesId': internal_id}

            r = requests.get(url, params=params, timeout=25)
            if r.status_code != 200:
                return jsonify({'error': r.text[:400] or 'interactive search failed'}), r.status_code

            releases = r.json() if isinstance(r.json(), list) else []
            return jsonify({'success': True, 'results': releases})
        except Exception as e:
            logging.error("[interactive_search] %s %s failed: %s", media_type, internal_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/<string:media_type>/<int:internal_id>/grab-release', methods=['POST'])
    @requires_auth
    def grab_release(media_type, internal_id):
        """Send a selected manual-search release to Radarr/Sonarr for download."""
        if media_type not in ('movie', 'tv'):
            return jsonify({'error': 'unsupported media type'}), 400

        data = request.get_json(silent=True) or {}
        release = data.get('release')
        if not isinstance(release, dict):
            return jsonify({'error': 'release payload required'}), 400

        try:
            if media_type == 'movie':
                if not CONFIG.radarr.enabled:
                    return jsonify({'error': 'Radarr not configured'}), 503
                url = f"{CONFIG.radarr.url}/api/v3/release"
                params = {'apikey': CONFIG.radarr.api_key}
                release.setdefault('movieId', internal_id)
            else:
                if not CONFIG.sonarr.enabled:
                    return jsonify({'error': 'Sonarr not configured'}), 503
                url = f"{CONFIG.sonarr.url}/api/v3/release"
                params = {'apikey': CONFIG.sonarr.api_key}
                release.setdefault('seriesId', internal_id)

            r = requests.post(url, params=params, json=release, timeout=25)
            if r.status_code not in (200, 201):
                return jsonify({'error': r.text[:400] or 'grab failed'}), r.status_code
            return jsonify({'success': True, 'result': r.json()})
        except Exception as e:
            logging.error("[grab_release] %s %s failed: %s", media_type, internal_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/series/<int:series_id>/seasons')
    @requires_auth
    def get_series_seasons(series_id):
        """Return Sonarr episodes grouped by season for a series."""
        if not CONFIG.sonarr.enabled:
            return jsonify({'error': 'Sonarr not configured'}), 503

        try:
            episodes_url = f"{CONFIG.sonarr.url}/api/v3/episode"
            r = requests.get(
                episodes_url,
                params={'apikey': CONFIG.sonarr.api_key, 'seriesId': series_id, 'includeImages': 'false'},
                timeout=25
            )
            if r.status_code != 200:
                return jsonify({'error': r.text[:400] or 'episode lookup failed'}), r.status_code

            grouped = {}
            for ep in r.json():
                season_no = ep.get('seasonNumber', 0)
                grouped.setdefault(season_no, {
                    'seasonNumber': season_no,
                    'episodes': [],
                })
                grouped[season_no]['episodes'].append({
                    'id': ep.get('id'),
                    'episodeNumber': ep.get('episodeNumber'),
                    'title': ep.get('title') or f"Episode {ep.get('episodeNumber')}",
                    'airDate': ep.get('airDateUtc') or ep.get('airDate'),
                    'hasFile': ep.get('hasFile', False),
                    'episodeFileId': ep.get('episodeFileId'),
                    'monitored': ep.get('monitored', False),
                })

            seasons = list(grouped.values())
            for season in seasons:
                season['episodes'].sort(key=lambda e: (e.get('episodeNumber') or 0))
            seasons.sort(key=lambda s: s['seasonNumber'])
            return jsonify(seasons)
        except Exception as e:
            logging.error("[series_seasons] %s failed: %s", series_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/episode/<int:episode_id>/search', methods=['POST'])
    @requires_auth
    def search_episode_route(episode_id):
        """Trigger Sonarr episode search for a single episode."""
        if not CONFIG.sonarr.enabled:
            return jsonify({'error': 'Sonarr not configured'}), 503
        try:
            r = requests.post(
                f"{CONFIG.sonarr.url}/api/v3/command",
                params={'apikey': CONFIG.sonarr.api_key},
                json={'name': 'EpisodeSearch', 'episodeIds': [episode_id]},
                timeout=20
            )
            if r.status_code not in (200, 201):
                return jsonify({'error': r.text[:400] or 'episode search failed'}), r.status_code
            return jsonify({'success': True})
        except Exception as e:
            logging.error("[episode_search] %s failed: %s", episode_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/episode/<int:episode_id>', methods=['DELETE'])
    @requires_auth
    def delete_episode_route(episode_id):
        """Delete a downloaded Sonarr episode file."""
        if not CONFIG.sonarr.enabled:
            return jsonify({'error': 'Sonarr not configured'}), 503
        try:
            ep = requests.get(
                f"{CONFIG.sonarr.url}/api/v3/episode/{episode_id}",
                params={'apikey': CONFIG.sonarr.api_key},
                timeout=15
            )
            if ep.status_code != 200:
                return jsonify({'error': ep.text[:400] or 'episode lookup failed'}), ep.status_code
            ep_data = ep.json()
            episode_file_id = ep_data.get('episodeFileId')
            if not episode_file_id:
                return jsonify({'error': 'episode has no file'}), 400

            r = requests.delete(
                f"{CONFIG.sonarr.url}/api/v3/episodefile/{episode_file_id}",
                params={'apikey': CONFIG.sonarr.api_key},
                timeout=20
            )
            if r.status_code not in (200, 202):
                return jsonify({'error': r.text[:400] or 'delete failed'}), r.status_code
            return jsonify({'success': True})
        except Exception as e:
            logging.error("[episode_delete] %s failed: %s", episode_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/check_library_status')
    @conditional_debug_log
    @requires_auth
    def check_library_status():
        media_type = request.args.get('type')
        media_id = request.args.get('id')
        source = request.args.get('source', 'tvdb' if media_type == 'tv' else 'tmdb')

        # Use cached library data (60s TTL)
        existing = get_cached_library(media_type)

        match = None
        if media_type == 'movie':
            match = next((m for m in existing if str(m.get('tmdbId')) == str(media_id)), None)
        elif media_type == 'book':
            match = next((b for b in existing if str(b.get('foreignBookId')) == str(media_id)), None)
        else:
            target_key = 'tmdbId' if source == 'tmdb' else 'tvdbId'
            match = next((s for s in existing if str(s.get(target_key)) == str(media_id)), None)

        if match:
            return jsonify({
                'in_library': True,
                'statistics': match.get('statistics', {}),
                'path': match.get('path'),
                'status': match.get('status')
            })

        return jsonify({'in_library': False})

    @app.route('/api/update/dismiss', methods=['POST'])
    @conditional_debug_log
    def dismiss_update_notification():
        # """Dismiss the update notification"""
        update_manager.set_env('UPDATE_NOTIFICATION', 'false')
        return jsonify({'success': True})

    # Information page
    @app.route('/api/info/network')
    @conditional_debug_log
    @requires_auth
    def get_network_info():
        """Get network information for the info panel"""
        try:
            if network_info_func:
                return jsonify(network_info_func())
            else:
                # Fallback if function not provided
                return jsonify({
                    'local_ip': get_ip_address(),
                    'port': CONFIG.app.port,
                    'duckdns_enabled': CONFIG.duckdns.enabled,
                    'duckdns_domain': CONFIG.duckdns.domain,
                    'tunnel_enabled': CONFIG.tunnel.enabled,
                    'tunnel_url': None,
                    'tunnel_active': False
                })
        except Exception as e:
            logging.error(f"Error getting network info: {str(e)}")
            return jsonify({'error': str(e)}), 500
        
    @app.route('/api/info/changelog')
    @conditional_debug_log
    @requires_auth
    def get_recent_changelog():
        """Get the most recent section from changelog.md"""
        try:
            changelog_path = os.path.join(os.path.dirname(__file__), 'CHANGELOG.md')
            
            if not os.path.exists(changelog_path):
                # Try static folder as fallback
                changelog_path = os.path.join(os.path.dirname(__file__), 'static', 'CHANGELOG.md')
                
            if not os.path.exists(changelog_path):
                return jsonify({
                    'recent_changes': 'Changelog not available.',
                    'last_updated': 'Unknown'
                })
            
            # Read changelog file with error handling for encoding
            try:
                with open(changelog_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(changelog_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            
            # Improved parsing to get the most recent version section
            # Look for pattern like "## [version]" to find version sections
            version_sections = re.split(r'\n## \[', content)
            
            if len(version_sections) > 1:
                # The first part is the header, second part is the most recent version
                recent_section = version_sections[1].strip()
                
                # Add the "## [" back that was removed by split
                recent_section = "## [" + recent_section
                
                # Find the next version section to trim at the right place
                next_version_match = re.search(r'\n## \[', recent_section)
                if next_version_match:
                    recent_section = recent_section[:next_version_match.start()].strip()
            else:
                # Fallback: if no version sections found, use first section after title
                sections = content.split('\n## ')
                if len(sections) > 1:
                    recent_section = sections[1].strip()
                    # Find the next major section
                    next_section_pos = recent_section.find('\n## ')
                    if next_section_pos != -1:
                        recent_section = recent_section[:next_section_pos].strip()
                else:
                    # If no sections found, return first 1000 characters
                    recent_section = content[:1000] + "..." if len(content) > 1000 else content
            
            # Convert markdown to HTML for better display
            recent_section = convert_markdown_to_html(recent_section)
            
            # Get file modification time for last updated
            stat = os.stat(changelog_path)
            last_updated = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            return jsonify({
                'recent_changes': recent_section,
                'last_updated': last_updated
            })
            
        except Exception as e:
            logging.error(f"Error reading changelog: {str(e)}")
            return jsonify({
                'recent_changes': f'Error loading changelog: {str(e)}',
                'last_updated': 'Error'
            }), 500

    def convert_markdown_to_html(markdown_text):
        """Convert markdown text to simple HTML for display - PRESERVE ALL CONTENT"""
        if not markdown_text:
            return ""
        
        html = markdown_text
        
        # Convert headers (preserve all levels)
        html = re.sub(r'##### (.*?)\n', r'<h5>\1</h5>', html)
        html = re.sub(r'#### (.*?)\n', r'<h4>\1</h4>', html)
        html = re.sub(r'### (.*?)\n', r'<h3>\1</h3>', html)
        html = re.sub(r'## (.*?)\n', r'<h2>\1</h2>', html)
        html = re.sub(r'# (.*?)\n', r'<h1>\1</h1>', html)
        
        # Convert bullet points (handle multiple levels)
        lines = html.split('\n')
        in_list = False
        processed_lines = []
        
        for line in lines:
            # Check for bullet points at different indentation levels
            if re.match(r'^\s*[-*+]\s+', line):
                if not in_list:
                    processed_lines.append('<ul>')
                    in_list = True
                # Preserve indentation with CSS classes
                indent_level = len(re.match(r'^\s*', line).group(0)) // 2
                indent_class = f'indent-{indent_level}' if indent_level > 0 else ''
                content = re.sub(r'^\s*[-*+]\s+', '', line)
                processed_lines.append(f'<li class="{indent_class}">{content}</li>')
            else:
                if in_list:
                    processed_lines.append('</ul>')
                    in_list = False
                processed_lines.append(line)
        
        # Close any open list
        if in_list:
            processed_lines.append('</ul>')
        
        html = '\n'.join(processed_lines)
        
        # Convert line breaks (preserve multiple consecutive breaks)
        html = re.sub(r'\n\s*\n', '</p><p>', html)  # Multiple newlines become paragraph breaks
        html = re.sub(r'\n', '<br>', html)  # Single newlines become line breaks
        
        # Wrap in paragraphs if not already in lists
        if not html.startswith('<ul>') and not html.startswith('<h'):
            html = f'<p>{html}</p>'
        
        # Remove any remaining markdown symbols but preserve content
        html = re.sub(r'\[(.*?)\]\(.*?\)', r'<span class="link-text">\1</span>', html)  # Keep link text
        
        return html

    @app.route('/api/info/last-updated')
    @conditional_debug_log
    @requires_auth
    def get_last_updated():
        """Get the last updated time of the application"""
        try:
            app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app.py'))
            stat = os.stat(app_path)
            last_updated = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            return jsonify({
                'last_updated': last_updated,
                'app_file': app_path
            })
        except Exception as e:
            logging.error(f"Error getting last updated time: {str(e)}")
            return jsonify({'error': str(e)}), 500


    # Update routes
    @app.route('/api/update/check')
    @conditional_debug_log
    def check_update():
        update_info = update_manager._check_github_for_updates()
        return jsonify(update_info)

    @app.route('/api/update/download', methods=['POST'])
    @conditional_debug_log
    def download_update_route():
        result = update_manager.download_update()
        return jsonify(result)

    @app.route('/api/update/status')
    @conditional_debug_log
    def update_status():
        return jsonify({
            'update_notification': os.getenv('UPDATE_NOTIFICATION', 'false') == 'true',
            'latest_version': os.getenv('LATEST_VERSION', ''),
            'current_version': CONFIG.app.version,
            'channel': CONFIG.update.channel,
            'current_commit': os.getenv('APP_COMMIT', '')
        })

    @app.route('/api/update/channel', methods=['POST'])
    @conditional_debug_log
    def switch_channel():
        """Switch between prod and dev channels"""
        data = request.json
        new_channel = data.get('channel', 'prod')
        
        if new_channel not in ['prod', 'dev']:
            return jsonify({'success': False, 'error': 'Invalid channel'})
        
        # Update environment
        update_manager.set_env('UPDATE_CHANNEL', new_channel)
        
        # Reload config
        CONFIG._reload_config()
        update_manager.current_channel = new_channel
        
        return jsonify({'success': True, 'channel': new_channel})

    @app.route('/api/update/list')
    @conditional_debug_log
    def list_downloaded_updates():
        # """Get list of downloaded updates"""
        update_files = update_manager.get_downloaded_updates_optimized()
        return jsonify({
            'updates': update_files,
            'total_count': len(update_files)
        })

    # Authentication routes
    @app.route('/login', methods=['GET', 'POST'])
    @conditional_debug_log
    def login():
        if not CONFIG.auth.enabled:
            return redirect('/')
        
        if session.get('authenticated'):
            return redirect('/')
        
        error = None
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            if utils.check_auth(username, password):
                session['authenticated'] = True
                session['username'] = username
                return redirect(request.args.get('next') or '/')
            else:
                error = 'Invalid username or password'
        
        return render_template('login.html', error=error, config=CONFIG._config)

    @app.route('/logout')
    @conditional_debug_log
    def logout():
        session.clear()
        return redirect('/')

    # Static file routes
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static', 'images'),
                                'favicon.ico', mimetype='image/vnd.microsoft.icon')

    @app.route('/images/<path:filename>')
    @conditional_debug_log
    @requires_auth  
    def serve_image(filename):
        return send_from_directory('static/images', filename)

    @app.route('/offline.html')
    @conditional_debug_log
    def offline():
        try:
            return render_template('offline.html')
        except Exception as e:
            logging.error(f"Template error: {e}")
            return "Page not found", 404

    # Configuration save route
    @app.route('/save_config', methods=['POST'])
    @conditional_debug_log
    @requires_auth
    def save_config():
        """Save configuration from the config form"""
        try:
            data = request.json
            
            if not data:
                return jsonify({'success': False, 'error': 'No configuration data provided'}), 400
            
            # Save each configuration value to the .env file
            for key, value in data.items():
                # Skip if None
                if value is None:
                    continue
                
                # Convert boolean values to string
                if isinstance(value, bool):
                    value = 'true' if value else 'false'
                else:
                    value = str(value)
                
                # Save to environment using update_manager
                update_manager.set_env(key, value)
            
            # Reload configuration after saving
            CONFIG._reload_config()
            
            logging.info(f"Configuration updated with {len(data)} parameters")
            return jsonify({'success': True, 'message': 'Configuration saved successfully'})
            
        except Exception as e:
            logging.error(f"Error saving configuration: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ============ PROWLARR ROUTES ============

    @app.route('/prowlarr')
    @conditional_debug_log
    @requires_auth
    def prowlarr_page():
        if not CONFIG.prowlarr.enabled:
            return redirect('/')
        return render_template('prowlarr.html',
                               config=CONFIG._config,
                               qbit_enabled=CONFIG.qbit.enabled,
                               readarr_enabled=CONFIG.readarr.enabled)

    @app.route('/api/prowlarr/search')
    @conditional_debug_log
    @requires_auth
    def prowlarr_search():
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'error': 'No query provided'}), 400
        if not CONFIG.prowlarr.enabled:
            return jsonify({'error': 'Prowlarr not configured'}), 503
        # Optional category filter — comma-separated Newznab IDs, e.g. ?categories=2000,2010
        raw_cats = request.args.get('categories', '').strip()
        categories = [int(c) for c in raw_cats.split(',') if c.strip().isdigit()] if raw_cats else None
        results = utils.search_prowlarr(query, categories=categories)
        return jsonify({'results': results})

    @app.route('/api/prowlarr/download', methods=['POST'])
    @conditional_debug_log
    @requires_auth
    def prowlarr_download():
        data = request.json or {}
        torrent_url = data.get('url', '').strip()
        category = data.get('category', '')
        if not torrent_url:
            return jsonify({'success': False, 'message': 'No URL provided'}), 400
        if not CONFIG.qbit.enabled:
            return jsonify({'success': False, 'message': 'qBittorrent not configured'}), 503
        result = utils.qbit_add_torrent(torrent_url, category)
        return jsonify(result)

    # ============ QBITTORRENT ROUTES ============

    @app.route('/api/qbit/test')
    @conditional_debug_log
    @requires_auth
    def qbit_test():
        if not CONFIG.qbit.enabled:
            return jsonify({'status': 'error', 'message': 'qBittorrent not configured'}), 503
        result = utils.qbit_test()
        return jsonify(result)

    @app.route('/downloads')
    @conditional_debug_log
    @requires_auth
    def downloads_page():
        if not CONFIG.qbit.enabled:
            return redirect('/')
        return render_template('downloads.html',
                               config=CONFIG._config,
                               qbit_enabled=CONFIG.qbit.enabled)

    @app.route('/api/downloads')
    @conditional_debug_log
    @requires_auth
    def api_downloads():
        if not CONFIG.qbit.enabled:
            return jsonify({'error': 'qBittorrent not configured'}), 503
        torrents = utils.qbit_get_torrents()
        return jsonify({'torrents': torrents})

    # ============ EBOOK READER ROUTES ============
    @app.route('/read/<int:book_id>')
    @requires_auth
    def read_book(book_id):
        """Serve the ebook reader page for a Readarr internal book ID."""
        if is_kindle_request():
            return redirect(url_for('kindle_books'))

        if not CONFIG.readarr.url:
            return redirect('/')

        file_path = utils.get_readarr_book_file_path(book_id)
        if not file_path:
            return render_template('error.html'), 404

        ext = os.path.splitext(file_path)[1].lower()
        file_type = 'epub' if ext == '.epub' else 'pdf' if ext == '.pdf' else None
        if not file_type:
            return render_template('error.html'), 415

        return render_template('reader.html',
                               book_id=book_id,
                               file_type=file_type,
                               config=CONFIG._config)

    @app.route('/api/book/file/<int:book_id>')
    @requires_auth
    def book_file(book_id):
        """Stream the ebook file for a given Readarr internal book ID.
        epub.js fetches this as an ArrayBuffer (see reader.html) so we must
        send the raw binary with correct MIME and permissive headers.
        """
        logging.info('[KindleLog] /api/book/file/%s | UA=%s | Range=%s',
                     book_id,
                     request.headers.get('User-Agent', '—'),
                     request.headers.get('Range', '—'))
        if not CONFIG.readarr.url:
            logging.warning('[KindleLog] book_file/%s — Readarr not configured', book_id)
            return jsonify({'error': 'Readarr not configured'}), 503
        file_path = utils.get_readarr_book_file_path(book_id)
        if not file_path or not os.path.isfile(file_path):
            logging.warning('[KindleLog] book_file/%s — file not found: %s', book_id, file_path)
            return jsonify({'error': 'File not found'}), 404
        ext = os.path.splitext(file_path)[1].lower()
        mime = 'application/epub+zip' if ext == '.epub' else 'application/pdf'
        file_size = os.path.getsize(file_path)
        logging.info('[KindleLog] book_file/%s — streaming %s (%s bytes, mime=%s)',
                     book_id, file_path, file_size, mime)
        try:
            response = send_file(
                file_path,
                mimetype=mime,
                as_attachment=False,
                conditional=False,
            )
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Cache-Control'] = 'no-store'
            return response
        except Exception as e:
            logging.error('[KindleLog] book_file/%s — send_file error: %s', book_id, e, exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/torrents/action', methods=['POST'])
    @conditional_debug_log
    @requires_auth
    def torrent_action():
        """Perform an action on one or more torrents.
        Body: { "action": "resume"|"pause"|"delete"|"setForceStart", "hashes": "abc123" | ["abc","def"] }
        """
        if not CONFIG.qbit.enabled:
            return jsonify({'error': 'qBittorrent not configured'}), 503
        data = request.get_json(silent=True) or {}
        action = data.get('action')
        hashes = data.get('hashes')
        if not action or not hashes:
            return jsonify({'error': 'action and hashes are required'}), 400
        if action not in ('resume', 'pause', 'delete', 'setForceStart'):
            return jsonify({'error': f'Unknown action: {action}'}), 400
        result = utils.qbit_action(action, hashes)
        return jsonify(result)

    @app.route('/api/<string:media_type>/<int:internal_id>', methods=['DELETE'])
    @conditional_debug_log
    @requires_auth
    def delete_media(media_type, internal_id):
        """Delete a movie, TV show, or book from the library (no file deletion)."""
        try:
            if media_type == 'movie':
                if not CONFIG.radarr.enabled:
                    return jsonify({'success': False, 'message': 'Radarr not configured'}), 503
                r = requests.delete(
                    f"{CONFIG.radarr.url}/api/v3/movie/{internal_id}",
                    params={'apikey': CONFIG.radarr.api_key, 'deleteFiles': 'false', 'addImportExclusion': 'false'}
                )
            elif media_type == 'tv':
                if not CONFIG.sonarr.enabled:
                    return jsonify({'success': False, 'message': 'Sonarr not configured'}), 503
                r = requests.delete(
                    f"{CONFIG.sonarr.url}/api/v3/series/{internal_id}",
                    params={'apikey': CONFIG.sonarr.api_key, 'deleteFiles': 'false'}
                )
            elif media_type == 'book':
                if not CONFIG.readarr.enabled:
                    return jsonify({'success': False, 'message': 'Readarr not configured'}), 503
                r = requests.delete(
                    f"{CONFIG.readarr.url}/api/v1/book/{internal_id}",
                    params={'apikey': CONFIG.readarr.api_key, 'deleteFiles': 'false'}
                )
            else:
                return jsonify({'success': False, 'message': f'Unknown media type: {media_type}'}), 400

            if r.status_code in (200, 204):
                logging.info(f"[delete_media] Deleted {media_type} id={internal_id}")
                return jsonify({'success': True})
            else:
                msg = f"{media_type.capitalize()} API returned HTTP {r.status_code}: {r.text[:200]}"
                logging.error(f"[delete_media] {msg}")
                return jsonify({'success': False, 'message': msg}), r.status_code

        except Exception as e:
            logging.error(f"[delete_media] Error deleting {media_type} {internal_id}: {e}", exc_info=True)
            return jsonify({'success': False, 'message': str(e)}), 500

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html'), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500

    logging.info("All routes initialized successfully")
