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
import importlib.metadata
import subprocess
import sys
import random
import requests
import atexit
import re

# Global variables
shutdown_event = False
app = Flask(__name__)

load_dotenv()

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
        'debug': os.getenv('FLASK_DEBUG', 'false').lower() == 'true',
        'version': os.getenv('APP_VERSION', '1.0.0'),
        'port' : os.getenv('SERVER_PORT', 5000)
    }
})
CONFIG.update({
    'duckdns': {
        'domain': os.getenv('DUCKDNS_DOMAIN', ''),
        'token': os.getenv('DUCKDNS_TOKEN', ''),
        'enabled': os.getenv('DUCKDNS_ENABLED', 'false').lower() == 'true'
    }
})
CONFIG.update({
    'update': {
        'github_repo':  os.getenv('GITHUB_REPO', ''),
        'check_interval':  os.getenv('CHECK_INTERVAL', '3600'),
        'last_checked':  os.getenv('LAST_CHECKED', '0'),
        'updates_folder':  os.getenv('UPDATES_FOLDER', ''),
    }
})

def setup_logging():
    log_format = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    log_file = 'addarr.log'
    
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if CONFIG['app']['debug'] else logging.INFO)
    
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
        
        # Only log if debug is actually enabled
        if CONFIG['app']['debug'] and logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Entering {func.__name__} with args: {args}, kwargs: {kwargs}")
        
        try:
            result = func(*args, **kwargs)
            
            # Don't log large HTML responses
            if (CONFIG['app']['debug'] and logger.isEnabledFor(logging.DEBUG) and 
                not (isinstance(result, str) and len(result) > 1000)):
                logger.debug(f"Exiting {func.__name__} with result: {result}")
            
            return result
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)
            raise
    return wrapper

setup_logging()

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
            
            if CONFIG['app']['debug']:
                logging.info(f"Current version: {current_version}, Latest version: {latest_version}")
            
            if latest_version > current_version:
                if CONFIG['app']['debug']:
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
                if CONFIG['app']['debug']:
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
    # Get the directory where the app is running from
    base_dir = os.path.dirname(os.path.abspath(__file__))
    updates_folder = os.path.join(base_dir, CONFIG['update']['updates_folder'])
    
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
        
        # Ensure updates folder exists - FIX: Get the full path
        updates_folder = ensure_updates_folder()
        
        # Download the release
        response = requests.get(release_url, timeout=30)
        if response.status_code != 200:
            return {'success': False, 'error': f"Download failed: {response.status_code}"}
        
        # Save the update file to updates folder - FIX: Use proper path joining
        update_file = os.path.join(updates_folder, f"addarr_{latest_version}.zip")
        with open(update_file, 'wb') as f:
            f.write(response.content)
        
        logging.info(f"Update {latest_version} downloaded successfully to {update_file}")
        
        # Set update notification flag
        set_env('UPDATE_NOTIFICATION', 'true')
        set_env('LATEST_VERSION', latest_version)
        
        # Auto-cleanup old updates after successful download
        cleanup_old_updates(keep_count=3)
        
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
                # Check if file exists (it might have been deleted)
                if not os.path.exists(file_path):
                    continue
                    
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
        if CONFIG['app']['debug']:
            logging.info(f"Set {key}={value}")
        return True
        
    except Exception as e:
        logging.error(f"Error setting environment variable: {str(e)}")
        return False


############################ START OF LOCALHOST.RUN TUNNELING ############################
## Localhost.run Tunnel Management
def ensure_tunnel_hostname():
    """Ensure TUNNEL_HOSTNAME exists in .env, generate if missing"""
    hostname = os.getenv('TUNNEL_HOSTNAME')
    
    if not hostname:
        # Generate a random hostname using two words
        adjectives = ['quick', 'happy', 'clever', 'brave', 'calm', 'eager', 'fierce', 'gentle', 
                     'jolly', 'kind', 'lively', 'nice', 'proud', 'silly', 'witty', 'young',
                     'ancient', 'autumn', 'hidden', 'misty', 'silent', 'red', 'green', 'blue',
                     'purple', 'golden', 'silver', 'crystal', 'distant', 'summer', 'winter']
        
        nouns = ['panda', 'tiger', 'eagle', 'dolphin', 'wolf', 'fox', 'lion', 'bear', 'hawk',
                'shark', 'whale', 'rabbit', 'deer', 'owl', 'falcon', 'panther', 'leopard',
                'dragon', 'phoenix', 'unicorn', 'griffin', 'wizard', 'warrior', 'mage',
                'explorer', 'traveler', 'pioneer', 'voyager', 'seeker', 'discoverer']
        
        adjective = random.choice(adjectives)
        noun = random.choice(nouns)
        hostname = f"{adjective}-{noun}"
        
        # Save to .env file
        set_env('TUNNEL_HOSTNAME', hostname)
        print(f"Generated new tunnel hostname: {hostname}")
    
    return hostname

def get_ssh_key_path():
    """Get the SSH key path from environment or use default"""
    ssh_key_path = os.getenv('TUNNEL_SSH_KEY')
    if ssh_key_path and os.path.exists(ssh_key_path):
        return ssh_key_path
    
    # Try common SSH key locations
    default_paths = [
        os.path.expanduser('~/.ssh/id_rsa'),
        os.path.expanduser('~/.ssh/id_ed25519'),
        os.path.expanduser('~/.ssh/id_ecdsa'),
    ]
    
    for path in default_paths:
        if os.path.exists(path):
            return path
    
    return None

def parse_tunnel_url(line):
    """Parse the actual tunnel URL from localhost.run output"""
    # Look for the new LHR domain format
    pattern1 = r'(https://[\w]+\.lhr\.life)'
    match1 = re.search(pattern1, line)
    if match1:
        tunnel_url = match1.group(1)
        subdomain = tunnel_url.replace('https://', '').replace('.lhr.life', '')
        return tunnel_url, subdomain
    
    # Look for the traditional localhost.run format
    pattern2 = r'(https://[\w-]+\.localhost\.run)'
    match2 = re.search(pattern2, line)
    if match2:
        tunnel_url = match2.group(1)
        subdomain = tunnel_url.replace('https://', '').replace('.localhost.run', '')
        return tunnel_url, subdomain
    
    # Look for username@subdomain format
    pattern3 = r'(\w+@[\w-]+\.localhost\.run)'
    match3 = re.search(pattern3, line)
    if match3:
        full_url = match3.group(1)
        username, subdomain = full_url.split('@')
        return f"https://{subdomain}", subdomain.replace('.localhost.run', '')
    
    return None, None

def start_tunnel(port=CONFIG['app']['port']):
    """Start the localhost.run tunnel with proper URL detection - non-blocking"""
    global tunnel_process, tunnel_thread, tunnel_running
    
    # If tunnel is already running, stop it first
    if tunnel_running:
        stop_tunnel()
        time.sleep(2)
    
    ssh_key_path = get_ssh_key_path()
    
    def run_tunnel():
        global tunnel_process, tunnel_running
        
        while tunnel_running:
            try:
                # Check if we have a preferred hostname from .env
                preferred_hostname = os.getenv('TUNNEL_HOSTNAME', '')
                
                if ssh_key_path:
                    logging.debug(f"Starting authenticated localhost.run tunnel to port {port}")
                else:
                    logging.debug(f"Starting localhost.run tunnel to port {port} (no-key mode)")
                
                # Build SSH command - be explicit about the forwarding
                cmd = [
                    'ssh', 
                    '-o', 'StrictHostKeyChecking=no',
                    '-o', 'ServerAliveInterval=60',
                    '-o', 'ServerAliveCountMax=3',
                    '-R', f'80:127.0.0.1:{port}',  # Explicitly use 127.0.0.1
                ]
                
                # Add SSH key if available
                if ssh_key_path:
                    cmd.extend(['-i', ssh_key_path])
                
                # Use the correct endpoint
                if ssh_key_path:
                    cmd.extend(['localhost.run'])  # Authenticated endpoint
                else:
                    cmd.extend(['-p', '2222', 'ssh.localhost.run'])  # No-key endpoint
                
                logging.debug(f"Running tunnel command: {' '.join(cmd)}")
                
                # Use Popen with proper non-blocking setup
                tunnel_process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    universal_newlines=True,
                    bufsize=1,
                    encoding='utf-8',
                    errors='replace'
                )
                
                logging.debug("Tunnel process started, waiting for connection...")
                
                tunnel_url_found = False
                used_preferred_hostname = False
                
                # Read output without blocking the main thread
                for line in iter(tunnel_process.stdout.readline, ''):
                    if not tunnel_running:
                        break
                    
                    line = line.strip()
                    if line and CONFIG['app']['debug']:
                        logging.debug(f"[localhost.run] {line}")
                    
                    # Skip welcome messages and documentation
                    if any(phrase in line.lower() for phrase in [
                        'welcome to', 'follow your', 'to set up', 'more details',
                        'if you get', 'to explore', 'documentation', 'custom domains',
                        '===============================================================================',
                        '** your connection id is'
                    ]):
                        continue
                    
                    # Look for the actual tunnel URL
                    tunnel_url, subdomain = parse_tunnel_url(line)
                    if tunnel_url and subdomain and not tunnel_url_found:
                        # Check if this matches our preferred hostname
                        if preferred_hostname and subdomain == preferred_hostname:
                            used_preferred_hostname = True
                            print(f"🎉 Using preferred hostname: {tunnel_url}")
                        else:
                            print(f"🎉 Your public URL is: {tunnel_url}")
                            
                        set_env('TUNNEL_HOSTNAME', subdomain)
                        tunnel_url_found = True
                        
                        # Test the tunnel immediately (silent unless debug)
                        if CONFIG['app']['debug']:
                            logging.debug("Testing tunnel connection...")
                        test_tunnel_connection(tunnel_url)
                        
                        # Always print QR code
                        if 'qr:' in line.lower():
                            print(f"📱 {line}")
                    
                    # Only show authentication and establishment in debug mode
                    if CONFIG['app']['debug']:
                        if 'authenticated' in line.lower() and '@' in line:
                            logging.debug(f"Authentication: {line}")
                        if 'tunneled with tls termination' in line.lower():
                            logging.debug(f"Tunnel established: {line}")
                
                return_code = tunnel_process.wait()
                tunnel_process = None
                
                if tunnel_running and return_code != 0 and not shutdown_event:
                    logging.error(f"Tunnel connection lost (exit code: {return_code}). Reconnecting in 10 seconds...")
                    time.sleep(10)
                elif not tunnel_running or shutdown_event:
                    logging.debug("Tunnel stopped by user")
                    break
                    
            except Exception as e:
                if tunnel_running:
                    logging.error(f"Error with localhost.run tunnel: {e}. Retrying in 10 seconds...")
                    time.sleep(10)
                else:
                    break
    
    tunnel_running = True
    tunnel_thread = threading.Thread(target=run_tunnel, daemon=True, name="TunnelManager")
    tunnel_thread.start()
    
    return os.getenv('TUNNEL_HOSTNAME', 'random')

def test_tunnel_connection(tunnel_url):
    """Test if the tunnel URL is accessible"""
    try:
        logging.debug(f"🧪 Testing {tunnel_url}...")
        response = requests.get(tunnel_url, timeout=10, verify=False)
        if response.status_code == 200:
            logging.debug(f"✅ Tunnel test successful! Status: {response.status_code}")
        else:
            logging.debug(f"⚠️ Tunnel responded with status: {response.status_code}")
    except requests.exceptions.SSLError:
        logging.debug("⚠️ SSL certificate error (expected for localhost.run)")
        # Try without SSL verification
        try:
            response = requests.get(tunnel_url, timeout=10, verify=False)
            logging.debug(f"✅ Tunnel test successful (without SSL)! Status: {response.status_code}")
        except Exception as e:
            logging.debug(f"❌ Tunnel test failed: {e}")
    except Exception as e:
        logging.debug(f"❌ Tunnel test failed: {e}")        

def stop_tunnel():
    """Stop the tunnel gracefully"""
    global tunnel_process, tunnel_running
    
    print("Stopping tunnel...")
    tunnel_running = False
    
    if tunnel_process:
        try:
            print("Terminating tunnel process...")
            tunnel_process.terminate()
            
            # Wait for process to terminate with timeout
            try:
                tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("Process didn't terminate, killing...")
                tunnel_process.kill()
                tunnel_process.wait()
                
        except Exception as e:
            print(f"Error stopping tunnel process: {e}")
        
        tunnel_process = None
    
    print("Tunnel stopped")

def check_server_health(port=CONFIG['app']['port'], timeout=5, retries=3):
    """Check if the Flask server is responding - silent version"""
    for attempt in range(retries):
        try:
            response = requests.get(f'http://localhost:{port}/', timeout=timeout)
            if response.status_code == 200:
                if CONFIG['app']['debug']:
                    logging.debug(f"Server health check passed (attempt {attempt + 1})")
                return True
            else:
                if CONFIG['app']['debug']:
                    logging.debug(f"Server returned status {response.status_code} (attempt {attempt + 1})")
        except requests.exceptions.ConnectionError:
            if CONFIG['app']['debug']:
                logging.debug(f"Server not ready yet (attempt {attempt + 1})")
        except Exception as e:
            if CONFIG['app']['debug']:
                logging.debug(f"Health check error: {e} (attempt {attempt + 1})")
        
        time.sleep(1)  # Wait before retry
    
    return False

def monitor_server_health(port=CONFIG['app']['port'], check_interval=10):
    """Monitor server health and stop tunnel if server is down"""
    consecutive_failures = 0
    max_failures = 3
    
    while tunnel_running and not shutdown_event:
        time.sleep(check_interval)
        
        if not tunnel_running or shutdown_event:
            break
            
        if check_server_health(port):
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if CONFIG['app']['debug']:
                logging.debug(f"Server health check failed ({consecutive_failures}/{max_failures})")
            
            if consecutive_failures >= max_failures:
                logging.warning("Server appears to be stopped. Stopping tunnel...")
                stop_tunnel()
                break

def start_health_monitor(port=CONFIG['app']['port']):
    """Start the server health monitor in a separate thread"""
    health_thread = threading.Thread(
        target=monitor_server_health, 
        args=(port,),
        daemon=True,
        name="HealthMonitor"
    )
    health_thread.start()

def restart_tunnel(port=CONFIG['app']['port']):
    """Restart the tunnel with new settings"""
    print("Restarting tunnel...")
    stop_tunnel()
    time.sleep(2)
    return start_tunnel(port)

# API endpoints for tunnel management
@app.route('/api/tunnel/status')
@debug_log
def get_tunnel_status():
    """Get current tunnel status"""
    return jsonify({
        'running': tunnel_running,
        'hostname': os.getenv('TUNNEL_HOSTNAME'),
        'ssh_key_configured': get_ssh_key_path() is not None,
        'process_alive': tunnel_process and tunnel_process.poll() is None
    })

@app.route('/api/tunnel/restart', methods=['POST'])
@debug_log
def restart_tunnel_route():
    """Restart the tunnel"""
    port = request.json.get('port', CONFIG['app']['port']) if request.is_json else CONFIG['app']['port']
    hostname = restart_tunnel(port)
    return jsonify({
        'success': True,
        'hostname': hostname,
        'message': 'Tunnel restarted'
    })

@app.route('/api/tunnel/stop', methods=['POST'])
@debug_log
def stop_tunnel_route():
    """Stop the tunnel"""
    stop_tunnel()
    return jsonify({'success': True, 'message': 'Tunnel stopped'})

@app.route('/api/tunnel/start', methods=['POST'])
@debug_log
def start_tunnel_route():
    """Start the tunnel"""
    port = request.json.get('port', CONFIG['app']['port']) if request.is_json else CONFIG['app']['port']
    hostname = start_tunnel(port)
    return jsonify({
        'success': True,
        'hostname': hostname,
        'message': 'Tunnel started'
    })

@app.route('/api/tunnel/regenerate-hostname', methods=['POST'])
@debug_log
def regenerate_hostname():
    """Generate a new tunnel hostname"""
    # Clear current hostname
    set_env('TUNNEL_HOSTNAME', '')
    
    # Generate new one
    hostname = ensure_tunnel_hostname()
    
    # Restart tunnel with new hostname
    restart_tunnel(CONFIG['app']['port'])
    
    return jsonify({
        'success': True,
        'hostname': hostname,
        'message': 'Hostname regenerated and tunnel restarted'
    })

@app.route('/api/tunnel/set-ssh-key', methods=['POST'])
@debug_log
def set_ssh_key():
    """Set the SSH key path for the tunnel"""
    if not request.is_json or 'ssh_key_path' not in request.json:
        return jsonify({'success': False, 'error': 'SSH key path required'}), 400
    
    ssh_key_path = request.json['ssh_key_path']
    
    if not os.path.exists(ssh_key_path):
        return jsonify({'success': False, 'error': 'SSH key file not found'}), 400
    
    set_env('TUNNEL_SSH_KEY', ssh_key_path)
    
    # Restart tunnel with new key
    restart_tunnel(CONFIG['app']['port'])
    
    return jsonify({
        'success': True,
        'message': 'SSH key updated and tunnel restarted'
    })
############################ END OF LOCALHOST.RUN TUNNELING ############################
    
@app.route('/get_media_details')
@debug_log
def get_media_details():
    media_type = request.args.get('type')
    media_id = request.args.get('id')

    print(f"Fetching details for {media_type} with ID: {media_id}")
    
    if media_type == 'movie':
        return jsonify(get_radarr_details(media_id))
    else:
        return jsonify(get_sonarr_details(media_id))
    
@debug_log
def update_checker():
    """Background thread to check for updates periodically"""
    update_lock = threading.Lock()
    
    while True:
        try:
            with update_lock:
                # Check if enough time has passed since last check
                current_time = time.time()
                
                # Convert last_checked to float, default to 0 if not set
                try:
                    last_checked = float(CONFIG['update']['last_checked'])
                except (ValueError, TypeError):
                    last_checked = 0.0
                
                # Convert check_interval to int, default to 3600 (1 hour) if not set
                try:
                    check_interval = int(CONFIG['update']['check_interval'])
                except (ValueError, TypeError):
                    check_interval = 3600
                
                if current_time - last_checked >= check_interval:
                    if CONFIG['app']['debug']:
                        logging.info("Checking for updates...")
                    
                    update_info = check_github_for_updates()
                    if update_info.get('update_available'):
                        latest_version = update_info['latest_version']
                        
                        # Check if this update is already downloaded
                        existing_updates = get_downloaded_updates()
                        already_downloaded = any(update['version'] == latest_version for update in existing_updates)
                        
                        if not already_downloaded:
                            if CONFIG['app']['debug']:
                                logging.info(f"Update available: {latest_version}")
                            # Auto-download the update
                            download_result = download_update()
                            if download_result.get('success'):
                                if CONFIG['app']['debug']:
                                    logging.info(f"Auto-downloaded update: {download_result['version']}")
                                
                                # Auto-apply the update after download
                                apply_result = apply_update(download_result['version'])
                                if apply_result.get('success'):
                                    if CONFIG['app']['debug']:
                                        logging.info(f"Auto-applied update: {download_result['version']}")
                                else:
                                    logging.error(f"Auto-apply failed: {apply_result.get('error')}")
                            else:
                                logging.error(f"Auto-download failed: {download_result.get('error')}")
                        else:
                            if CONFIG['app']['debug']:
                                logging.info(f"Update {latest_version} already downloaded, skipping download")
                    
                    # Update last_checked as float
                    CONFIG['update']['last_checked'] = current_time
                    
            # Sleep for 1 hour before checking again
            time.sleep(3600)
            
        except Exception as e:
            logging.error(f"Update checker error: {str(e)}")
            time.sleep(3600)

# Start update checker thread
update_thread = threading.Thread(target=update_checker, daemon=True)
update_thread.start()

@app.route('/api/debug/tunnel')
@debug_log
def debug_tunnel():
    """Debug endpoint to check tunnel status"""
    import socket
    from urllib.parse import urlparse
    
    tunnel_hostname = os.getenv('TUNNEL_HOSTNAME', '')
    
    # Check DNS resolution
    dns_resolved = False
    try:
        for domain in [f"{tunnel_hostname}.lhr.life", f"{tunnel_hostname}.localhost.run"]:
            try:
                socket.gethostbyname(domain)
                dns_resolved = True
                break
            except socket.gaierror:
                continue
    except Exception as e:
        dns_resolved = False
    
    return jsonify({
        'tunnel_hostname': tunnel_hostname,
        'tunnel_urls': [
            f"https://{tunnel_hostname}.lhr.life",
            f"https://{tunnel_hostname}.localhost.run"
        ],
        'dns_resolved': dns_resolved,
        'tunnel_running': tunnel_running,
        'process_alive': tunnel_process and tunnel_process.poll() is None,
        'flask_running': True,
        'flask_port': CONFIG['app']['port'],
        'request_headers': dict(request.headers)
    })

@debug_log
def extract_update(version):
    """Extract the downloaded update zip file with detailed logging"""
    try:
        updates_folder = ensure_updates_folder()
        zip_file = os.path.join(updates_folder, f"addarr_{version}.zip")
        
        if not os.path.exists(zip_file):
            logging.error(f"Update file not found: {zip_file}")
            return {'success': False, 'error': f'Update file not found: {zip_file}'}
        
        logging.info(f"Extracting update {version} from {zip_file}")
        
        # Create extraction directory
        extract_path = os.path.join(updates_folder, f"extracted_{version}")
        
        # Remove existing extraction directory if it exists
        if os.path.exists(extract_path):
            import shutil
            shutil.rmtree(extract_path)
            logging.info(f"Removed existing extraction directory: {extract_path}")
        
        # Extract the zip file
        import zipfile
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            logging.info(f"Files in zip: {len(file_list)}")
            for i, file in enumerate(file_list[:10]):  # Log first 10 files
                logging.info(f"  {i+1}. {file}")
            if len(file_list) > 10:
                logging.info(f"  ... and {len(file_list) - 10} more files")
            
            zip_ref.extractall(extract_path)
        
        logging.info(f"Successfully extracted to: {extract_path}")
        
        # List extracted contents
        extracted_items = os.listdir(extract_path)
        logging.info(f"Extracted contents: {extracted_items}")
        
        return {
            'success': True,
            'extract_path': extract_path,
            'zip_file': zip_file,
            'file_count': len(file_list),
            'extracted_items': extracted_items
        }
        
    except Exception as e:
        logging.error(f"Error extracting update: {str(e)}")
        logging.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}
    
@debug_log
def apply_update(version):
    """Apply the extracted update to the current installation with detailed logging"""
    try:
        logging.info(f"STARTING UPDATE APPLICATION FOR VERSION {version}")
        
        # First extract the update
        extract_result = extract_update(version)
        if not extract_result['success']:
            logging.error(f"Extraction failed: {extract_result.get('error')}")
            return extract_result
        
        extract_path = extract_result['extract_path']
        
        # Find the actual application files in the extracted directory
        extracted_items = os.listdir(extract_path)
        logging.info(f"Looking for application files in: {extracted_items}")
        
        if not extracted_items:
            logging.error("No files found in extracted update")
            return {'success': False, 'error': 'No files found in extracted update'}
        
        # GitHub releases typically have a folder like "addarr-main" or "addarr-version"
        source_dir = extract_path
        for item in extracted_items:
            item_path = os.path.join(extract_path, item)
            if os.path.isdir(item_path) and item.startswith('addarr-'):
                source_dir = item_path
                logging.info(f"Found application directory: {item}")
                break
        
        logging.info(f"Source directory for update: {source_dir}")
        
        # Get current application directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        logging.info(f"Target application directory: {current_dir}")
        
        # Verify source directory exists and has files
        if not os.path.exists(source_dir):
            logging.error(f"Source directory does not exist: {source_dir}")
            return {'success': False, 'error': f'Source directory not found: {source_dir}'}
        
        source_files = []
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), source_dir)
                source_files.append(rel_path)
        
        logging.info(f"Found {len(source_files)} files in source directory")
        logging.info("First 20 files to be copied:")
        for i, file in enumerate(source_files[:20]):
            logging.info(f"  {i+1}. {file}")
        
        # Files and directories to exclude from update
        exclude_files = {
            '.env', 'addarr.log', 'updates', '__pycache__', '.git',
            'instance', 'venv', 'node_modules', '.vscode', '.idea',
            'last_ip.txt'
        }
        
        exclude_extensions = {'.pyc', '.tmp', '.log', '.db'}
        
        # Copy files from extracted update to current directory
        files_copied = 0
        files_skipped = 0
        errors = []
        
        logging.info("Starting file copy process...")
        
        for root, dirs, files in os.walk(source_dir):
            # Filter out excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_files]
            
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, source_dir)
                
                # Skip excluded files and extensions
                if (file in exclude_files or 
                    any(file.endswith(ext) for ext in exclude_extensions) or
                    any(excluded in relative_path.split(os.sep) for excluded in exclude_files)):
                    files_skipped += 1
                    logging.debug(f"Skipped (excluded): {relative_path}")
                    continue
                
                # Determine destination path
                dest_path = os.path.join(current_dir, relative_path)
                dest_dir = os.path.dirname(dest_path)
                
                # Create destination directory if it doesn't exist
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir, exist_ok=True)
                    logging.debug(f"Created directory: {dest_dir}")
                
                try:
                    # Copy file with proper error handling
                    import shutil
                    shutil.copy2(file_path, dest_path)
                    files_copied += 1
                    logging.info(f"Copied: {relative_path}")
                except Exception as e:
                    error_msg = f"Error copying {relative_path}: {str(e)}"
                    logging.error(f"COPY ERROR: {error_msg}")
                    errors.append(error_msg)
        
        # Clean up temporary extraction directory
        try:
            import shutil
            shutil.rmtree(extract_path, ignore_errors=True)
            logging.info(f"Cleaned up extraction directory: {extract_path}")
        except Exception as e:
            logging.warning(f"Could not clean up extraction directory: {str(e)}")
        
        if errors:
            logging.error(f"Update completed with {len(errors)} errors")
            return {
                'success': False,
                'error': f'Update partially applied with {len(errors)} errors',
                'files_copied': files_copied,
                'files_skipped': files_skipped,
                'errors': errors
            }
        
        logging.info(f"Update file copy completed: {files_copied} files copied, {files_skipped} files skipped")
        
        # Update version in environment and config
        logging.info(f"Updating version from {CONFIG['app']['version']} to {version}")
        
        version_result = set_env('APP_VERSION', version)
        if not version_result:
            logging.error("Failed to update APP_VERSION in .env")
        
        set_env('UPDATE_APPLIED', 'true')
        set_env('UPDATE_APPLIED_VERSION', version)
        set_env('UPDATE_NOTIFICATION', 'false')  # Clear update notification
        
        # Update running config
        CONFIG['app']['version'] = version
        logging.info(f"Successfully updated running config to version: {version}")
        
        result = {
            'success': True,
            'message': f'Update {version} applied successfully. Server will restart shortly.',
            'files_copied': files_copied,
            'files_skipped': files_skipped,
            'version': version
        }
        
        logging.info("Scheduling server restart...")
        
        # Schedule restart
        def delayed_restart():
            logging.info("Executing delayed restart...")
            restart_application()
        
        # Start restart in a separate thread after 3 seconds
        restart_thread = threading.Timer(3.0, delayed_restart)
        restart_thread.daemon = True
        restart_thread.start()
        
        logging.info("Restart scheduled in 3 seconds")
        
        return result
        
    except Exception as e:
        logging.error(f"Critical error in apply_update: {str(e)}")
        logging.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}
    
@debug_log
def restart_application():
    """Restart the application to apply changes"""
    try:
        logging.info("RESTARTING APPLICATION...")
        print("RESTARTING APPLICATION...")
        
        # Import required modules here to avoid circular imports
        import sys
        import subprocess
        
        # For development/debugging - just log the restart
        if CONFIG['app']['debug']:
            logging.info("DEBUG MODE: Application restart simulated - would normally restart now")
            print("DEBUG MODE: Application restart simulated")
            # Even in debug mode, let's try to actually restart
            logging.info("Attempting restart even in debug mode...")
        
        # Get current python executable and script
        python = sys.executable
        script = os.path.abspath(__file__)
        
        logging.info(f"Restarting with: {python} {script}")
        print(f"Restarting with: {python} {script}")
        
        # Start new process
        subprocess.Popen([python, script])
        
        logging.info("New process started, exiting current process")
        print("New process started, exiting current process")
        
        # Exit current process
        sys.exit(0)
        
    except Exception as e:
        logging.error(f"Error restarting application: {str(e)}")
        print(f"Error restarting application: {str(e)}")
        logging.error(traceback.format_exc())
        return {'success': False, 'error': str(e)}

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static', 'images'),
                              'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/save_config', methods=['POST'])
@debug_log
def save_config():
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred'}), 500

def update_duckdns_if_needed():
    """Check and update DuckDNS with detailed logging"""
    if not CONFIG['duckdns']['enabled']:
        if CONFIG['app']['debug']:
            logging.debug("DuckDNS: Update skipped - DuckDNS is not enabled")
        return False
        
    if not CONFIG['duckdns']['domain'] or not CONFIG['duckdns']['token']:
        if CONFIG['app']['debug']:
            logging.debug("DuckDNS: Update skipped - Missing domain or token")
        return False
    
    if CONFIG['app']['debug']:
        logging.debug("DuckDNS: Starting IP check and update process...")
    
    current_ip = get_ip_address()
    last_ip = None
    
    # Check if IP has changed
    ip_file = os.path.join(os.path.dirname(__file__), 'last_ip.txt')
    if os.path.exists(ip_file):
        with open(ip_file, 'r') as f:
            last_ip = f.read().strip()
        if CONFIG['app']['debug']:
            logging.debug(f"DuckDNS: Last known IP: {last_ip}")
    else:
        if CONFIG['app']['debug']:
            logging.debug("DuckDNS: No previous IP found - first time update")
    
    if CONFIG['app']['debug']:
        logging.debug(f"DuckDNS: Current external IP: {current_ip}")
    
    if current_ip == last_ip:
        if CONFIG['app']['debug']:
            logging.debug("DuckDNS: IP unchanged - no update required")
        return False
    
    # Update DuckDNS
    try:
        if CONFIG['app']['debug']:
            logging.debug(f"DuckDNS: Attempting to update {CONFIG['duckdns']['domain']}.duckdns.org to IP: {current_ip}")
        
        url = f"https://www.duckdns.org/update?domains={CONFIG['duckdns']['domain']}&token={CONFIG['duckdns']['token']}&ip={current_ip}"
        response = requests.get(url, timeout=10)
        
        if response.text.strip() == "OK":
            with open(ip_file, 'w') as f:
                f.write(current_ip)
            logging.info(f"DuckDNS: Successfully updated to {current_ip}")
            return True
        else:
            logging.error(f"DuckDNS: Update failed. Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"DuckDNS: Network error during update: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"DuckDNS: Unexpected error during update: {str(e)}")
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


@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred'}), 500

required_env = ['RADARR_URL', 'RADARR_API_KEY', 'SONARR_URL', 'SONARR_API_KEY']
missing = [key for key in required_env if not os.getenv(key)]
if missing:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")


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

@app.route('/api/update/extract/<version>', methods=['POST'])
@debug_log
def extract_update_route(version):
    """Extract a downloaded update"""
    result = extract_update(version)
    return jsonify(result)


@debug_log
def apply_update_simple(version):
    """Simple update application that just updates version and prompts for restart"""
    try:
        logging.info(f"Applying update {version} (simple method)")
        
        # Update the current version in .env
        set_env('APP_VERSION', version)
        
        # Set flags
        set_env('UPDATE_APPLIED', 'true')
        set_env('UPDATE_APPLIED_VERSION', version)
        set_env('UPDATE_NOTIFICATION', 'false')  # Clear the update notification
        
        # Update the running config
        CONFIG['app']['version'] = version
        
        logging.info(f"Successfully updated to version {version}")
        
        return {
            'success': True,
            'message': f'Successfully updated to version {version}. Please restart the application.',
            'version': version
        }
        
    except Exception as e:
        logging.error(f"Error applying update: {str(e)}")
        return {'success': False, 'error': str(e)}

@app.route('/api/update/apply/<version>', methods=['POST'])
@debug_log
def apply_update_route(version):
    """Apply an extracted update"""
    try:
        logging.info(f"📍 API Route: Starting update application for version {version}")
        result = apply_update(version)
        logging.info(f"📍 API Route: Update result: {result}")
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"❌ API Route Error: {str(e)}")
        logging.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)})
    
@app.route('/api/debug/update-status')
@debug_log
def debug_update_status():
    """Debug endpoint to check current update state"""
    updates_folder = ensure_updates_folder()
    downloaded_updates = get_downloaded_updates()
    
    return jsonify({
        'current_version': CONFIG['app']['version'],
        'env_version': os.getenv('APP_VERSION'),
        'update_notification': os.getenv('UPDATE_NOTIFICATION'),
        'update_applied': os.getenv('UPDATE_APPLIED'),
        'update_applied_version': os.getenv('UPDATE_APPLIED_VERSION'),
        'updates_folder': updates_folder,
        'downloaded_updates': [u['version'] for u in downloaded_updates],
        'updates_folder_exists': os.path.exists(updates_folder),
        'updates_folder_contents': os.listdir(updates_folder) if os.path.exists(updates_folder) else []
    })

@app.route('/api/update/apply-latest', methods=['POST'])
@debug_log
def apply_latest_update():
    """Apply the latest downloaded update"""
    try:
        updates = get_downloaded_updates()
        if not updates:
            return jsonify({'success': False, 'error': 'No downloaded updates found'})
        
        latest_update = updates[0]  # Already sorted by version, newest first
        version = latest_update['version']
        
        # Apply the update
        apply_result = apply_update(version)
        
        return jsonify(apply_result)
        
    except Exception as e:
        logging.error(f"Error applying latest update: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/update/apply-simple/<version>', methods=['POST'])
@debug_log
def apply_update_simple_route(version):
    """Simple update application that just updates version"""
    try:
        logging.info(f"Applying simple update to version {version}")
        
        # Update the current version in .env
        set_env('APP_VERSION', version)
        
        # Set flags
        set_env('UPDATE_APPLIED', 'true')
        set_env('UPDATE_APPLIED_VERSION', version)
        set_env('UPDATE_NOTIFICATION', 'false')  # Clear the update notification
        
        # Update the running config
        CONFIG['app']['version'] = version
        
        logging.info(f"Successfully updated to version {version}")
        
        result = {
            'success': True,
            'message': f'Successfully updated to version {version}. Please restart the application.',
            'version': version
        }
        
        return jsonify(result)
        
    except Exception as e:
        logging.error(f"Error in simple update: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/update/restart', methods=['POST'])
@debug_log
def restart_application_route():
    """Restart the application"""
    result = restart_application()
    return jsonify(result)


@app.route('/logs')
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
      
@app.route('/search', methods=['POST'])
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
@debug_log
def serve_image(filename):
    return send_from_directory('static/images', filename)

@app.route('/manage')
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
    


if CONFIG['app']['debug']:
    logging.info("Performing initial update check...")
initial_update_info = check_github_for_updates()
if initial_update_info.get('update_available'):
    latest_version = initial_update_info['latest_version']
    
    # Check if we already have this update downloaded
    existing_updates = get_downloaded_updates()
    already_downloaded = any(update['version'] == latest_version for update in existing_updates)
    
    if not already_downloaded:
        if CONFIG['app']['debug']:
            logging.info(f"Initial check: Update available - {latest_version}")
        # Don't auto-download on initial check, just notify
        set_env('UPDATE_NOTIFICATION', 'true')
        set_env('LATEST_VERSION', latest_version)
    else:
        if CONFIG['app']['debug']:
            logging.info(f"Initial check: Update {latest_version} already downloaded")

CONFIG['update']['last_checked'] = time.time()

@app.route('/')
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
    """Print welcome message and logo only once"""
    from colorama import Fore, Style
    
    tunnel_hostname = os.getenv('TUNNEL_HOSTNAME', '')
    
    # Build tunnel URL display
    if tunnel_hostname:
        # Try both possible domain formats
        # tunnel_urls = [
        #     f"https://{tunnel_hostname}.lhr.life",
        #     f"https://{tunnel_hostname}.localhost.run"
        # ]
        #tunnel_display = f"{Fore.CYAN}{tunnel_urls[0]}{Style.RESET_ALL} or {Fore.CYAN}{tunnel_urls[1]}{Style.RESET_ALL}"
        tunnel_urls = [
            f"https://{tunnel_hostname}.lhr.life"
        ]
        tunnel_display = f"{Fore.CYAN}{tunnel_urls[0]}{Style.RESET_ALL}"
    else:
        tunnel_display = "Not configured"
    
    app_info = f"""
    {Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}
    {Fore.WHITE}• Version: {CONFIG['app']['version']}
    {Fore.WHITE}• Local: {Fore.CYAN}http://127.0.0.1:{CONFIG['app']['port']}{Style.RESET_ALL}
    {Fore.WHITE}• Network: {Fore.CYAN}http://{get_ip_address()}:{CONFIG['app']['port']}{Style.RESET_ALL}
    {Fore.WHITE}• Tunnel: {tunnel_display}
    """
    
    if CONFIG['duckdns']['enabled'] and CONFIG['duckdns']['domain']:
        app_info += f"{Fore.WHITE}• DuckDNS: {Fore.CYAN}http://{CONFIG['duckdns']['domain']}.duckdns.org:{CONFIG['app']['port']}{Style.RESET_ALL}\n"
    
    try:
        my_art = AsciiArt.from_image('static/images/logo.png')
        my_art.to_terminal()
    except Exception as e:
        # Fallback if logo isn't available
        print(f"{Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}")
    
    print(app_info)
    print(f"{Fore.GREEN}✅ Ready to add media!{Style.RESET_ALL}\n")
    print(f"{Fore.YELLOW}Press Ctrl-C to shutdown{Style.RESET_ALL}")

if __name__ == '__main__':
    import signal
    import sys
    
    def signal_handler(sig, frame):
        print("\n🛑 Shutting down gracefully...")
        global tunnel_running, shutdown_event
        
        # Set shutdown flag to prevent restarts
        shutdown_event = True
        tunnel_running = False
        
        # Stop tunnel first
        stop_tunnel()
        
        # Exit immediately
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    def start_application():
        """Start the application with proper sequencing"""
        print("🚀 Starting Flask application...")
        
        # Start Flask in a separate thread
        def run_flask():
            app.run(host='0.0.0.0', debug=False, port=CONFIG['app']['port'], use_reloader=False)
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Wait for Flask to start
        print("⏳ Waiting for Flask server to start...")
        for i in range(10):  # Wait up to 10 seconds
            if check_server_health(CONFIG['app']['port']):
                print("✅ Flask server is running!")
                break
            time.sleep(1)
        else:
            print("❌ Flask server failed to start within 10 seconds")
            return False
        
        # Start tunnel (only in main process)
        if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
            if CONFIG['app']['debug']:
                logging.debug("Starting tunnel...")
            tunnel_hostname = start_tunnel(port=CONFIG['app']['port'])
            
            # Start health monitor
            start_health_monitor(port=CONFIG['app']['port'])

            # Update DuckDNS if enabled
            if CONFIG['duckdns']['enabled']:
                try:
                    update_duckdns_if_needed()
                except Exception as e:
                    logging.error(f"DuckDNS update failed: {str(e)}")

            print_welcome()
        
        return True

    # Start the application
    if not start_application():
        sys.exit(1)
    
    # Keep the main thread alive and responsive
    try:
        print("🏃 Application running. Press Ctrl-C to stop.")
        while not shutdown_event:
            time.sleep(1)
            # Only check/restart tunnel if we're not shutting down
            if not shutdown_event and tunnel_process and tunnel_process.poll() is not None:
                logging.warning("Tunnel process died, restarting...")
                start_tunnel(port=CONFIG['app']['port'])
    except KeyboardInterrupt:
        # This should be caught by the signal handler, but just in case
        pass
    except Exception as e:
        logging.error(f"Unexpected error in main loop: {e}")
    finally:
        # Clean shutdown
        shutdown_event = True
        tunnel_running = False
        stop_tunnel()
        print("👋 Goodbye!")