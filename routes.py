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


# Import shared utilities (will be passed from app.py)
def init_routes(app, config_manager, update_manager, auth_decorator, debug_decorator, shared_utils, network_info_func=None):
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

    # Library status cache with 60s TTL
    library_cache = {
        'movies': {'data': None, 'timestamp': 0},
        'series': {'data': None, 'timestamp': 0},
        'books': {'data': None, 'timestamp': 0}
    }
    CACHE_TTL = 60  # 60 seconds

    def get_cached_library(media_type):
        """Get library from cache or fetch fresh if expired (60s TTL)"""
        if media_type == 'movie':
            cache_key = 'movies'
        elif media_type == 'book':
            cache_key = 'books'
        else:
            cache_key = 'series'
        cache_entry = library_cache[cache_key]
        current_time = time.time()

        # Check if cache is still valid
        if cache_entry['data'] is not None and (current_time - cache_entry['timestamp']) < CACHE_TTL:
            return cache_entry['data']

        # Fetch fresh data
        try:
            if media_type == 'movie':
                response = requests.get(
                    f"{CONFIG.radarr.url}/api/v3/movie",
                    params={'apikey': CONFIG.radarr.api_key}
                )
            elif media_type == 'book':
                response = requests.get(
                    f"{CONFIG.readarr.url}/api/v1/book",
                    params={'apikey': CONFIG.readarr.api_key}
                )
            else:
                response = requests.get(
                    f"{CONFIG.sonarr.url}/api/v3/series",
                    params={'apikey': CONFIG.sonarr.api_key}
                )

            data = response.json()
            # Update cache
            cache_entry['data'] = data
            cache_entry['timestamp'] = current_time
            return data
        except Exception as e:
            logging.error(f"Error fetching {media_type} library: {str(e)}")
            # Return cached data if available, even if expired
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
        readarr_enabled = CONFIG.readarr.enabled
        apify_enabled   = CONFIG.apify.enabled
        logging.info(
            f"[SEARCH] query='{query}' | radarr={bool(CONFIG.radarr.url)} "
            f"sonarr={bool(CONFIG.sonarr.url)} readarr={readarr_enabled} apify={apify_enabled}"
        )

        try:
            book_search_enabled = readarr_enabled or apify_enabled
            max_workers = 3 if book_search_enabled else 2

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                movie_future = executor.submit(utils.search_radarr, query)
                tv_future    = executor.submit(utils.search_sonarr, query)
                if apify_enabled:
                    book_future = executor.submit(utils.search_goodreads_apify, query)
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
                readarr_enabled=readarr_enabled or apify_enabled
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

            combined_media = []
            for movie in movies:
                movie['media_type'] = 'movie'
                combined_media.append(movie)
            for show in series:
                show['media_type'] = 'tv'
                combined_media.append(show)

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

    @app.route('/manage-books')
    @conditional_debug_log
    @requires_auth
    def manage_books():
        try:
            if not CONFIG.readarr.enabled:
                return render_template('error.html', error="Readarr is not configured")
            books = utils.get_readarr_books()
            # Only show books that have at least one file on disk
            downloaded = [
                b for b in books
                if (b.get('statistics', {}).get('bookFileCount', 0) > 0
                    or b.get('statistics', {}).get('sizeOnDisk', 0) > 0)
            ]
            downloaded.sort(key=lambda x: x.get('title', '').lower())
            return render_template(
                'manage-books.html',
                books=downloaded,
                config=CONFIG._config,
                total_in_library=len(books),
                total_downloaded=len(downloaded)
            )
        except Exception as e:
            logging.error(f"Error fetching books: {str(e)}")
            return render_template('error.html', error="Failed to load books")

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
        media_type = request.args.get('type')
        tmdb_id = request.args.get('id')

        logging.info(f"Fetching TMDB details for type: {media_type}, ID: {tmdb_id}")
        
        if not media_type or not tmdb_id:
            return jsonify({'error': 'Missing type or ID'}), 400
        
        try:
            return jsonify(utils.get_tmdb_media_details(media_type, tmdb_id))
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
        if not CONFIG.readarr.url:
            return jsonify({'error': 'Readarr not configured'}), 503
        file_path = utils.get_readarr_book_file_path(book_id)
        if not file_path or not os.path.isfile(file_path):
            logging.warning(f"[reader] book file not found: {file_path!r}")
            return jsonify({'error': 'File not found'}), 404
        ext = os.path.splitext(file_path)[1].lower()
        mime = 'application/epub+zip' if ext == '.epub' else 'application/pdf'
        try:
            response = send_file(
                file_path,
                mimetype=mime,
                as_attachment=False,
                conditional=False,   # always send full file — no 304
            )
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Cache-Control'] = 'no-store'
            return response
        except Exception as e:
            logging.error(f"[reader] send_file error: {str(e)}", exc_info=True)
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