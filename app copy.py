import os
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_from_directory
from dotenv import load_dotenv
import threading
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import time
from ascii_magic import AsciiArt
from collections import deque
import traceback
import subprocess
import sys
import requests
import atexit
import re
import io
import logging
import shutil

try:
    import pinggy
    PINGGY_AVAILABLE = True
except ImportError:
    PINGGY_AVAILABLE = False
    print("⚠️  Pinggy module not installed. Tunnel features will be disabled.")
    print("   Install with: pip install pinggy")

# Ensure Windows console uses UTF-8 and wrap stdio so logging can emit emojis / block chars
try:
    if os.name == 'nt':
        # ask Windows to use UTF-8 code page for console output (best-effort)
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    # re-wrap stdout/stderr with explicit UTF-8 encoding and safe error handling
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
except Exception:
    # if wrapping fails, continue without crashing
    pass

# configure root logger to use stdout wrapper (ensures handler uses UTF-8 stream)
root = logging.getLogger()
for h in list(root.handlers):
    root.removeHandler(h)
handler = logging.StreamHandler(stream=sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
root.addHandler(handler)
root.setLevel(logging.DEBUG if os.environ.get('FLASK_DEBUG', 'false').lower() == 'true' else logging.INFO)

# Global variables
shutdown_event = False
app = Flask(__name__)
tunnel_process = None
tunnel_url = None

# Load environment variables
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
    },
    'app': {
        'debug': os.getenv('FLASK_DEBUG', 'false').lower() == 'true',
        'version': os.getenv('APP_VERSION', '1.0.0'),
        'port' : os.getenv('SERVER_PORT', 5000)
    },
    'duckdns': {
        'domain': os.getenv('DUCKDNS_DOMAIN', ''),
        'token': os.getenv('DUCKDNS_TOKEN', ''),
        'enabled': os.getenv('DUCKDNS_ENABLED', 'false').lower() == 'true'
    },
    'update': {
        'github_repo':  os.getenv('GITHUB_REPO', 'revvin76/addarr'),
        'check_interval':  os.getenv('CHECK_INTERVAL', '3600'),
        'last_checked':  os.getenv('LAST_CHECKED', '0'),
        'enabled': os.getenv('ENABLE_AUTO_UPDATE', 'false').lower() == 'true',
        'updates_folder':  os.getenv('UPDATES_FOLDER', ''),
    },
    'tunnel': {
        'enabled':  os.getenv('TUNNEL_ENABLED', 'false').lower() == 'true',
    }
}

def setup_logging():
    log_format = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    log_file = 'addarr.log'
    
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if CONFIG['app']['debug'] else logging.INFO)
    
    # Remove any existing handlers to avoid duplicate handlers that may hold old streams
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.handlers.clear()
    
    # File handler (rotating) — ensure UTF-8 encoding
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(file_handler)
    
    # Console handler — explicitly use the wrapped sys.stdout so encoding is UTF-8
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(console_handler)
    
    # Reduce noise
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
    """Background thread to check for updates periodically (respects interval)"""
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
                        logging.info("🔄 Automated update check running...")
                    
                    update_info = check_github_for_updates()
                    if update_info.get('update_available'):
                        latest_version = update_info['latest_version']
                        current_version = CONFIG['app']['version']
                        
                        if latest_version > current_version:
                            logging.info(f"📦 Auto-check: Update available: {latest_version}")
                            
                            # Check if this update is already downloaded
                            existing_updates = get_downloaded_updates()
                            already_downloaded = any(update['version'] == latest_version for update in existing_updates)
                            
                            if not already_downloaded:
                                # AUTO-DOWNLOAD the update
                                download_result = download_update()
                                if download_result.get('success'):
                                    logging.info(f"✅ Auto-downloaded update: {download_result['version']}")
                                    
                                    # AUTO-APPLY the update
                                    apply_result = apply_update(download_result['version'])
                                    if apply_result.get('success'):
                                        logging.info(f"🚀 Auto-applied update: {download_result['version']}")
                                    else:
                                        logging.error(f"❌ Auto-apply failed: {apply_result.get('error')}")
                                else:
                                    logging.error(f"❌ Auto-download failed: {download_result.get('error')}")
                            else:
                                logging.info(f"📦 Auto-check: Update {latest_version} already downloaded, applying...")
                                # AUTO-APPLY the already downloaded update
                                apply_result = apply_update(latest_version)
                                if apply_result.get('success'):
                                    logging.info(f"🚀 Auto-applied existing update: {latest_version}")
                                else:
                                    logging.error(f"❌ Auto-apply failed: {apply_result.get('error')}")
                    
                    # Update last_checked for next automated check
                    CONFIG['update']['last_checked'] = current_time
                    set_env('LAST_CHECKED', str(current_time))
                
            # Sleep for 1 hour before checking again
            time.sleep(int(CONFIG['update']['check_interval']))
            
        except Exception as e:
            logging.error(f"❌ Automated update checker error: {str(e)}")
            time.sleep(int(CONFIG['update']['check_interval']))

# Start the automated update checker thread (only for continuous operation)
update_thread = threading.Thread(target=update_checker, daemon=True)
update_thread.start()

@debug_log
def perform_initial_update_check():
    """Blocking initial update check that always runs on startup - only in main process"""
    # Skip if this is the Werkzeug reloader process
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        logging.info("🔄 Skipping update check in Werkzeug reloader process")
        return False
        
    logging.info("🔍 Performing initial update check...")
    
    try:
        # FIRST: Check if we have any downloaded updates that need to be applied
        existing_updates = get_downloaded_updates()
        if existing_updates:
            latest_downloaded = existing_updates[0]  # Already sorted by version, newest first
            latest_version = latest_downloaded['version']
            current_version = CONFIG['app']['version']
            
            # If the downloaded version is newer than current version, apply it
            if latest_version > current_version:
                logging.info(f"📦 Found downloaded update {latest_version} (current: {current_version})")
                logging.info(f"🔄 Attempting to apply existing update: {latest_version}")
                
                apply_result = apply_update(latest_version)
                if apply_result.get('success'):
                    logging.info(f"🚀 Successfully applied existing update: {latest_version}")
                    logging.info("🔄 Application will restart shortly...")
                    return True
                else:
                    logging.error(f"❌ Failed to apply existing update: {apply_result.get('error')}")
                    # Continue to check for newer updates even if this one failed
        
        # SECOND: Check GitHub for new updates
        logging.info("Checking GitHub for new updates...")
        update_info = check_github_for_updates()
        
        if update_info.get('update_available'):
            latest_version = update_info['latest_version']
            current_version = CONFIG['app']['version']
            
            if latest_version > current_version:
                logging.info(f"📦 New update available: {latest_version} (current: {current_version})")
                
                # Check if we already have this specific update downloaded
                already_downloaded = any(update['version'] == latest_version for update in (existing_updates or []))
                
                if not already_downloaded:
                    # AUTO-DOWNLOAD THE UPDATE
                    logging.info(f"⬇️ Auto-downloading update: {latest_version}")
                    download_result = download_update()
                    
                    if download_result.get('success'):
                        logging.info(f"✅ Auto-downloaded update: {download_result['version']}")
                        
                        # AUTO-APPLY THE UPDATE AFTER DOWNLOAD
                        logging.info(f"🔄 Auto-applying update: {download_result['version']}")
                        apply_result = apply_update(download_result['version'])
                        
                        if apply_result.get('success'):
                            logging.info(f"🚀 Successfully applied new update: {download_result['version']}")
                            logging.info("🔄 Application will restart shortly...")
                            return True
                        else:
                            logging.error(f"❌ Auto-apply failed: {apply_result.get('error')}")
                    else:
                        logging.error(f"❌ Auto-download failed: {download_result.get('error')}")
                        # Set notification for manual download
                        set_env('UPDATE_NOTIFICATION', 'true')
                        set_env('LATEST_VERSION', latest_version)
                else:
                    # We already have this update downloaded - apply it
                    logging.info(f"📦 Update {latest_version} already downloaded, applying...")
                    apply_result = apply_update(latest_version)
                    
                    if apply_result.get('success'):
                        logging.info(f"🚀 Successfully applied downloaded update: {latest_version}")
                        logging.info("🔄 Application will restart shortly...")
                        return True
                    else:
                        logging.error(f"❌ Failed to apply downloaded update: {apply_result.get('error')}")
                        # Set notification for manual intervention
                        set_env('UPDATE_NOTIFICATION', 'true')
                        set_env('LATEST_VERSION', latest_version)
            else:
                logging.info("✅ Already on latest version")
        else:
            logging.info("✅ No new updates available")
        
        # Update last_checked timestamp for the next automated check
        current_time = time.time()
        CONFIG['update']['last_checked'] = current_time
        set_env('LAST_CHECKED', str(current_time))
        
        return False  # No restart needed
            
    except Exception as e:
        logging.error(f"❌ Initial update check failed: {str(e)}")
        return False
      
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
def update_env_file_from_demo(extract_path, current_dir):
    """Update .env file with existing values while preserving new structure from demo_env"""
    try:
        logging.info("🔄 Starting .env file update process...")
        
        # Make sure shutil is available
        import shutil  # ADD THIS HERE TOO FOR SAFETY
        
        # Paths to the files
        existing_env_path = os.path.join(current_dir, '.env')
        demo_env_path = find_demo_env_file(extract_path)
        
        if not demo_env_path:
            logging.error("❌ demo_env file not found in update")
            return False
        
        if not os.path.exists(existing_env_path):
            logging.error("❌ Existing .env file not found")
            return False
        
        # Read and parse both files
        existing_env = parse_env_file(existing_env_path)
        demo_env_content, demo_env_lines = read_demo_env_file(demo_env_path)
        
        if not demo_env_content:
            logging.error("❌ Failed to read demo_env file")
            return False
        
        # Create updated content
        updated_content, unknown_settings = create_updated_env_content(
            demo_env_content, demo_env_lines, existing_env
        )
        
        # Backup the original .env file
        backup_path = existing_env_path + '.backup'
        shutil.copy2(existing_env_path, backup_path)
        logging.info(f"📁 Backed up .env to {backup_path}")
        
        # Write the updated .env file
        with open(existing_env_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        logging.info("✅ Successfully updated .env file")
        
        # Log any unknown settings that were preserved
        if unknown_settings:
            logging.info(f"📝 Preserved {len(unknown_settings)} unknown settings:")
            for key in unknown_settings:
                logging.info(f"   - {key}")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Error updating .env file: {str(e)}")
        logging.error(traceback.format_exc())
        return False
    
@debug_log
def find_demo_env_file(extract_path):
    """Find the demo_env file in the extracted update"""
    possible_names = ['demo_env', 'demo_env.txt', 'env.example', '.env.example']
    
    for root, dirs, files in os.walk(extract_path):
        for file in files:
            if file.lower() in possible_names:
                return os.path.join(root, file)
    
    # Also check for files starting with "demo_env"
    for root, dirs, files in os.walk(extract_path):
        for file in files:
            if file.lower().startswith('demo_env'):
                return os.path.join(root, file)
    
    return None

@debug_log
def parse_env_file(env_path):
    """Parse .env file into a dictionary"""
    env_dict = {}
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Parse key=value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_dict[key.strip()] = value.strip()
    except Exception as e:
        logging.error(f"Error parsing env file {env_path}: {str(e)}")
    return env_dict

@debug_log
def read_demo_env_file(demo_env_path):
    """Read demo_env file and return content and structured lines"""
    try:
        with open(demo_env_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse lines while preserving structure
        lines = []
        for line in content.splitlines():
            lines.append({
                'original': line,
                'is_comment': line.strip().startswith('#'),
                'is_empty': not line.strip(),
                'is_setting': '=' in line and not line.strip().startswith('#')
            })
        
        return content, lines
    except Exception as e:
        logging.error(f"Error reading demo_env file: {str(e)}")
        return None, []

@debug_log
def create_updated_env_content(demo_env_content, demo_env_lines, existing_env):
    """Create updated .env content by merging existing values into demo_env structure"""
    updated_lines = []
    used_keys = set()
    unknown_settings = {}
    
    # First, process all demo_env lines
    for line_info in demo_env_lines:
        line = line_info['original']
        
        if line_info['is_setting'] and not line_info['is_comment']:
            # This is a setting line - extract key and replace value if it exists
            key = line.split('=', 1)[0].strip()
            
            if key in existing_env:
                # Replace with existing value
                new_line = f"{key}={existing_env[key]}"
                updated_lines.append(new_line)
                used_keys.add(key)
                logging.debug(f"🔧 Updated setting: {key}")
            else:
                # Keep the demo value
                updated_lines.append(line)
                logging.debug(f"📋 Kept demo setting: {key}")
        else:
            # Keep comments and empty lines as-is
            updated_lines.append(line)
    
    # Now find any existing settings that weren't in demo_env
    for key, value in existing_env.items():
        if key not in used_keys:
            unknown_settings[key] = value
    
    # Add unknown settings at the end with a header
    if unknown_settings:
        updated_lines.append('')
        updated_lines.append('# =========================================')
        updated_lines.append('# UNKNOWN SETTINGS (from previous version)')
        updated_lines.append('# These settings were not found in the new version')
        updated_lines.append('# but have been preserved from your existing configuration')
        updated_lines.append('# =========================================')
        updated_lines.append('')
        
        for key, value in unknown_settings.items():
            updated_lines.append(f"{key}={value}")
    
    return '\n'.join(updated_lines), unknown_settings
    
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
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # UPDATE: Update .env file first, before copying other files
        logging.info("🔄 Updating .env file with new version...")
        env_update_result = update_env_file_from_demo(extract_path, current_dir)
        if not env_update_result:
            logging.warning("⚠️  .env file update failed, but continuing with update")
        else:
            logging.info("✅ .env file updated successfully")
        
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
            'last_ip.txt', 'demo_env'  # ADDED: Exclude demo_env since we already processed it
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
                'errors': errors,
                'env_updated': env_update_result
            }
        
        logging.info(f"Update file copy completed: {files_copied} files copied, {files_skipped} files skipped")
        
        # Update version in environment and config (this should now reflect the new version from demo_env)
        current_version = CONFIG['app']['version']
        logging.info(f"Previous version: {current_version}, New version: {version}")
        
        # Also update the version in .env file explicitly
        set_env('APP_VERSION', version)
        
        # Reload environment to get any new settings
        load_dotenv()  # Reload to get updated .env values
        
        # Update running config with new version
        CONFIG['app']['version'] = version
        logging.info(f"Successfully updated running config to version: {version}")

        result = {
            'success': True,
            'message': f'Update {version} applied successfully. Server will restart shortly.',
            'files_copied': files_copied,
            'files_skipped': files_skipped,
            'version': version,
            'env_updated': env_update_result
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
def restore_env_backup_if_needed():
    """Restore .env backup if the update failed and backup exists"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(current_dir, '.env')
        backup_path = env_path + '.backup'
        
        if os.path.exists(backup_path):
            # Check if we need to restore (if .env doesn't exist or is empty)
            if not os.path.exists(env_path) or os.path.getsize(env_path) == 0:
                shutil.copy2(backup_path, env_path)
                logging.info("✅ Restored .env from backup due to update failure")
                return True
            else:
                # Remove the backup since update was successful
                os.remove(backup_path)
                logging.info("✅ Update successful, removed .env backup")
        return False
    except Exception as e:
        logging.error(f"Error handling .env backup: {str(e)}")
        return False
        
@debug_log
def restart_application():
    """Restart the application to apply changes"""
    try:
        logging.info("RESTARTING APPLICATION...")
        print("RESTARTING APPLICATION...")
        
        # Check if we need to restore .env backup
        restore_env_backup_if_needed()
        
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
    try:
        data = request.get_json()
        
        # Update configuration with new values
        for key, value in data.items():
            # Handle boolean values for environment variables
            if isinstance(value, bool):
                value_str = 'true' if value else 'false'
            else:
                value_str = str(value)
            
            # Update the environment variable
            set_env(key, value_str)
            
            # Update the running config for specific keys
            # === RADARR SETTINGS ===
            if key == 'RADARR_URL':
                CONFIG['radarr']['url'] = value
            elif key == 'RADARR_API_KEY':
                CONFIG['radarr']['api_key'] = value
            elif key == 'RADARR_ROOT_FOLDER':
                CONFIG['radarr']['root_folder'] = value
            elif key == 'RADARR_QUALITY_PROFILE':
                CONFIG['radarr']['quality_profile_id'] = value
            
            # === SONARR SETTINGS ===
            elif key == 'SONARR_URL':
                CONFIG['sonarr']['url'] = value
            elif key == 'SONARR_API_KEY':
                CONFIG['sonarr']['api_key'] = value
            elif key == 'SONARR_ROOT_FOLDER':
                CONFIG['sonarr']['root_folder'] = value
            elif key == 'SONARR_QUALITY_PROFILE':
                CONFIG['sonarr']['quality_profile_id'] = value
            elif key == 'SONARR_LANGUAGE_PROFILE':
                CONFIG['sonarr']['language_profile_id'] = value
            
            # === TMDB SETTINGS ===
            elif key == 'TMDB_KEY':
                # TMDB settings aren't in CONFIG by default, but we'll set env var
                pass
            elif key == 'TMDB_TOKEN':
                # TMDB settings aren't in CONFIG by default, but we'll set env var
                pass
            
            # === DUCKDNS SETTINGS ===
            elif key == 'DUCKDNS_ENABLED':
                CONFIG['duckdns']['enabled'] = value
            elif key == 'DUCKDNS_DOMAIN':
                CONFIG['duckdns']['domain'] = value
            elif key == 'DUCKDNS_TOKEN':
                CONFIG['duckdns']['token'] = value
            
            # === AUTO-UPDATER SETTINGS ===
            elif key == 'GITHUB_REPO':
                CONFIG['update']['github_repo'] = value
            elif key == 'UPDATES_FOLDER':
                CONFIG['update']['updates_folder'] = value
            elif key == 'CHECK_INTERVAL':
                CONFIG['update']['check_interval'] = value
            elif key == 'LAST_CHECKED':
                CONFIG['update']['last_checked'] = value
            elif key == 'UPDATE_NOTIFICATION':
                # This is handled by environment variable only
                pass
            elif key == 'ENABLE_AUTO_UPDATE':
                CONFIG['update']['enabled'] = value
            
            # === FLASK APP SETTINGS ===
            elif key == 'APP_VERSION':
                CONFIG['app']['version'] = value
            elif key == 'FLASK_DEBUG':
                CONFIG['app']['debug'] = value
            elif key == 'SERVER_PORT':
                CONFIG['app']['port'] = int(value) if value else 5000
            elif key == 'LATEST_VERSION':
                # This is handled by environment variable only
                pass
            
            # === LOGGING ===
            elif key == 'LOG_LEVEL':
                # Update logging level if needed
                logging.getLogger().setLevel(getattr(logging, value.upper()))
            
            # === TUNNEL SETTINGS ===
            elif key == 'TUNNEL_ENABLED':
                CONFIG['tunnel']['enabled'] = value
            elif key == 'PINGGY_AUTH_TOKEN':
                # Tunnel settings aren't in CONFIG by default, but we'll set env var
                pass
            elif key == 'PINGGY_RESERVED_SUBDOMAIN':
                # Tunnel settings aren't in CONFIG by default, but we'll set env var
                pass
            
            # === UPDATE INFO ===
            elif key == 'UPDATE_APPLIED':
                # This is handled by environment variable only
                pass
            elif key == 'UPDATE_APPLIED_VERSION':
                # This is handled by environment variable only
                pass
        
        return jsonify({'success': True})
    
    except Exception as e:
        logging.error(f"Error saving configuration: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
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

@app.errorhandler(Exception)
def handle_exception(e):
    logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
    return jsonify({'error': 'An unexpected error occurred'}), 500

required_env = ['RADARR_URL', 'RADARR_API_KEY', 'SONARR_URL', 'SONARR_API_KEY']
missing = [key for key in required_env if not os.getenv(key)]
if missing:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")

@app.route('/api/pwa/health')
def pwa_health():
    """Health check endpoint for PWA"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': CONFIG['app']['version']
    })

#################################### --- PINGGY TUNNEL START --- ####################################
def start_pinggy_tunnel():
    """Start Pinggy tunnel with Pro support"""
    global tunnel_process, tunnel_url
    
    # Check if pinggy is available
    if not PINGGY_AVAILABLE:
        print("❌ Pinggy module not available. Cannot start tunnel.")
        logging.error("Pinggy module not available. Cannot start tunnel.")
        return
    
   
    def tunnel_worker():
        global tunnel_process, tunnel_url
        try:
            print("🚀 Starting Pinggy Pro tunnel...")
            logging.info("Starting Pinggy Pro tunnel...")
            
            # For Pinggy Pro: Use token and reserved subdomain
            pinggy_token = os.getenv('PINGGY_AUTH_TOKEN')
            reserved_subdomain = os.getenv('PINGGY_RESERVED_SUBDOMAIN') # e.g., "addarr"
            
            # Build the connection arguments
            connection_args = {
                'forwardto': f"localhost:{CONFIG['app']['port']}",
                'type': 'http',
                'headermodification': ["X-Pinggy-No-Screen:bypass"],
                'force': True
            }
            
            # For Pinggy Pro with token authentication
            if pinggy_token and reserved_subdomain:
                # Remove .a.pinggy.link if present, just use the subdomain name
                clean_subdomain = reserved_subdomain.replace('.a.pinggy.link', '').replace('.pinggy.io', '')
                # The token+subdomain combination goes in the 'token' parameter
                connection_args['token'] = f"{pinggy_token}+{clean_subdomain}"
                print(f"🔐 Using Pinggy Pro authentication & subdomain: {clean_subdomain}")
            elif pinggy_token:
                connection_args['token'] = pinggy_token
                print("🔐 Using Pinggy Pro authentication")
            else:
                print("🔐 Using public Pinggy tunnel")
            
            print(f"🎯 Starting tunnel on port {CONFIG['app']['port']}...")
            print("🔄 Establishing tunnel connection...")
            
            # Start the tunnel with the correct parameters
            tunnel_process = pinggy.start_tunnel(**connection_args)
            
            # Wait for tunnel with timeout
            import time
            start_time = time.time()
            max_wait = 30  # 30 second timeout
            
            print("⏳ Waiting for tunnel URLs...", end="", flush=True)
            
            while not hasattr(tunnel_process, 'urls') or not tunnel_process.urls:
                if time.time() - start_time > max_wait:
                    raise Exception(f"Tunnel connection timeout after {max_wait} seconds")
                time.sleep(1)
                print(".", end="", flush=True)  # Show progress
            
            print()  # New line after progress dots
            
            if tunnel_process.urls:
                tunnel_url = tunnel_process.urls[1] if len(tunnel_process.urls) > 1 else tunnel_process.urls[0]
                print(f"✅ Pinggy Pro tunnel started successfully!")
                print(f"   🌐 Public URL: {tunnel_url}")                
                logging.info(f"Pinggy Pro tunnel started: {tunnel_url}")
            else:
                raise Exception("No tunnel URLs received")
            
        except Exception as e:
            print(f"\n❌ Tunnel failed: {e}")
            logging.error(f"Tunnel failed: {str(e)}")
            logging.error(traceback.format_exc())
            tunnel_url = None
    
    # Start tunnel in separate thread
    print("🧵 Starting tunnel thread...")
    tunnel_thread = threading.Thread(target=tunnel_worker, daemon=True, name="PinggyTunnel")
    tunnel_thread.start()
    
    # Don't wait for completion - let it run in background
    print("📡 Tunnel thread started (running in background)")

def cleanup_tunnel():
    """Clean up tunnel on shutdown"""
    global tunnel_process
    if tunnel_process:
        try:
            print("🔄 Stopping tunnel...")
            logging.info("Stopping tunnel...")
            # Try to close the tunnel gracefully
            if hasattr(tunnel_process, 'close'):
                tunnel_process.close()
            tunnel_process = None
        except Exception as e:
            print(f"Warning: Error closing tunnel: {e}")
            logging.warning(f"Error closing tunnel: {str(e)}")

# Register cleanup
atexit.register(cleanup_tunnel)

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

#################################### --- PINGGY TUNNEL END --- ####################################

#################################### --- QRCODE START --- ####################################
@debug_log
def display_enhanced_qr_code(url):
    """Display an enhanced QR code with better formatting"""
    try:
        import qrcode
        
        # Create QR code with optimal settings for console
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,  # Very small for compact display
            border=1,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        # Print the QR code
        qr.print_ascii(invert=True)
        
    except ImportError:
        print("❌ QR code display unavailable - install: pip install qrcode[pil]")
    except Exception as e:
        print(f"❌ QR code error: {e}")
#################################### --- QRCODE END --- ####################################


#################################### --- INFOPANEL START --- ####################################
@app.route('/api/info/network')
@debug_log
def get_network_info():
    """Get network information for the info panel"""
    try:
        # Get global tunnel_url if available
        global tunnel_url
        current_tunnel_url = tunnel_url if tunnel_url else None
        
        return jsonify({
            'local_ip': get_ip_address(),
            'port': CONFIG['app']['port'],
            'duckdns_enabled': CONFIG['duckdns']['enabled'],
            'duckdns_domain': CONFIG['duckdns']['domain'],
            'tunnel_enabled': CONFIG['tunnel']['enabled'],
            'tunnel_url': current_tunnel_url,
            'tunnel_active': current_tunnel_url is not None
        })
    except Exception as e:
        logging.error(f"Error getting network info: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/info/changelog')
@debug_log
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
        import re
        
        # Find all version sections (starting with ## [version_number])
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
@debug_log
def get_last_updated():
    """Get the last updated time of the application"""
    try:
        app_path = os.path.abspath(__file__)
        stat = os.stat(app_path)
        last_updated = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'last_updated': last_updated,
            'app_file': app_path
        })
    except Exception as e:
        logging.error(f"Error getting last updated time: {str(e)}")
        return jsonify({'error': str(e)}), 500
#################################### --- INFOPANEL END--- ####################################

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

@app.route('/')
@debug_log
def index():
    try:
        return render_template(
            'index.html',
            config=CONFIG
        )
    
    except Exception as e:
        logging.error(f"Error loading index: {str(e)}", exc_info=True)
        return render_template(
            'index.html',
            error="Page load failed"
        )
    
def print_welcome():
    """Print welcome message and logo only once"""
    from colorama import Fore, Style

    app_info = f"""
    {Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}
    {Fore.WHITE}• Version: {CONFIG['app']['version']}
    {Fore.WHITE}• Local: {Fore.CYAN}http://127.0.0.1:{CONFIG['app']['port']}{Style.RESET_ALL}
    {Fore.WHITE}• Network: {Fore.CYAN}http://{get_ip_address()}:{CONFIG['app']['port']}{Style.RESET_ALL}
    """
    
    # Check if tunnel URL is available (it might be set by the tunnel thread)
    global tunnel_url
    if tunnel_url:
        app_info += f"{Fore.WHITE}• Tunnel: {Fore.CYAN}{tunnel_url}{Style.RESET_ALL}\n"
    elif CONFIG['tunnel']['enabled']:
        app_info += f"{Fore.WHITE}• Tunnel: {Fore.YELLOW}Starting...{Style.RESET_ALL}\n"
    
    if CONFIG['duckdns']['enabled'] and CONFIG['duckdns']['domain']:
        app_info += f"""\t{Fore.WHITE}• DuckDNS: {Fore.CYAN}http://{CONFIG['duckdns']['domain']}.duckdns.org:{CONFIG['app']['port']}{Style.RESET_ALL}\n"""
    
    try:
        my_art = AsciiArt.from_image('static/images/logo.png')
        my_art.to_terminal()
    except Exception as e:
        # Fallback if logo isn't available
        print(f"{Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}")
    
    print(app_info)
    if tunnel_url:
        display_enhanced_qr_code(tunnel_url)

    print(f"{Fore.GREEN}✅ Ready to add media!{Style.RESET_ALL}\n")
    print(f"{Fore.YELLOW}Press Ctrl-C to shutdown{Style.RESET_ALL}")

if __name__ == '__main__':
    from colorama import init
    init()

    if CONFIG['update']['enabled']:
        restart_needed = perform_initial_update_check()

        if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
            # BLOCKING UPDATE CHECK - runs first before anything else
            restart_needed = perform_initial_update_check()
            
            # If an update was applied and restart is needed, we should exit here
            if restart_needed:
                logging.info("🔄 Update applied, waiting for restart...")
                # Give a moment for logs to flush
                time.sleep(2)
                logging.info("🚀 Exiting main process to allow restart...")
                # Exit completely to allow the new process to take over
                sys.exit(0)

        # Only continue if no restart is needed
        # Start DuckDNS if enabled
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

    # Print welcome message in main process only
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        # Start tunnel if enabled
        if CONFIG['tunnel']['enabled']:
            print("🔧 Starting tunnel in main process...")
            start_pinggy_tunnel()
            
            # Wait for tunnel to establish (success or failure) before printing welcome
            import time
            print("⏳ Waiting for tunnel to establish...", end="", flush=True)
            
            for i in range(15):  # Wait up to 15 seconds
                # Check if tunnel has either succeeded (has URL) or failed (None after error)
                if tunnel_url is not None:  # This will be True if URL exists or False if failed
                    break
                time.sleep(1)
                print(".", end="", flush=True)
            
            print()  # New line after progress dots
            
            if tunnel_url:
                print(f"✅ Tunnel established: {tunnel_url}")
            else:
                print("❌ Tunnel failed to establish within timeout")
        
        # Print welcome message after tunnel status is determined
        print_welcome()
    
    try:
        app.run(host='0.0.0.0', debug=CONFIG['app']['debug'], port=CONFIG['app']['port'], use_reloader=True)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        cleanup_tunnel()
        sys.exit(0)