import os
from functools import wraps
from flask import Flask, render_template, request, jsonify,send_from_directory
import requests
from dotenv import load_dotenv
import json
import subprocess
import threading
from datetime import datetime
from git import Repo
import logging
from logging.handlers import RotatingFileHandler
import time
from ascii_magic import AsciiArt
from collections import deque
import traceback
from version_manager import VersionManager

load_dotenv()

app = Flask(__name__)

version_manager = VersionManager()

# Configuration
CONFIG = {
    'radarr': {
        'url': os.getenv('RADARR_URL'),
        'api_key': os.getenv('RADARR_API_KEY'),
        'root_folder': os.getenv('RADARR_ROOT_FOLDER'),
        'quality_profile_id':  os.getenv('RADARR_QUALITY_PROFILE')
    },
    'sonarr': {
        'url': os.getenv('SONARR_URL'),
        'api_key': os.getenv('SONARR_API_KEY'),
        'root_folder': os.getenv('SONARR_ROOT_FOLDER'),
        'quality_profile_id': os.getenv('SONARR_QUALITY_PROFILE'),  
        'language_profile_id': os.getenv('SONARR_LANGUAGE_PROFILE')   
    }
}

CONFIG.update({
    'app': {
        'update_interval': 3600,  # Check for updates every hour (in seconds)
        'github_repo': 'revvin76/addarr',  # Update with your GitHub repo
        'branch': 'main',  # Your main branch name,
        'debug': os.getenv('FLASK_DEBUG', '0') == '1'
    }
})

CONFIG.update({
    'duckdns': {
        'domain': os.getenv('DUCKDNS_DOMAIN', ''),
        'token': os.getenv('DUCKDNS_TOKEN', ''),
        'enabled': os.getenv('DUCKDNS_ENABLED', 'false').lower() == 'true'
    }
})

def setup_logging():
    log_format = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    log_file = 'addarr.log'
    
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if os.getenv('FLASK_DEBUG') == '1' else logging.INFO)
    
    # File handler (rotating)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(console_handler)
    
    # Set specific log levels for noisy libraries
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

def debug_log(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Entering {func.__name__} with args: {args}, kwargs: {kwargs}")
        try:
            result = func(*args, **kwargs)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Exiting {func.__name__} with result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)
            raise
    return wrapper

setup_logging()

def log_request_response(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Log request
        request_data = {
            'method': request.method,
            'path': request.path,
            'args': dict(request.args),
            'remote_addr': request.remote_addr
        }
        
        # Only include form/json if not sensitive
        if not any(s in request.path.lower() for s in ['login', 'auth']):
            if request.form:
                request_data['form'] = dict(request.form)
            if request.is_json:
                try:
                    request_data['json'] = request.json
                except:
                    request_data['json'] = "Invalid JSON"
        
        logging.info(f"Request: {json.dumps(request_data, indent=2)}")
        
        start_time = time.time()
        
        try:
            response = f(*args, **kwargs)
            
            # Handle both Response objects and direct string returns
            if isinstance(response, str):
                # For template responses, create a mock response for logging
                response_data = {
                    'status_code': 200,
                    'type': 'template',
                    'processing_time': f"{time.time() - start_time:.3f}s"
                }
            else:
                # For proper Response objects
                response_data = {
                    'status_code': response.status_code,
                    'type': 'response',
                    'processing_time': f"{time.time() - start_time:.3f}s"
                }
                
            logging.info(f"Response: {json.dumps(response_data, indent=2)}")
            return response
            
        except Exception as e:
            logging.error(f"Error in {f.__name__}: {str(e)}", exc_info=True)
            raise
    
    return decorated_function

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static', 'images'),
                              'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/save_config', methods=['POST'])
@debug_log
def save_config():
    try:
        config = request.json
        
        # Update debug mode if changed
        if 'FLASK_DEBUG' in config:
            debug_enabled = config['FLASK_DEBUG'].lower() == 'true'
            CONFIG['app']['debug'] = debug_enabled
            logging.getLogger().setLevel(logging.DEBUG if debug_enabled else logging.INFO)
            logging.info(f"Debug mode {'enabled' if debug_enabled else 'disabled'}")

        # Read existing .env file
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        env_lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                env_lines = f.readlines()
        
        # Update or add each config value
        updated_lines = []
        config_keys_written = set()
        
        # Process existing lines
        for line in env_lines:
            if '=' in line:
                key = line.split('=')[0].strip()
                if key in config:
                    updated_lines.append(f"{key}={config[key]}\n")
                    config_keys_written.add(key)
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        # Add any new keys
        for key, value in config.items():
            if key not in config_keys_written:
                updated_lines.append(f"{key}={value}\n")
        
        # Write back to .env
        with open(env_path, 'w') as f:
            f.writelines(updated_lines)

        # Update in-memory config if DuckDNS settings changed
        if 'DUCKDNS_DOMAIN' in config or 'DUCKDNS_TOKEN' in config or 'DUCKDNS_ENABLED' in config:
            CONFIG['duckdns']['domain'] = config.get('DUCKDNS_DOMAIN', CONFIG['duckdns']['domain'])
            CONFIG['duckdns']['token'] = config.get('DUCKDNS_TOKEN', CONFIG['duckdns']['token'])
            CONFIG['duckdns']['enabled'] = config.get('DUCKDNS_ENABLED', str(CONFIG['duckdns']['enabled'])).lower() == 'true'
            
            # Trigger immediate update if enabled
            if CONFIG['duckdns']['enabled']:
                threading.Thread(target=update_duckdns_if_needed).start()
                logging.info("Configuration saved successfully")

        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred'}), 500

required_env = ['RADARR_URL', 'RADARR_API_KEY', 'SONARR_URL', 'SONARR_API_KEY']
missing = [key for key in required_env if not os.getenv(key)]
if missing:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")

@app.route('/')
@log_request_response
@debug_log
def index():
    try:
        repo = Repo(os.path.dirname(os.path.abspath(__file__)))
        local_commit = repo.head.commit.hexsha[:7]
        remote_commit = repo.remotes.origin.fetch()[0].commit.hexsha[:7]

        current_version = local_commit
        latest_version = remote_commit
        return render_template(
            'index.html',
            current_version=current_version,
            latest_version=latest_version,
            radarr_quality_profile=CONFIG['radarr']['quality_profile_id'],
            radarr_root_folder=CONFIG['radarr']['root_folder'],
            radarr_url=CONFIG['radarr']['url'],
            radarr_api_key=CONFIG['radarr']['api_key'],
            sonarr_quality_profile=CONFIG['sonarr']['quality_profile_id'],
            sonarr_root_folder=CONFIG['sonarr']['root_folder'],
            sonarr_language_profile=CONFIG['sonarr']['language_profile_id'],
            sonarr_url=CONFIG['sonarr']['url'],
            sonarr_api_key=CONFIG['sonarr']['api_key'],
            # Add DuckDNS config to template variables
            duckdns_domain=CONFIG['duckdns']['domain'],
            duckdns_token=CONFIG['duckdns']['token'],
            duckdns_enabled=CONFIG['duckdns']['enabled']            
        )
    
    except Exception as e:
        logging.error(f"Version check failed: {str(e)}", exc_info=True)
        return render_template(
            'index.html',
            error="Update check failed",
            current_version='unknown',
            latest_version='unknown'
        )

@app.route('/logs')
@log_request_response
@debug_log
def get_logs():
    try:
        log_path = 'addarr.log'
        lines_to_return = min(int(request.args.get('lines', 1000)), 10000)  # Limit to 10,000 lines max
        
        # Check if file exists first
        if not os.path.exists(log_path):
            return jsonify({
                'success': False,
                'error': f'Log file {log_path} does not exist',
                'traceback': ''
            })
        
        # Read the log file efficiently
        with open(log_path, 'r') as f:
            lines = deque(f, maxlen=lines_to_return)
        
        return jsonify({
            'success': True,
            'log': ''.join(lines),
            'total_lines': len(lines)
        })
        
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid line count parameter: {str(e)}',
            'traceback': traceback.format_exc()
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to read log file: {str(e)}',
            'traceback': traceback.format_exc()
        }), 500

@app.route('/offline.html')
@log_request_response
@debug_log
def offline():
    try:
        return render_template('offline.html')
    except TemplateNotFound:
        logging.error("Template 'offline.html' not found")
        return "Page not found", 404

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html'), 404

@app.route('/get_tmdb_details')
@log_request_response
@debug_log
def get_tmdb_details():
    media_type = request.args.get('type')  # 'tv' or 'movie'
    tmdb_id = request.args.get('id')      # TMDB ID

    print(f"Fetching TMDB details for type: {media_type}, ID: {tmdb_id}")
    
    if not media_type or not tmdb_id:
        return jsonify({'error': 'Missing type or ID'}), 400
    
    try:
        # Base details
        base_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        params = {
            'api_key': os.getenv('TMDB_KEY'),
            'language': 'en-GB',
            'append_to_response': 'videos,images'  # Get additional data
        }
        
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Process the data into a consistent format
        result = {
            'title': data.get('name') or data.get('title'),
            'overview': data.get('overview'),
            'poster_path': data.get('poster_path'),
            'backdrop_path': data.get('backdrop_path'),
            'vote_average': data.get('vote_average'),
            'genres': [g['name'] for g in data.get('genres', [])],
            'first_air_date': data.get('first_air_date'),
            'last_air_date': data.get('last_air_date'),
            'status': data.get('status'),  # 'Returning Series' or 'Ended'
            'videos': data.get('videos', {}).get('results', []),
            'images': data.get('images', {}).get('posters', [])
        }
        
        # Find the best trailer (official YouTube trailer)
        result['trailer'] = next(
            (v for v in result['videos']
             if v.get('site') == 'YouTube' 
             and v.get('type') == 'Trailer'
             and v.get('official') is True),
            None
        )
        
        return jsonify(result)
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'TMDB API error: {str(e)}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/search_old', methods=['POST'])
@log_request_response
@debug_log
def search_old():
    query = request.form['query']
    media_type = request.form['media_type']
    print(f"Searching {media_type} for: {query}")
    
    try:
        if media_type == 'movie':
            results = search_radarr(query)
            # Ensure results is always a list
            results = results if isinstance(results, list) else []
            print(f"Found {len(results)} movies")
        else:
            results = search_sonarr(query)
            # Sonarr returns a list directly
            print(f"Found {len(results)} TV shows")
            
        return render_template(
            'results.html',
            results=results,
            media_type=media_type,
            query=query
        )
        
    except Exception as e:
        print(f"Search error: {str(e)}")
        return render_template('error.html', error=str(e))
    
@app.route('/search', methods=['POST'])
@log_request_response
@debug_log
def search():
    query = request.form['query']
    print(f"Searching for: {query}")
    
    try:
        # Search both Radarr and Sonarr simultaneously
        movie_results = search_radarr(query)
        tv_results = search_sonarr(query)
        
        # Ensure results are always lists
        movie_results = movie_results if isinstance(movie_results, list) else []
        tv_results = tv_results if isinstance(tv_results, list) else []
        
        # Add media type to each result for filtering
        for movie in movie_results:
            movie['media_type'] = 'movie'
        for tv_show in tv_results:
            tv_show['media_type'] = 'tv'
            
        # Alternate between Sonarr and Radarr results to preserve their individual sort order
        combined_results = []
        max_length = max(len(movie_results), len(tv_results))
        
        for i in range(max_length):
            # Add TV show (Sonarr) result if available
            if i < len(tv_results):
                combined_results.append(tv_results[i])
            # Add movie (Radarr) result if available  
            if i < len(movie_results):
                combined_results.append(movie_results[i])
        
        print(f"Found {len(movie_results)} movies and {len(tv_results)} TV shows")
        print(f"Combined results: {len(combined_results)} items (alternating TV/Movie)")
            
        return render_template(
            'results.html',
            results=combined_results,
            media_type='combined',
            query=query
        )
        
    except Exception as e:
        print(f"Search error: {str(e)}")
        return render_template('error.html', error=str(e))
def search_radarr(query):
    url = f"{CONFIG['radarr']['url']}/api/v3/movie/lookup"
    params = {
        'term': query,
        'apikey': CONFIG['radarr']['api_key']
    }
    response = requests.get(url, params=params)
    return response.json()

def search_sonarr(query):
    url = f"{CONFIG['sonarr']['url']}/api/v3/series/lookup"
    params = {
        'term': query,
        'apikey': CONFIG['sonarr']['api_key']
    }
    response = requests.get(url, params=params)
    return response.json()

@app.route('/add', methods=['POST'])
@log_request_response
@debug_log
def add_to_arr():
    data = request.json
    media_type = data['media_type']
    media_id = data['media_id']
    
    if media_type == 'movie':
        success = add_to_radarr(media_id)
    else:
        success = add_to_sonarr(media_id)
    
    return jsonify({'success': success})

def add_to_radarr(tmdb_id):
    url = f"{CONFIG['radarr']['url']}/api/v3/movie"
    headers = {'Content-Type': 'application/json'}
    payload = {
        'tmdbId': tmdb_id,
        'monitored': True,
        'rootFolderPath': CONFIG['radarr']['root_folder'],
        'qualityProfileId': CONFIG['radarr']['quality_profile_id'],
        'addOptions': {'searchForMovie': True}
    }
    response = requests.post(
        url, 
        json=payload, 
        headers=headers,
        params={'apikey': CONFIG['radarr']['api_key']}
    )
    return response.status_code in [200, 201]

def add_to_sonarr(tvdb_id):
    # First lookup series details
    lookup_url = f"{CONFIG['sonarr']['url']}/api/v3/series/lookup"
    params = {
        'term': f'tvdb:{tvdb_id}',
        'apikey': CONFIG['sonarr']['api_key']
    }
    
    lookup_res = requests.get(lookup_url, params=params)
    if lookup_res.status_code != 200:
        print(f"Lookup failed: {lookup_res.text}")
        return False
    
    series_data = lookup_res.json()[0]  # Get first result
    
    payload = {
        'tvdbId': tvdb_id,
        'title': series_data['title'],
        'monitored': True,
        'rootFolderPath': CONFIG['sonarr']['root_folder'],
        'qualityProfileId': CONFIG['sonarr']['quality_profile_id'],
        'languageProfileId': CONFIG['sonarr']['language_profile_id'],
        'addOptions': {
            'searchForMissingEpisodes': True,
            'monitor': 'all'
        },
        'seasonFolder': True,
        'seriesType': 'standard'
    }
    
    response = requests.post(
        f"{CONFIG['sonarr']['url']}/api/v3/series",
        json=payload,
        params={'apikey': CONFIG['sonarr']['api_key']}
    )
    
    print(f"Sonarr response: {response.status_code} - {response.text}")
    return response.status_code in [200, 201]

# Add these new functions to your Flask app
@app.route('/get_media_details')
@debug_log
@log_request_response
def get_media_details():
    media_type = request.args.get('type')
    media_id = request.args.get('id')

    print(f"Fetching details for {media_type} with ID: {media_id}")
    
    if media_type == 'movie':
        return jsonify(get_radarr_details(media_id))
    else:
        return jsonify(get_sonarr_details(media_id))

@debug_log
def check_for_updates():
    """Check for updates and apply them if available"""
    try:
        repo = Repo(os.path.dirname(os.path.abspath(__file__)))
        origin = repo.remotes.origin
        
        # Fetch latest changes
        origin.fetch()
        
        # Get current and remote commits
        local_commit = repo.head.commit
        remote_commit = repo.commit(f'origin/{CONFIG["app"]["branch"]}')
        
        if local_commit.hexsha != remote_commit.hexsha:
            logging.info("Update available - pulling changes...")
            
            # Stash local changes if any
            if repo.is_dirty():
                repo.git.stash()
            
            # Pull changes
            repo.git.reset('--hard', f'origin/{CONFIG["app"]["branch"]}')
            logging.info("Update applied successfully")
            
            # Signal that restart is needed
            return True
        else:
            logging.debug("No updates available")
            return False
            
    except Exception as e:
        logging.error(f"Update check failed: {str(e)}")
        return False

@debug_log
def update_checker():
    """Background thread to check for updates periodically"""
    while True:
        try:
            update_info = version_manager.check_for_updates()
            
            if update_info.get('update_available'):
                logging.info(f"Update available: {update_info['new_version']}")
                
                # Apply update automatically if enabled
                if os.getenv('AUTO_APPLY_UPDATES', 'true').lower() == 'true':
                    result = version_manager.apply_update()
                    if result.get('success'):
                        logging.info(f"Auto-update applied: {result['new_version']}")
                        # The notification will be shown on next page load
                    else:
                        logging.error(f"Auto-update failed: {result.get('error')}")
            
            time.sleep(CONFIG['app']['update_interval'])
            
        except Exception as e:
            logging.error(f"Update checker error: {str(e)}")
            time.sleep(300)  # Wait 5 minutes after error

@debug_log
def restart_app():
    """Trigger application restart"""
    logging.info("Restarting application...")
    python = sys.executable
    os.execl(python, python, *sys.argv)

@debug_log
def get_radarr_details(tmdb_id):
    """Simplified Radarr details without crew information"""
    # Check if movie exists in Radarr
    existing_url = f"{CONFIG['radarr']['url']}/api/v3/movie"
    existing = requests.get(existing_url, params={'apikey': CONFIG['radarr']['api_key']}).json()
    
    for movie in existing:
        if str(movie.get('tmdbId')) == str(tmdb_id):
            # Existing movie - get full details
            movie_url = f"{CONFIG['radarr']['url']}/api/v3/movie/{movie['id']}"
            full_details = requests.get(movie_url, params={'apikey': CONFIG['radarr']['api_key']}).json()
            
            # Ensure images are properly structured
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
    
    # Not added - get fresh details
    lookup_url = f"{CONFIG['radarr']['url']}/api/v3/movie/lookup/tmdb"
    lookup = requests.get(lookup_url, params={
        'tmdbId': tmdb_id,
        'apikey': CONFIG['radarr']['api_key']
    }).json()
    
    # Ensure lookup results have proper image structure
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

@debug_log
def get_sonarr_details(tvdb_id):
    """Check if series exists in Sonarr and get details"""
    # Check if already added
    existing_url = f"{CONFIG['sonarr']['url']}/api/v3/series"
    existing = requests.get(existing_url, params={'apikey': CONFIG['sonarr']['api_key']}).json()
    
    for series in existing:
        if str(series.get('tvdbId')) == str(tvdb_id):
            # Get detailed status
            status_url = f"{CONFIG['sonarr']['url']}/api/v3/series/{series['id']}"
            details = requests.get(status_url, params={'apikey': CONFIG['sonarr']['api_key']}).json()
            
            return {
                'status': 'existing',
                'data': details,
                'on_disk': details.get('statistics', {}).get('percentOfEpisodes') > 0,
                'monitored': details.get('monitored', False),
                'download_status': f"{details.get('statistics', {}).get('percentOfEpisodes', 0)}% complete",
                'season_count': details.get('statistics', {}).get('seasonCount'),
                'episode_count': details.get('statistics', {}).get('episodeCount')
            }
    
    # Not added - get fresh details
    lookup_url = f"{CONFIG['sonarr']['url']}/api/v3/series/lookup"
    lookup = requests.get(lookup_url, params={
        'term': f'tvdb:{tvdb_id}',
        'apikey': CONFIG['sonarr']['api_key']
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

# Add this new endpoint
@app.route('/check_library_status')
@log_request_response
@debug_log
def check_library_status():
    media_type = request.args.get('type')
    media_id = request.args.get('id')
    
    if media_type == 'movie':
        # Check Radarr
        existing = requests.get(
            f"{CONFIG['radarr']['url']}/api/v3/movie",
            params={'apikey': CONFIG['radarr']['api_key']}
        ).json()
        in_library = any(str(m.get('tmdbId')) == str(media_id) for m in existing)
    else:
        # Check Sonarr
        existing = requests.get(
            f"{CONFIG['sonarr']['url']}/api/v3/series",
            params={'apikey': CONFIG['sonarr']['api_key']}
        ).json()
        in_library = any(str(s.get('tvdbId')) == str(media_id) for s in existing)
    
    return jsonify({'in_library': in_library})

@app.route('/images/<path:filename>')
@log_request_response
@debug_log
def serve_image(filename):
    return send_from_directory('static/images', filename)

if os.getenv('FLASK_DEBUG') == '1':
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

@app.route('/api/version')
@debug_log
def get_current_version():
    try:
        version_info = version_manager.get_current_version()
        return jsonify(version_info)
    except Exception as e:
        return jsonify({
            'version': 'unknown',
            'error': str(e)
        })

@app.route('/api/version/check-update')
@debug_log
def check_for_updates():
    try:
        update_info = version_manager.check_for_updates()
        return jsonify(update_info)
    except Exception as e:
        return jsonify({
            'update_available': False,
            'error': str(e)
        })

@app.route('/api/version/apply-update', methods=['POST'])
@debug_log
def apply_update():
    try:
        result = version_manager.apply_update()
        
        # Store update info for the notification
        if result.get('success'):
            update_info = version_manager.check_for_updates()
            session['pending_update'] = {
                'applied_at': datetime.now().isoformat(),
                'new_version': result.get('new_version', {}).get('version'),
                'changes': update_info.get('changes', [])
            }
        
        return jsonify(result)
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/version/update-notification')
@debug_log
def get_update_notification():
    """Check if there's a pending update notification to show"""
    pending_update = session.pop('pending_update', None)
    return jsonify({'pending_update': pending_update})


@app.route('/manage')
@log_request_response
@debug_log
def manage_media():
    try:
        # Get all movies from Radarr
        radarr_url = f"{CONFIG['radarr']['url']}/api/v3/movie"
        movies = requests.get(radarr_url, params={'apikey': CONFIG['radarr']['api_key']}).json()
        
        # Get all series from Sonarr
        sonarr_url = f"{CONFIG['sonarr']['url']}/api/v3/series"
        series = requests.get(sonarr_url, params={'apikey': CONFIG['sonarr']['api_key']}).json()
        
        # Create a combined list with type indicator
        combined_media = []
        
        # Add movies with type indicator
        for movie in movies:
            movie['media_type'] = 'movie'
            combined_media.append(movie)
        
        # Add TV shows with type indicator
        for show in series:
            show['media_type'] = 'tv'
            combined_media.append(show)
        
        # Sort by title alphabetically (case-insensitive)
        combined_media.sort(key=lambda x: x.get('title', '').lower())
        
        return render_template(
            'manage.html',
            media=combined_media
        )
    except Exception as e:
        logging.error(f"Error fetching media: {str(e)}", exc_info=True)
        return render_template('error.html', error="Failed to load media library")

@app.route('/get_media_manage')
@debug_log
@log_request_response
def get_media_manage():
    media_type = request.args.get('type')
    media_id = request.args.get('id')

    if media_type == 'movie':
        # Get details from Radarr
        url = f"{CONFIG['radarr']['url']}/api/v3/movie/{media_id}"
        movie = requests.get(url, params={'apikey': CONFIG['radarr']['api_key']}).json()
        return jsonify({
            "title": movie.get("title"),
            "poster": movie["images"][0]["remoteUrl"] if movie.get("images") else None
        })

    elif media_type == 'tv':
        # Get details from Sonarr
        url = f"{CONFIG['sonarr']['url']}/api/v3/series/{media_id}"
        series = requests.get(url, params={'apikey': CONFIG['sonarr']['api_key']}).json()

        # Fetch all episodes
        episodes_url = f"{CONFIG['sonarr']['url']}/api/v3/episode"
        episodes = requests.get(episodes_url, params={
            "seriesId": media_id,
            "apikey": CONFIG['sonarr']['api_key']
        }).json()

        # Group into seasons
        seasons = {}
        for ep in episodes:
            sn = ep["seasonNumber"]
            if sn not in seasons:
                seasons[sn] = {"number": sn, "episodes": []}
            status = "downloaded" if ep.get("hasFile") \
                     else "missing" if ep.get("airDateUtc") < datetime.utcnow().isoformat() \
                     else "unaired"
            seasons[sn]["episodes"].append({
                "number": ep["episodeNumber"],
                "title": ep["title"],
                "status": status,
                "id": ep["id"]
            })

        return jsonify({
            "title": series.get("title"),
            "poster": series["images"][0]["remoteUrl"] if series.get("images") else None,
            "seasons": list(seasons.values())
        })

    return jsonify({"error": "Invalid media type"}), 400


@app.route('/delete_movie/<int:movie_id>', methods=['POST'])
@debug_log
def delete_movie_manage(movie_id):
    url = f"{CONFIG['radarr']['url']}/api/v3/movie/{movie_id}"
    r = requests.delete(url, params={'apikey': CONFIG['radarr']['api_key']})
    return jsonify({"success": r.status_code == 200})


@app.route('/delete_movie_file/<int:movie_id>', methods=['POST'])
@debug_log
def delete_movie_file(movie_id):
    # Radarr can delete only file by setting deleteFiles=True/False
    url = f"{CONFIG['radarr']['url']}/api/v3/movie/{movie_id}"
    r = requests.delete(url, params={'apikey': CONFIG['radarr']['api_key'], 'deleteFiles': 'true'})
    return jsonify({"success": r.status_code == 200})


@app.route('/search_movie/<int:movie_id>', methods=['POST'])
@debug_log
def search_movie_manage(movie_id):
    url = f"{CONFIG['radarr']['url']}/api/v3/command"
    payload = {"name": "MoviesSearch", "movieIds": [movie_id]}
    r = requests.post(url, json=payload, params={'apikey': CONFIG['radarr']['api_key']})
    return jsonify({"success": r.status_code == 201})


@app.route('/delete_show/<int:series_id>', methods=['POST'])
@debug_log
def delete_show(series_id):
    url = f"{CONFIG['sonarr']['url']}/api/v3/series/{series_id}"
    r = requests.delete(url, params={'apikey': CONFIG['sonarr']['api_key'], 'deleteFiles': 'true'})
    return jsonify({"success": r.status_code == 200})


@app.route('/delete_all_episodes/<int:series_id>', methods=['POST'])
@debug_log
def delete_all_episodes(series_id):
    # Delete all files for a series
    url = f"{CONFIG['sonarr']['url']}/api/v3/episodefile/bulk"
    payload = {"seriesId": series_id}
    r = requests.delete(url, json=payload, params={'apikey': CONFIG['sonarr']['api_key']})
    return jsonify({"success": r.status_code == 200})


@app.route('/delete_episode/<int:episode_id>', methods=['POST'])
@debug_log
def delete_episode_manage(episode_id):
    url = f"{CONFIG['sonarr']['url']}/api/v3/episodefile/{episode_id}"
    r = requests.delete(url, params={'apikey': CONFIG['sonarr']['api_key']})
    return jsonify({"success": r.status_code == 200})


@app.route('/search_episode/<int:episode_id>', methods=['POST'])
@debug_log
def search_episode_manage(episode_id):
    url = f"{CONFIG['sonarr']['url']}/api/v3/command"
    payload = {"name": "EpisodeSearch", "episodeIds": [episode_id]}
    r = requests.post(url, json=payload, params={'apikey': CONFIG['sonarr']['api_key']})
    return jsonify({"success": r.status_code == 201})


@app.route('/search_all_missing/<int:series_id>', methods=['POST'])
@debug_log
def search_all_missing(series_id):
    url = f"{CONFIG['sonarr']['url']}/api/v3/command"
    payload = {"name": "SeriesSearch", "seriesId": series_id}
    r = requests.post(url, json=payload, params={'apikey': CONFIG['sonarr']['api_key']})
    return jsonify({"success": r.status_code == 201})


@app.route('/api/movie/<int:movie_id>', methods=['DELETE'])
@debug_log
def delete_movie(movie_id):
    try:
        url = f"{CONFIG['radarr']['url']}/api/v3/movie/{movie_id}"
        response = requests.delete(url, params={'apikey': CONFIG['radarr']['api_key']})
        return jsonify({'success': response.status_code == 200}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/movie/<int:movie_id>/monitor', methods=['PUT'])
@debug_log
def monitor_movie(movie_id):
    try:
        # First get current movie details
        url = f"{CONFIG['radarr']['url']}/api/v3/movie/{movie_id}"
        movie = requests.get(url, params={'apikey': CONFIG['radarr']['api_key']}).json()
        
        # Update monitored status
        movie['monitored'] = request.json.get('monitored', False)
        
        # Send update
        response = requests.put(url, json=movie, params={'apikey': CONFIG['radarr']['api_key']})
        return jsonify({'success': response.status_code == 202}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/movie/<int:movie_id>/search', methods=['POST'])
@debug_log
def search_movie(movie_id):
    try:
        url = f"{CONFIG['radarr']['url']}/api/v3/command"
        payload = {
            'name': 'MoviesSearch',
            'movieIds': [movie_id]
        }
        response = requests.post(url, json=payload, params={'apikey': CONFIG['radarr']['api_key']})
        return jsonify({'success': response.status_code == 201}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/series/<int:series_id>', methods=['DELETE'])
@debug_log
def delete_series(series_id):
    try:
        url = f"{CONFIG['sonarr']['url']}/api/v3/series/{series_id}"
        response = requests.delete(url, params={'apikey': CONFIG['sonarr']['api_key']})
        return jsonify({'success': response.status_code == 200}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/series/<int:series_id>/monitor', methods=['PUT'])
@debug_log
def monitor_series(series_id):
    try:
        # First get current series details
        url = f"{CONFIG['sonarr']['url']}/api/v3/series/{series_id}"
        series = requests.get(url, params={'apikey': CONFIG['sonarr']['api_key']}).json()
        
        # Update monitored status
        series['monitored'] = request.json.get('monitored', False)
        
        # Send update
        response = requests.put(url, json=series, params={'apikey': CONFIG['sonarr']['api_key']})
        return jsonify({'success': response.status_code == 202}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/series/<int:series_id>/search', methods=['POST'])
@debug_log
def search_series(series_id):
    try:
        url = f"{CONFIG['sonarr']['url']}/api/v3/command"
        payload = {
            'name': 'SeriesSearch',
            'seriesId': series_id
        }
        response = requests.post(url, json=payload, params={'apikey': CONFIG['sonarr']['api_key']})
        return jsonify({'success': response.status_code == 201}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/series/<int:series_id>/seasons')
@debug_log
def get_series_seasons(series_id):
    try:
        url = f"{CONFIG['sonarr']['url']}/api/v3/episode"
        params = {
            'seriesId': series_id,
            'apikey': CONFIG['sonarr']['api_key']
        }
        episodes = requests.get(url, params=params).json()
        
        # Group episodes by season
        seasons = {}
        for episode in episodes:
            season_num = episode['seasonNumber']
            if season_num not in seasons:
                seasons[season_num] = {
                    'seasonNumber': season_num,
                    'episodes': [],
                    'statistics': {
                        'episodeCount': 0,
                        'episodeFileCount': 0,
                        'percentOfEpisodes': 0
                    }
                }
            seasons[season_num]['episodes'].append(episode)
            seasons[season_num]['statistics']['episodeCount'] += 1
            if episode.get('hasFile', False):
                seasons[season_num]['statistics']['episodeFileCount'] += 1
        
        # Calculate percentages
        for season in seasons.values():
            if season['statistics']['episodeCount'] > 0:
                season['statistics']['percentOfEpisodes'] = round(
                    (season['statistics']['episodeFileCount'] / season['statistics']['episodeCount']) * 100
                )
        
        return jsonify(list(seasons.values()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/episode/<int:episode_id>/search', methods=['POST'])
@debug_log
def search_episode(episode_id):
    try:
        url = f"{CONFIG['sonarr']['url']}/api/v3/command"
        payload = {
            'name': 'EpisodeSearch',
            'episodeIds': [episode_id]
        }
        response = requests.post(url, json=payload, params={'apikey': CONFIG['sonarr']['api_key']})
        return jsonify({'success': response.status_code == 201}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/episode/<int:episode_id>', methods=['DELETE'])
@debug_log
def delete_episode(episode_id):
    try:
        # First get episode to find file id
        url = f"{CONFIG['sonarr']['url']}/api/v3/episode/{episode_id}"
        episode = requests.get(url, params={'apikey': CONFIG['sonarr']['api_key']}).json()
        
        if not episode.get('episodeFileId'):
            return jsonify({'error': 'No file to delete'}), 400
            
        # Delete the file
        file_url = f"{CONFIG['sonarr']['url']}/api/v3/episodefile/{episode['episodeFileId']}"
        response = requests.delete(file_url, params={'apikey': CONFIG['sonarr']['api_key']})
        return jsonify({'success': response.status_code == 200}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500
            
# Check and update DuckDNS
def update_duckdns_if_needed_old():
    if not CONFIG['duckdns']['enabled'] or not CONFIG['duckdns']['domain'] or not CONFIG['duckdns']['token']:
        logging.debug("DuckDNS update skipped - not enabled or missing credentials")
        return False
    
    current_ip = get_ip_address()
    last_ip = None
    
    # Check if IP has changed
    ip_file = os.path.join(os.path.dirname(__file__), 'last_ip.txt')
    if os.path.exists(ip_file):
        with open(ip_file, 'r') as f:
            last_ip = f.read().strip()
    
    if current_ip == last_ip:
        logging.debug("DuckDNS update skipped - IP unchanged")
        return False
    
    # Update DuckDNS
    try:
        url = f"https://www.duckdns.org/update?domains={CONFIG['duckdns']['domain']}&token={CONFIG['duckdns']['token']}&ip={current_ip}"
        response = requests.get(url, timeout=10)
        if response.text.strip() == "OK":
            with open(ip_file, 'w') as f:
                f.write(current_ip)
            logging.info(f"DuckDNS updated successfully to {current_ip}")
            return True
        else:
            logging.error(f"DuckDNS update failed. Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"DuckDNS update error: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error during DuckDNS update: {str(e)}")
        return False
def update_duckdns_if_needed():
    """Check and update DuckDNS with detailed logging"""
    if not CONFIG['duckdns']['enabled']:
        logging.info("DuckDNS: Update skipped - DuckDNS is not enabled")
        return False
        
    if not CONFIG['duckdns']['domain'] or not CONFIG['duckdns']['token']:
        logging.warning("DuckDNS: Update skipped - Missing domain or token")
        return False
    
    logging.info("DuckDNS: Starting IP check and update process...")
    current_ip = get_ip_address()
    last_ip = None
    
    # Check if IP has changed
    ip_file = os.path.join(os.path.dirname(__file__), 'last_ip.txt')
    if os.path.exists(ip_file):
        with open(ip_file, 'r') as f:
            last_ip = f.read().strip()
        logging.info(f"DuckDNS: Last known IP: {last_ip}")
    else:
        logging.info("DuckDNS: No previous IP found - first time update")
    
    logging.info(f"DuckDNS: Current external IP: {current_ip}")
    
    if current_ip == last_ip:
        logging.info("DuckDNS: IP unchanged - no update required")
        return False
    
    # Update DuckDNS
    try:
        logging.info(f"DuckDNS: Attempting to update {CONFIG['duckdns']['domain']}.duckdns.org to IP: {current_ip}")
        url = f"https://www.duckdns.org/update?domains={CONFIG['duckdns']['domain']}&token={CONFIG['duckdns']['token']}&ip={current_ip}"
        response = requests.get(url, timeout=10)
        
        if response.text.strip() == "OK":
            with open(ip_file, 'w') as f:
                f.write(current_ip)
            logging.info(f"DuckDNS: ✅ Successfully updated to {current_ip}")
            print(f"✅ DuckDNS: Successfully updated {CONFIG['duckdns']['domain']}.duckdns.org to {current_ip}")
            return True
        else:
            logging.error(f"DuckDNS: ❌ Update failed. Response: {response.text}")
            print(f"❌ DuckDNS: Update failed. Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"DuckDNS: ❌ Network error during update: {str(e)}")
        print(f"❌ DuckDNS: Network error during update: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"DuckDNS: ❌ Unexpected error during update: {str(e)}")
        print(f"❌ DuckDNS: Unexpected error during update: {str(e)}")
        return False
def get_ip_address():
    """Get the local IP address for network access"""
    import socket
    try:
        # Create a temporary socket to get the IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Doesn't actually connect, just determines the best route
            s.connect(('10.255.255.255', 1))
            ip_address = s.getsockname()[0]
    except Exception:
        ip_address = '127.0.0.1'  # Fallback to localhost
    return ip_address

def print_welcome():
    """Print welcome message and logo only once"""
    from colorama import Fore, Style
    
    # App info text
    app_info = f"""
    {Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}
    {Fore.WHITE}• Version: {os.getenv('APP_VERSION', '1.0.6')}
    {Fore.WHITE}• Local: {Fore.CYAN}http://127.0.0.1:5000{Style.RESET_ALL}
    {Fore.WHITE}• Network: {Fore.CYAN}http://{get_ip_address()}:5000{Style.RESET_ALL}
    """
    
    # Add DuckDNS info if enabled
    if CONFIG['duckdns']['enabled'] and CONFIG['duckdns']['domain']:
        app_info += f"{Fore.WHITE}• DuckDNS: {Fore.CYAN}https://{CONFIG['duckdns']['domain']}.duckdns.org{Style.RESET_ALL}\n"
    
    # Print logo and info
    my_art = AsciiArt.from_image('static/images/logo.png')
    my_art.to_terminal()
    print(app_info)
    print(f"{Fore.GREEN}✅ Ready to add media!{Style.RESET_ALL}\n")


if __name__ == '__main__':
    from colorama import init
    init()  # Initialize colorama
    
    if CONFIG['duckdns']['enabled']:
        try:
            duckdns_thread = threading.Thread(
                target=lambda: update_duckdns_if_needed(),
                daemon=True,
                name="DuckDNSUpdater"
            )
            duckdns_thread.start()
            logging.info("DuckDNS update thread started")
        except Exception as e:
            logging.error(f"Failed to start DuckDNS thread: {str(e)}")

    print_welcome()
    app.run(host='0.0.0.0', debug=True, port=5000)

