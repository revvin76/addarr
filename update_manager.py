import threading
import time
import logging
import gc
import requests
from packaging import version

class UpdateManager:
    """Memory-efficient update management"""
    def __init__(self, config):
        self.config = config
        self.update_thread = None
        self.running = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()  # Add stop event
    
    def start(self):
        if self.running:
            return
        
        with self._lock:
            self.running = True
            self._stop_event.clear()
            self.update_thread = threading.Thread(
                target=self._update_checker, 
                daemon=True,
                name="UpdateChecker"
            )
            self.update_thread.start()
            logging.info("Update manager started")
    
    def stop(self):
        """Stop the update manager"""
        with self._lock:
            self.running = False
            self._stop_event.set()  # Signal thread to stop
            
        if self.update_thread and self.update_thread.is_alive():
            try:
                self.update_thread.join(timeout=3.0)
                if self.update_thread.is_alive():
                    logging.warning("Update thread did not stop gracefully")
            except Exception as e:
                logging.warning(f"Error stopping update thread: {e}")
                
        logging.info("Update manager stopped")
    
    def _update_checker(self):
        """Memory-optimized background update checker"""
        while self.running and not self._stop_event.is_set():
            try:
                current_time = time.time()
                last_checked = self.config.update.last_checked
                check_interval = self.config.update.check_interval
                
                if current_time - last_checked >= check_interval:
                    if self.config.app.debug:
                        logging.info("Automated update check running...")
                    
                    update_info = self._check_github_for_updates()
                    if update_info.get('update_available'):
                        self._handle_available_update(update_info)
                    
                    # Update last_checked - you'll need to implement this
                    # self.set_env('LAST_CHECKED', str(current_time))
                
                # Use wait with timeout for quicker shutdown
                if self._stop_event.wait(timeout=check_interval):
                    break
                
            except Exception as e:
                logging.error(f"Update checker error: {str(e)}")
                # Shorter sleep on error, but check stop event
                if self._stop_event.wait(timeout=300):
                    break
    
    def _check_github_for_updates(self):
        """Check GitHub for updates with memory efficiency"""
        try:
            url = f"https://api.github.com/repos/{self.config.update.github_repo}/releases/latest"
            with requests.get(url, timeout=10) as response:
                if response.status_code == 200:
                    latest_release = response.json()
                    current_version = self.config.app.version
                    latest_version = latest_release.get('tag_name', '').lstrip('v')
                    
                    if version.parse(latest_version) > version.parse(current_version):
                        return {
                            'update_available': True,
                            'current_version': current_version,
                            'latest_version': latest_version,
                            'release_url': latest_release.get('html_url'),
                            'release_notes': latest_release.get('body', '')[:500],
                            'published_at': latest_release.get('published_at')
                        }
            return {'update_available': False}
        except Exception as e:
            logging.error(f"Error checking for updates: {str(e)}")
            return {'update_available': False, 'error': str(e)}
    
    def _handle_available_update(self, update_info):
        """Handle available update with memory considerations"""
        latest_version = update_info['latest_version']
        logging.info(f"Auto-check: Update available: {latest_version}")
        
        existing_updates = self.get_downloaded_updates_optimized()
        already_downloaded = any(update['version'] == latest_version for update in existing_updates)
        
        if not already_downloaded:
            download_result = self._download_update(latest_version)
            if download_result.get('success'):
                logging.info(f"Auto-downloaded update: {download_result['version']}")
                self._apply_update(download_result['version'])
        else:
            self._apply_update(latest_version)
    
    def _download_update(self, version):
        """Download update with memory efficiency"""
        try:
            # TODO: Implement actual download logic
            logging.info(f"Would download update: {version}")
            return {'success': True, 'version': version}
        except Exception as e:
            logging.error(f"Download error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _apply_update(self, version):
        """Apply update with memory cleanup"""
        try:
            # TODO: Implement actual apply logic
            logging.info(f"Would apply update: {version}")
            return {'success': True, 'version': version}
        except Exception as e:
            logging.error(f"Apply error: {str(e)}")
            return {'success': False, 'error': str(e)}   
    
    def backup_env_file():
        """Create a timestamped backup of the .env file"""
        try:
            env_path = os.path.join(os.path.dirname(__file__), '.env')
            backup_path = os.path.join(os.path.dirname(__file__), f".env.backup.{int(time.time())}")
            
            if os.path.exists(env_path):
                shutil.copy2(env_path, backup_path)
                logging.info(f"✅ Created .env backup: {backup_path}")
                return backup_path
            return None
        except Exception as e:
            logging.error(f"❌ Failed to create .env backup: {str(e)}")
            return None
        
    def set_env(key, value):
        # """Set an environment variable in the .env file"""
        try:
            env_path = os.path.join(os.path.dirname(__file__), '.env')
            env_lines = []
            
            # Create backup before making changes (only once per session)
            if not hasattr(set_env, 'backup_created'):
                backup_env_file()
                set_env.backup_created = True
            
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
    
    def ensure_updates_folder():
        # Get the directory where the app is running from
        base_dir = os.path.dirname(os.path.abspath(__file__))
        updates_folder = os.path.join(base_dir, CONFIG['update']['updates_folder'])
        
        if not os.path.exists(updates_folder):
            os.makedirs(updates_folder)
            logging.info(f"Created updates folder: {updates_folder}")
        return updates_folder
    
    def get_downloaded_updates_optimized(self):
        # """Get downloaded updates"""
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
