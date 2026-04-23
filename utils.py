# utils.py
import requests
import os
import logging
from datetime import datetime
import time
from packaging import version

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
        """Add a book to Readarr by looking up the author then adding via author endpoint"""
        logging.info(f"[Readarr] adding book foreignBookId={foreign_book_id}")
        try:
            # Look up the book to get author data
            lookup_url = f"{self.config.readarr.url}/api/v1/book/lookup"
            params = {'term': f'goodreads:{foreign_book_id}', 'apikey': self.config.readarr.api_key}
            lookup_res = requests.get(lookup_url, params=params, timeout=10)

            if lookup_res.status_code != 200:
                return False

            results = lookup_res.json()
            if not results:
                return False

            book_data = results[0]
            author_data = book_data.get('author', {})

            if not author_data:
                return False

            # Add author with specific book monitored
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
            return response.status_code in [200, 201]

        except Exception as e:
            logging.error(f"Error adding to Readarr: {str(e)}")
            return False

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
            # Normalise image field: Readarr uses 'url' not 'remoteUrl'
            for book in books:
                for img in book.get('images', []):
                    if 'url' in img and 'remoteUrl' not in img:
                        img['remoteUrl'] = img['url']
                    # Normalise coverType: Readarr uses 'cover' instead of 'poster'
                    if img.get('coverType') == 'cover':
                        img['coverType'] = 'poster'
            return books
        except Exception as e:
            logging.error(f"Error fetching Readarr books: {str(e)}")
            return []

    def get_readarr_details(self, foreign_book_id):
        """Get details for a specific book from Readarr"""
        try:
            # Check if it's in the library first
            library_url = f"{self.config.readarr.url}/api/v1/book"
            existing = requests.get(library_url, params={'apikey': self.config.readarr.api_key}, timeout=10).json()

            for book in existing:
                if str(book.get('foreignBookId')) == str(foreign_book_id):
                    # Normalise images
                    for img in book.get('images', []):
                        if 'url' in img and 'remoteUrl' not in img:
                            img['remoteUrl'] = img['url']
                        if img.get('coverType') == 'cover':
                            img['coverType'] = 'poster'
                    return {
                        'status': 'existing',
                        'data': book,
                        'on_disk': (book.get('statistics', {}).get('sizeOnDisk', 0) > 0),
                        'monitored': book.get('monitored', False)
                    }

            # Not in library — look it up
            lookup_url = f"{self.config.readarr.url}/api/v1/book/lookup"
            lookup = requests.get(lookup_url, params={
                'term': f'goodreads:{foreign_book_id}',
                'apikey': self.config.readarr.api_key
            }, timeout=10).json()

            if lookup:
                book = lookup[0]
                for img in book.get('images', []):
                    if 'url' in img and 'remoteUrl' not in img:
                        img['remoteUrl'] = img['url']
                    if img.get('coverType') == 'cover':
                        img['coverType'] = 'poster'
                return {
                    'status': 'not_added',
                    'data': book,
                    'on_disk': False,
                    'monitored': False
                }

            return {'error': 'Book not found'}

        except Exception as e:
            logging.error(f"Error fetching Readarr details: {str(e)}")
            return {'error': str(e)}

    # ============ PROWLARR METHODS ============

    def search_prowlarr(self, query):
        """Search Prowlarr across all indexers"""
        try:
            url = f"{self.config.prowlarr.url}/api/v1/search"
            params = {
                'query': query,
                'type': 'search',
                'limit': 100,
                'offset': 0,
                'apikey': self.config.prowlarr.api_key
            }
            logging.info(f"[Prowlarr] searching: term={query!r}")
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

    def check_auth(self, username, password):
        """Check authentication"""
        if not self.config.auth.enabled:
            return True
        return (username == self.config.auth.username and 
                password == self.config.auth.password)