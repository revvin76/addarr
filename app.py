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


load_dotenv()

app = Flask(__name__)

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
        'branch': 'main'  # Your main branch name
    }
})

def setup_logging():
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    log_file = 'addarr.log'
    
    # Set up rotating logs (10MB max, 5 backups)
    handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5
    )
    handler.setFormatter(logging.Formatter(log_format))
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    # Also log to console in debug mode
    if os.getenv('FLASK_DEBUG') == '1':
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        logger.addHandler(console_handler)

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
def save_config():
    try:
        config = request.json
        
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
            sonarr_api_key=CONFIG['sonarr']['api_key']
        )
    except Exception as e:
        logging.error(f"Version check failed: {str(e)}", exc_info=True)
        return render_template(
            'index.html',
            error="Update check failed",
            current_version='unknown',
            latest_version='unknown'
        )
    
@app.route('/offline.html')
@log_request_response
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
    
@app.route('/search', methods=['POST'])
@log_request_response
def search():
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
@log_request_response
def get_media_details():
    media_type = request.args.get('type')
    media_id = request.args.get('id')

    print(f"Fetching details for {media_type} with ID: {media_id}")
    
    if media_type == 'movie':
        return jsonify(get_radarr_details(media_id))
    else:
        return jsonify(get_sonarr_details(media_id))

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

def update_checker():
    """Background thread to check for updates periodically"""
    while True:
        try:
            update_available = check_for_updates()
            if update_available:
                # Here you could implement a restart mechanism
                restart_app()
                
            time.sleep(CONFIG['app']['update_interval'])
            
        except Exception as e:
            logging.error(f"Update checker error: {str(e)}")
            time.sleep(300)  # Wait 5 minutes after error

def restart_app():
    """Trigger application restart"""
    logging.info("Restarting application...")
    python = sys.executable
    os.execl(python, python, *sys.argv)

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
def serve_image(filename):
    return send_from_directory('static/images', filename)

if os.getenv('ENABLE_AUTO_UPDATE', 'true').lower() == 'true':
    try:
        update_thread = threading.Thread(
            target=update_checker,
            daemon=True,
            name="AutoUpdater"
        )
        update_thread.start()
        logging.info("Auto-update thread started")
    except Exception as e:
        logging.error(f"Failed to start update thread: {str(e)}")

if os.getenv('FLASK_DEBUG') == '1':
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

@app.route('/api/version')
def get_current_version():
    try:
        repo = git.Repo(search_parent_directories=True)
        return jsonify({
            'hash': repo.head.commit.hexsha[:7],
            'date': repo.head.commit.committed_datetime.isoformat()
        })
    except Exception as e:
        return jsonify({'hash': 'unknown', 'error': str(e)})

@app.route('/api/version/latest')
def get_latest_version():
    try:
        response = requests.get('https://api.github.com/repos/yourusername/yourrepo/releases/latest')
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'tag_name': 'unknown', 'error': str(e)})

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    if request.method == 'GET':
        return jsonify({'auto_update': os.getenv('ENABLE_AUTO_UPDATE', 'true').lower() == 'true'})
    else:
        auto_update = request.json.get('auto_update', True)
        # Update your configuration here (write to .env or config file)
        return jsonify({'success': True})

@app.route('/api/update', methods=['POST'])
def trigger_update():
    try:
        repo = git.Repo(search_parent_directories=True)
        origin = repo.remotes.origin
        origin.fetch()
        repo.git.reset('--hard', f'origin/{CONFIG["app"]["branch"]}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
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
    from colorama import Fore, Style
    
    # App info text
    app_info = f"""
    {Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}
    {Fore.WHITE}• Version: {os.getenv('APP_VERSION', '1.0.1')}
    {Fore.WHITE}• Local: {Fore.CYAN}http://127.0.0.1:5000{Style.RESET_ALL}
    {Fore.WHITE}• Network: {Fore.CYAN}http://{get_ip_address()}:5000{Style.RESET_ALL}
    """
    my_art = AsciiArt.from_image('static/images/logo.png')
    my_art.to_terminal()

    print(app_info)
    print(f"{Fore.GREEN}✅ Ready to add media!{Style.RESET_ALL}\n")


if __name__ == '__main__':
    from colorama import init
    init()  # Initialize colorama
    
    if os.getenv('ENABLE_AUTO_UPDATE', 'true').lower() == 'true':
        update_thread = threading.Thread(
            target=update_checker,
            daemon=True,
            name="ForceUpdater"
        )
        update_thread.start()

    print_welcome()
    app.run(host='0.0.0.0', port=5000)

