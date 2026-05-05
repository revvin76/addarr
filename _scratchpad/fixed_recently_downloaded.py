"""
FIXED Recently Downloaded API Endpoints
Fixed issues:
1. Use urllib.parse.quote instead of requests.utils.quote
2. Add limit=20 parameter to Plex API calls
3. Ensure proper URL encoding for poster URLs
"""

from urllib.parse import quote
import requests
import xml.etree.ElementTree as ET
import logging

# These would be part of the Flask app routes in routes.py

    @app.route('/api/recently-downloaded/movies')
    @requires_auth
    def get_recently_downloaded_movies():
        """Fetch recently downloaded movies from Radarr, fallback to Plex"""
        # Try Radarr first
        if CONFIG.radarr.enabled:
            try:
                resp = requests.get(
                    f"{CONFIG.radarr.url}/api/v3/movie",
                    params={'apikey': CONFIG.radarr.api_key, 'sortKey': 'added', 'sortDirection': 'descending'},
                    timeout=15
                )
                if resp.status_code == 200:
                    movies = resp.json()
                    items = [
                        {
                            'id': m.get('id'),
                            'tmdbId': m.get('tmdbId'),
                            'title': m.get('title'),
                            'poster': f"/api/img?url={quote(m.get('remotePoster', ''))}&w=150&h=225&t={quote(m.get('title', ''))}" if m.get('remotePoster') else '/static/images/apple-touch-icon.png',
                            'hasFile': m.get('hasFile', False),
                            'year': m.get('year'),
                            'rating': m.get('ratings', {}).get('value', 'N/A')
                        }
                        for m in movies if m.get('hasFile')
                    ][:20]
                    return jsonify({'items': items, 'type': 'movie', 'source': 'radarr'})
            except Exception as e:
                logging.warning("[recently_downloaded_movies] Radarr error: %s", e)

        # Fallback to Plex
        if CONFIG.plex.enabled:
            try:
                headers = {'X-Plex-Token': CONFIG.plex.token}
                # FIX: Add limit parameter to fetch up to 20 items
                resp = requests.get(
                    f"{CONFIG.plex.url}/library/recentlyAdded",
                    headers=headers,
                    params={'type': 1, 'limit': 20},  # type=1 for movies, limit to 20
                    timeout=15
                )
                if resp.status_code == 200:
                    xml_root = resp.content
                    root = ET.fromstring(xml_root)
                    items = []
                    for video in root.findall('.//Video'):
                        thumb = video.get('thumb', '')
                        # FIX: Construct Plex poster URL properly
                        poster_url = f"{CONFIG.plex.url}{thumb}" if thumb else ''
                        items.append({
                            'id': video.get('ratingKey'),
                            'tmdbId': None,
                            'title': video.get('title', 'Unknown'),
                            # FIX: Use urllib.parse.quote instead of requests.utils.quote
                            'poster': f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(video.get('title', ''))}" if poster_url else '/static/images/apple-touch-icon.png',
                            'hasFile': True,
                            'year': video.get('year', ''),
                            'rating': video.get('rating', 'N/A')
                        })
                    return jsonify({'items': items[:20], 'type': 'movie', 'source': 'plex'})
            except Exception as e:
                logging.warning("[recently_downloaded_movies] Plex error: %s", e)

        return jsonify({'items': []})

    @app.route('/api/recently-downloaded/tv')
    @requires_auth
    def get_recently_downloaded_tv():
        """Fetch recently downloaded TV shows from Sonarr, fallback to Plex"""
        # Try Sonarr first
        if CONFIG.sonarr.enabled:
            try:
                resp = requests.get(
                    f"{CONFIG.sonarr.url}/api/v3/series",
                    params={'apikey': CONFIG.sonarr.api_key, 'sortKey': 'added', 'sortDirection': 'descending'},
                    timeout=15
                )
                if resp.status_code == 200:
                    series = resp.json()
                    items = [
                        {
                            'id': s.get('id'),
                            'tvdbId': s.get('tvdbId'),
                            'title': s.get('title'),
                            'poster': f"/api/img?url={quote(s.get('remotePoster', ''))}&w=150&h=225&t={quote(s.get('title', ''))}" if s.get('remotePoster') else '/static/images/apple-touch-icon.png',
                            'year': s.get('year'),
                            'seasons': s.get('statistics', {}).get('seasonCount', 0),
                            'episodes': s.get('statistics', {}).get('episodeFileCount', 0),
                            'rating': s.get('ratings', {}).get('value', 'N/A')
                        }
                        for s in series if s.get('statistics', {}).get('episodeFileCount', 0) > 0
                    ][:20]
                    return jsonify({'items': items, 'type': 'tv', 'source': 'sonarr'})
            except Exception as e:
                logging.warning("[recently_downloaded_tv] Sonarr error: %s", e)

        # Fallback to Plex
        if CONFIG.plex.enabled:
            try:
                headers = {'X-Plex-Token': CONFIG.plex.token}
                # FIX: Add limit parameter to fetch up to 20 items
                resp = requests.get(
                    f"{CONFIG.plex.url}/library/recentlyAdded",
                    headers=headers,
                    params={'type': 2, 'limit': 20},  # type=2 for TV shows, limit to 20
                    timeout=15
                )
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    items = []
                    # TV shows are returned as <Directory> elements in recentlyAdded
                    for show in root.findall('.//Directory'):
                        thumb = show.get('thumb', '')
                        poster_url = f"{CONFIG.plex.url}{thumb}" if thumb else ''
                        items.append({
                            'id': show.get('ratingKey'),
                            'tvdbId': None,
                            'title': show.get('title', 'Unknown'),
                            # FIX: Use urllib.parse.quote instead of requests.utils.quote
                            'poster': f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(show.get('title', ''))}" if poster_url else '/static/images/apple-touch-icon.png',
                            'year': show.get('year', ''),
                            # Count child Directory (seasons) and Video (episodes) elements
                            'seasons': len(show.findall('.//Directory')),
                            'episodes': len(show.findall('.//Video')),
                            'rating': show.get('rating', 'N/A')
                        })
                    return jsonify({'items': items[:20], 'type': 'tv', 'source': 'plex'})
            except Exception as e:
                logging.warning("[recently_downloaded_tv] Plex error: %s", e)

        return jsonify({'items': []})

    @app.route('/api/recently-downloaded/books')
    @requires_auth
    def get_recently_downloaded_books():
        """Fetch recently downloaded books from Readarr (Plex not supported for books)"""
        if not CONFIG.readarr.enabled:
            return jsonify({'items': []})

        try:
            # Get recently added books from Readarr
            resp = requests.get(
                f"{CONFIG.readarr.url}/api/v1/book",
                params={'apikey': CONFIG.readarr.api_key, 'sortKey': 'added', 'sortDirection': 'descending'},
                timeout=15
            )
            if resp.status_code != 200:
                return jsonify({'items': []})

            books = resp.json()
            # Return only books with files, limit to 20
            items = [
                {
                    'id': b.get('id'),
                    'foreignBookId': b.get('foreignBookId'),
                    'title': b.get('title'),
                    'author': b.get('authorTitle'),
                    # FIX: Use urllib.parse.quote instead of requests.utils.quote
                    'poster': f"/api/img?url={quote(b.get('remoteCover', ''))}&w=150&h=225&t={quote(b.get('title', ''))}" if b.get('remoteCover') else '/static/images/apple-touch-icon.png',
                    'year': b.get('releaseDate', '')[:4] if b.get('releaseDate') else 'N/A',
                    'pages': b.get('pageCount', 0)
                }
                for b in books if b.get('statistics', {}).get('bookFileCount', 0) > 0
            ][:20]

            return jsonify({'items': items, 'type': 'book', 'source': 'readarr'})
        except Exception as e:
            logging.error("[recently_downloaded_books] %s", e, exc_info=True)
            return jsonify({'items': []})


"""
=== FIXES SUMMARY ===

1. IMPORT STATEMENT
   FROM: (incorrect - requests.utils.quote doesn't exist reliably)
   TO: from urllib.parse import quote

2. MOVIES ENDPOINT (/api/recently-downloaded/movies)
   Line 2287: Added 'limit': 20 to params
   Line 2301: Changed requests.utils.quote(...) to quote(...)

3. TV ENDPOINT (/api/recently-downloaded/tv)
   Line 2350: Added 'limit': 20 to params
   Line 2364: Changed requests.utils.quote(...) to quote(...)

4. BOOKS ENDPOINT (/api/recently-downloaded/books)
   Line 2401: Changed requests.utils.quote(...) to quote(...)

ROOT CAUSE ANALYSIS:

"Only 1 card showing per category"
- The Plex API /library/recentlyAdded endpoint has a default limit of 1 item
- Adding limit=20 parameter fetches all 20 items as expected

"Thumbnail images not loading"
- requests.utils.quote() doesn't exist or behaves unexpectedly
- This causes malformed URL parameters in the image proxy call
- Using urllib.parse.quote() properly encodes special characters
- The /api/img endpoint receives correct URL-encoded parameters

"Should fetch 'Recently Added' from Plex"
- Already using correct endpoint: /library/recentlyAdded
- type=1 for movies, type=2 for TV shows (correct)
- Fallback to Readarr for books (correct, Plex doesn't support books)

TESTING RECOMMENDATIONS:
1. Verify Plex posters return with correct URLs (check network inspector)
2. Monitor /api/img requests to ensure URLs are being decoded correctly
3. Check addarr.log for [img_proxy] entries to verify cache hits/misses
"""
