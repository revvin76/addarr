import os
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
from dotenv import load_dotenv
import json
import subprocess
import threading
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import time
from ascii_magic import AsciiArt
from collections import deque
import traceback

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
        'debug': os.getenv('FLASK_DEBUG', '0') == '1',
        'version': os.getenv('APP_VERSION', '1.0.0')
    }
})

CONFIG.update({
    'duckdns': {
        'domain': os.getenv('DUCKDNS_DOMAIN', ''),
        'token': os.getenv('DUCKDNS_TOKEN', ''),
        'enabled': os.getenv('DUCKDNS_ENABLED', 'false').lower() == 'true'
    }
})

# Update configuration
CONFIG.update({
    'update': {
        'github_repo': 'revvin76/addarr',
        'check_interval': 12 * 60 * 60,  # 12 hours in seconds
        'last_checked': 0,
        'updates_folder': 'updates'  # New updates folder
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

# Update functions
@debug_log
def check_github_for_updates():
    # """Check GitHub for new releases"""
    try:
        url = f"https://api.github.com/repos/{CONFIG['update']['github_repo']}/releases/latest"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            latest_release = response.json()
            current_version = CONFIG['app']['version']
            latest_version = latest_release.get('tag_name', '').lstrip('v')
            
            logging.info(f"Current version: {current_version}, Latest version: {latest_version}")
            
            if latest_version > current_version:
                logging.info(f"Update available: {latest_version}")
                return {
                    'update_available': True,
                    'current_version': current_version,
                    'latest_version': latest_version,
                    'release_url': latest_release.get('html_url'),
                    'release_notes': latest_release.get('body', ''),
                    'published_at': latest_release.get('published_at')
                }
            else:
                logging.info("No update available")
                return {'update_available': False}
        else:
            logging.warning(f"GitHub API returned status {response.status_code}")
            return {'update_available': False, 'error': f"GitHub API error: {response.status_code}"}
            
    except Exception as e:
        logging.error(f"Error checking for updates: {str(e)}")
        return {'update_available': False, 'error': str(e)}

@debug_log
def ensure_updates_folder():
    updates_folder = CONFIG['update']['updates_folder']
    if not os.path.exists(updates_folder):
        os.makedirs(updates_folder)
        logging.info(f"Created updates folder: {updates_folder}")
    return updates_folder

@debug_log
def download_update():
    try:
        update_info = check_github_for_updates()
        
        if not update_info.get('update_available'):
            return {'success': False, 'error': 'No update available'}
        
        latest_version = update_info['latest_version']
        release_url = f"https://github.com/{CONFIG['update']['github_repo']}/archive/refs/tags/v{latest_version}.zip"
        
        logging.info(f"Downloading update {latest_version} from {release_url}")
        
        # Ensure updates folder exists
        updates_folder = ensure_updates_folder()
        
        # Download the release
        response = requests.get(release_url, timeout=30)
        if response.status_code != 200:
            return {'success': False, 'error': f"Download failed: {response.status_code}"}
        
        # Save the update file to updates folder
        update_file = os.path.join(updates_folder, f"addarr_{latest_version}.zip")
        with open(update_file, 'wb') as f:
            f.write(response.content)
        
        logging.info(f"Update {latest_version} downloaded successfully to {update_file}")
        
        # Set update notification flag
        set_env('UPDATE_NOTIFICATION', 'true')
        set_env('LATEST_VERSION', latest_version)
        
        return {
            'success': True, 
            'message': f'Update {latest_version} downloaded successfully',
            'version': latest_version,
            'file_path': update_file,
            'file_size': os.path.getsize(update_file)
        }
        
    except Exception as e:
        logging.error(f"Error downloading update: {str(e)}")
        return {'success': False, 'error': str(e)}

@debug_log
def get_downloaded_updates():
    try:
        updates_folder = ensure_updates_folder()
        update_files = []
        
        for filename in os.listdir(updates_folder):
            if filename.startswith('addarr_') and filename.endswith('.zip'):
                file_path = os.path.join(updates_folder, filename)
                file_stat = os.stat(file_path)
                version = filename.replace('addarr_', '').replace('.zip', '')
                
                update_files.append({
                    'filename': filename,
                    'version': version,
                    'file_path': file_path,
                    'size': file_stat.st_size,
                    'downloaded_at': file_stat.st_mtime,
                    'formatted_size': format_file_size(file_stat.st_size),
                    'formatted_date': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        # Sort by version (newest first)
        update_files.sort(key=lambda x: x['version'], reverse=True)
        return update_files
        
    except Exception as e:
        logging.error(f"Error getting downloaded updates: {str(e)}")
        return []

@debug_log
def format_file_size(size_bytes):
    # """Format file size in human-readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.2f} {size_names[i]}"

@debug_log
def cleanup_old_updates(keep_count=3):
    # """Keep only the most recent updates and delete older ones"""
    try:
        update_files = get_downloaded_updates()
        
        if len(update_files) <= keep_count:
            return {'deleted': 0, 'kept': len(update_files)}
        
        # Keep the most recent ones
        updates_to_keep = update_files[:keep_count]
        updates_to_delete = update_files[keep_count:]
        
        deleted_files = []
        for update in updates_to_delete:
            try:
                os.remove(update['file_path'])
                deleted_files.append(update['filename'])
                logging.info(f"Deleted old update: {update['filename']}")
            except Exception as e:
                logging.error(f"Error deleting {update['filename']}: {str(e)}")
        
        return {
            'deleted': len(deleted_files),
            'kept': len(updates_to_keep),
            'deleted_files': deleted_files
        }
        
    except Exception as e:
        logging.error(f"Error cleaning up old updates: {str(e)}")
        return {'error': str(e)}
    
@debug_log
def set_env(key, value):
    # """Set an environment variable in the .env file"""
    try:
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        env_lines = []
        
        # Read existing .env file
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                env_lines = f.readlines()
        
        # Update or add the key
        updated = False
        for i, line in enumerate(env_lines):
            if line.startswith(f"{key}="):
                env_lines[i] = f"{key}={value}\n"
                updated = True
                break
        
        if not updated:
            env_lines.append(f"{key}={value}\n")
        
        # Write back to .env file
        with open(env_path, 'w') as f:
            f.writelines(env_lines)
        
        # Update current environment
        os.environ[key] = value
        logging.info(f"Set {key}={value}")
        return True
        
    except Exception as e:
        logging.error(f"Error setting environment variable: {str(e)}")
        return False

@debug_log
def update_checker():
    # """Background thread to check for updates periodically"""
    while True:
        try:
            # Check if enough time has passed since last check
            current_time = time.time()
            if current_time - CONFIG['update']['last_checked'] >= CONFIG['update']['check_interval']:
                logging.info("Checking for updates...")
                
                update_info = check_github_for_updates()
                if update_info.get('update_available'):
                    logging.info(f"Update available: {update_info['latest_version']}")
                    # Auto-download the update
                    download_result = download_update()
                    if download_result.get('success'):
                        logging.info(f"Auto-downloaded update: {download_result['version']}")
                    else:
                        logging.error(f"Auto-download failed: {download_result.get('error')}")
                
                CONFIG['update']['last_checked'] = current_time
                
            # Sleep for 1 hour before checking again
            time.sleep(3600)
            
        except Exception as e:
            logging.error(f"Update checker error: {str(e)}")
            time.sleep(3600)  # Sleep for 1 hour after error

# Start update checker thread
update_thread = threading.Thread(target=update_checker, daemon=True)
update_thread.start()

# API routes for updates
@app.route('/api/update/check')
@debug_log
def check_update():
    # """Check for updates manually"""
    update_info = check_github_for_updates()
    return jsonify(update_info)

@app.route('/api/update/download', methods=['POST'])
@debug_log
def download_update_route():
    # """Download update manually"""
    result = download_update()
    return jsonify(result)

@app.route('/api/update/status')
@debug_log
def update_status():
    # """Get update notification status"""
    return jsonify({
        'update_notification': os.getenv('UPDATE_NOTIFICATION', 'false') == 'true',
        'latest_version': os.getenv('LATEST_VERSION', ''),
        'current_version': CONFIG['app']['version']
    })

@app.route('/api/update/dismiss', methods=['POST'])
@debug_log
def dismiss_update_notification():
    # """Dismiss the update notification"""
    set_env('UPDATE_NOTIFICATION', 'false')
    return jsonify({'success': True})

@app.route('/api/update/list')
@debug_log
def list_downloaded_updates():
    # """Get list of downloaded updates"""
    update_files = get_downloaded_updates()
    return jsonify({
        'updates': update_files,
        'total_count': len(update_files)
    })

@app.route('/api/update/cleanup', methods=['POST'])
@debug_log
def cleanup_updates():
    # """Clean up old updates"""
    keep_count = request.json.get('keep_count', 3) if request.is_json else 3
    result = cleanup_old_updates(keep_count)
    return jsonify(result)

@app.route('/api/update/delete/<version>', methods=['DELETE'])
@debug_log
def delete_update(version):
    # """Delete a specific update"""
    try:
        updates_folder = ensure_updates_folder()
        filename = f"addarr_{version}.zip"
        file_path = os.path.join(updates_folder, filename)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"Deleted update: {filename}")
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        else:
            return jsonify({'success': False, 'error': 'File not found'}), 404
            
    except Exception as e:
        logging.error(f"Error deleting update: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Initial update check on startup
logging.info("Performing initial update check...")
initial_update_info = check_github_for_updates()
if initial_update_info.get('update_available'):
    logging.info(f"Initial check: Update available - {initial_update_info['latest_version']}")
    # Don't auto-download on initial check, just notify
    set_env('UPDATE_NOTIFICATION', 'true')
    set_env('LATEST_VERSION', initial_update_info['latest_version'])

CONFIG['update']['last_checked'] = time.time()

@app.route('/')
@log_request_response
@debug_log
def index():
    try:
        return render_template(
            'index.html',
            radarr_quality_profile=CONFIG['radarr']['quality_profile_id'],
            radarr_root_folder=CONFIG['radarr']['root_folder'],
            radarr_url=CONFIG['radarr']['url'],
            radarr_api_key=CONFIG['radarr']['api_key'],
            sonarr_quality_profile=CONFIG['sonarr']['quality_profile_id'],
            sonarr_root_folder=CONFIG['sonarr']['root_folder'],
            sonarr_language_profile=CONFIG['sonarr']['language_profile_id'],
            sonarr_url=CONFIG['sonarr']['url'],
            sonarr_api_key=CONFIG['sonarr']['api_key'],
            duckdns_domain=CONFIG['duckdns']['domain'],
            duckdns_token=CONFIG['duckdns']['token'],
            duckdns_enabled=CONFIG['duckdns']['enabled'],
            current_version=CONFIG['app']['version']
        )
    
    except Exception as e:
        logging.error(f"Error loading index: {str(e)}", exc_info=True)
        return render_template(
            'index.html',
            error="Page load failed"
        )

# ... (all your other existing routes remain exactly the same)

def get_ip_address():
    # """Get the local IP address for network access"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.255.255.255', 1))
            ip_address = s.getsockname()[0]
    except Exception:
        ip_address = '127.0.0.1'
    return ip_address

def print_welcome():
    # """Print welcome message and logo only once"""
    from colorama import Fore, Style
    
    app_info = f"""
    {Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}
    {Fore.WHITE}• Version: {CONFIG['app']['version']}
    {Fore.WHITE}• Local: {Fore.CYAN}http://127.0.0.1:5000{Style.RESET_ALL}
    {Fore.WHITE}• Network: {Fore.CYAN}http://{get_ip_address()}:5000{Style.RESET_ALL}
    """
    
    if CONFIG['duckdns']['enabled'] and CONFIG['duckdns']['domain']:
        app_info += f"{Fore.WHITE}• DuckDNS: {Fore.CYAN}https://{CONFIG['duckdns']['domain']}.duckdns.org{Style.RESET_ALL}\n"
    
    my_art = AsciiArt.from_image('static/images/logo.png')
    my_art.to_terminal()
    print(app_info)
    print(f"{Fore.GREEN}✅ Ready to add media!{Style.RESET_ALL}\n")

if __name__ == '__main__':
    from colorama import init
    init()
    
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