# Memory-optimized configuration management
import threading
import time
import os
from dotenv import load_dotenv

class ConfigSection:
    """Wrapper to allow attribute access to config sections"""
    def __init__(self, data):
        self._data = data
    
    def __getattr__(self, name):
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def get(self, key, default=None):
        return self._data.get(key, default)

class LazyConfig:
    """Lazy-loading configuration to reduce memory footprint"""
    def __init__(self):
        self._config = None
        self._last_reload = 0
        self._reload_interval = 300  # Reload every 5 minutes
        self._lock = threading.Lock()
    
    def _ensure_loaded(self):
        """Load configuration if needed"""
        with self._lock:
            current_time = time.time()
            if (self._config is None or 
                current_time - self._last_reload > self._reload_interval):
                self._reload_config()
    
    def _reload_config(self):
        """Load only essential configuration"""
        load_dotenv(override=True)
        
        config_data = {
            'radarr': {
                'url': os.getenv('RADARR_URL', ''),
                'api_key': os.getenv('RADARR_API_KEY', ''),
                'root_folder': os.getenv('RADARR_ROOT_FOLDER', ''),
                'quality_profile_id': os.getenv('RADARR_QUALITY_PROFILE', ''),
                'enabled': os.getenv('RADARR_ENABLED', os.getenv('RADARR_URL', '')).lower() == 'true'
                           if os.getenv('RADARR_ENABLED') is not None else bool(os.getenv('RADARR_URL', ''))
            },
            'sonarr': {
                'url': os.getenv('SONARR_URL', ''),
                'api_key': os.getenv('SONARR_API_KEY', ''),
                'root_folder': os.getenv('SONARR_ROOT_FOLDER', ''),
                'quality_profile_id': os.getenv('SONARR_QUALITY_PROFILE', ''),
                'language_profile_id': os.getenv('SONARR_LANGUAGE_PROFILE', ''),
                'enabled': os.getenv('SONARR_ENABLED', os.getenv('SONARR_URL', '')).lower() == 'true'
                           if os.getenv('SONARR_ENABLED') is not None else bool(os.getenv('SONARR_URL', ''))
            },
            'tmdb': {
                'key': os.getenv('TMDB_KEY', ''),
                'token': os.getenv('TMDB_TOKEN', ''),
                'enabled': os.getenv('TMDB_ENABLED', '').lower() == 'true'
                           if os.getenv('TMDB_ENABLED') is not None else bool(os.getenv('TMDB_KEY', '') or os.getenv('TMDB_TOKEN', ''))
            },
            'app': {
                'debug': os.getenv('FLASK_DEBUG', 'false').lower() == 'true',
                'version': os.getenv('APP_VERSION', '1.0.0'),
                'port': int(os.getenv('SERVER_PORT', '5000')),
                'log_level': os.getenv('LOG_LEVEL', 'INFO')
            },
            'duckdns': {
                'domain': os.getenv('DUCKDNS_DOMAIN', ''),
                'token': os.getenv('DUCKDNS_TOKEN', ''),
                'enabled': os.getenv('DUCKDNS_ENABLED', 'false').lower() == 'true'
            },
            'update': {
                'github_repo': os.getenv('GITHUB_REPO', 'revvin76/addarr'),
                'check_interval': int(os.getenv('CHECK_INTERVAL', '3600')),
                'last_checked': float(os.getenv('LAST_CHECKED', '0')),
                'enabled': os.getenv('ENABLE_AUTO_UPDATE', 'false').lower() == 'true',
                'updates_folder': os.getenv('UPDATES_FOLDER', 'updates'),
                'channel': os.getenv('UPDATE_CHANNEL', 'prod'),
                'notification': os.getenv('UPDATE_NOTIFICATION', 'false').lower() == 'true',
                'latest_version': os.getenv('LATEST_VERSION', ''),
                'applied': os.getenv('UPDATE_APPLIED', 'false').lower() == 'true',
                'applied_version': os.getenv('UPDATE_APPLIED_VERSION', '')
            },
            'auth': {
                'enabled': os.getenv('AUTH_ENABLED', 'false').lower() == 'true',
                'username': os.getenv('AUTH_USERNAME', ''),
                'password': os.getenv('AUTH_PASSWORD', '')
            },
            'tunnel': {
                'enabled': os.getenv('TUNNEL_ENABLED', 'false').lower() == 'true',
                'auth_token': os.getenv('PINGGY_AUTH_TOKEN', ''),
                'reserved_subdomain': os.getenv('PINGGY_RESERVED_SUBDOMAIN', '')
            },
            'readarr': {
                'url': os.getenv('READARR_URL', ''),
                'api_key': os.getenv('READARR_API_KEY', ''),
                'root_folder': os.getenv('READARR_ROOT_FOLDER', ''),
                'quality_profile_id': os.getenv('READARR_QUALITY_PROFILE', ''),
                'metadata_profile_id': os.getenv('READARR_METADATA_PROFILE', ''),
                'enabled': os.getenv('READARR_ENABLED', os.getenv('READARR_URL', '')).lower() == 'true'
                           if os.getenv('READARR_ENABLED') is not None else bool(os.getenv('READARR_URL', ''))
            },
            'prowlarr': {
                'url': os.getenv('PROWLARR_URL', ''),
                'api_key': os.getenv('PROWLARR_API_KEY', ''),
                'enabled': os.getenv('PROWLARR_ENABLED', os.getenv('PROWLARR_URL', '')).lower() == 'true'
                           if os.getenv('PROWLARR_ENABLED') is not None else bool(os.getenv('PROWLARR_URL', ''))
            },
            'qbit': {
                'url': os.getenv('QBIT_URL', ''),
                'username': os.getenv('QBIT_USERNAME', ''),
                'password': os.getenv('QBIT_PASSWORD', ''),
                'enabled': os.getenv('QBIT_ENABLED', os.getenv('QBIT_URL', '')).lower() == 'true'
                           if os.getenv('QBIT_ENABLED') is not None else bool(os.getenv('QBIT_URL', ''))
            },
            'google_books': {
                'api_key': os.getenv('GOOGLE_BOOKS_API_KEY', '').strip(),
                'enabled': os.getenv('GOOGLE_BOOKS_ENABLED', '').lower() == 'true'
            },
            'plex': {
                'url': os.getenv('PLEX_URL', ''),
                'token': os.getenv('PLEX_TOKEN', ''),
                'enabled': os.getenv('PLEX_ENABLED', os.getenv('PLEX_URL', '')).lower() == 'true'
                           if os.getenv('PLEX_ENABLED') is not None else bool(os.getenv('PLEX_URL', ''))
            },
            'display': {
                'mode': os.getenv('DISPLAY_MODE', 'dark'),
                'accent': os.getenv('DISPLAY_ACCENT', '#6ab759'),
                'bg': os.getenv('DISPLAY_BG', '#1c1d24'),
                'surface': os.getenv('DISPLAY_SURFACE', '#24242d'),
                'surface_alt': os.getenv('DISPLAY_SURFACE_ALT', '#2f323b'),
                'panel': os.getenv('DISPLAY_PANEL', '#1d1d25'),
                'text': os.getenv('DISPLAY_TEXT', '#f5f7fb'),
                'muted': os.getenv('DISPLAY_MUTED', '#a5acb8'),
                'border': os.getenv('DISPLAY_BORDER', 'rgba(255,255,255,0.08)'),
                'radius': os.getenv('DISPLAY_RADIUS', '8'),
                'border_width': os.getenv('DISPLAY_BORDER_WIDTH', '1'),
                'shadow_opacity': os.getenv('DISPLAY_SHADOW_OPACITY', '0.38')
            }
        }
        
        # Wrap each section with ConfigSection for attribute access
        self._config = {}
        for key, value in config_data.items():
            self._config[key] = ConfigSection(value)
        
        self._last_reload = time.time()
    
    def __getattr__(self, name):
        self._ensure_loaded()
        if name in self._config:
            return self._config[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def __getitem__(self, key):
        self._ensure_loaded()
        return self._config[key]
    
    def get(self, key, default=None):
        self._ensure_loaded()
        return self._config.get(key, default)
