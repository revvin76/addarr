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
            limit = 10
            
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
        url = f"{self.config.radarr.url}/api/v3/movie/lookup"
        params = {'term': query, 'apikey': self.config.radarr.api_key}
        response = requests.get(url, params=params)
        return response.json()
    
    def search_sonarr(self, query):
        url = f"{self.config.sonarr.url}/api/v3/series/lookup"
        params = {'term': query, 'apikey': self.config.sonarr.api_key}
        response = requests.get(url, params=params)
        return response.json()
    
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
    
    def add_to_sonarr(self, tvdb_id):
        lookup_url = f"{self.config.sonarr.url}/api/v3/series/lookup"
        params = {'term': f'tvdb:{tvdb_id}', 'apikey': self.config.sonarr.api_key}
        
        lookup_res = requests.get(lookup_url, params=params)
        if lookup_res.status_code != 200:
            return False
        
        series_data = lookup_res.json()[0]
        
        payload = {
            'tvdbId': tvdb_id,
            'title': series_data['title'],
            'monitored': True,
            'rootFolderPath': self.config.sonarr.root_folder,
            'qualityProfileId': self.config.sonarr.quality_profile_id,
            'languageProfileId': self.config.sonarr.language_profile_id,
            'addOptions': {'searchForMissingEpisodes': True, 'monitor': 'all'},
            'seasonFolder': True,
            'seriesType': 'standard'
        }
        
        response = requests.post(
            f"{self.config.sonarr.url}/api/v3/series",
            json=payload,
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
        
        for series in existing:
            if str(series.get('tvdbId')) == str(tvdb_id):
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
            'term': f'tvdb:{tvdb_id}',
            'apikey': self.config.sonarr.api_key
        }).json()
        
        if lookup:
            return {
                'status': 'not_added',
                'data': lookup[0],
                'on_disk': False,
                'monitored': False,
                'status': lookup[0].get('status', 'unknown')
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

    def check_auth(self, username, password):
        """Check authentication"""
        if not self.config.auth.enabled:
            return True
        return (username == self.config.auth.username and 
                password == self.config.auth.password)