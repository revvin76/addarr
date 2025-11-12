import threading
import time
import logging
import gc
import requests
from packaging import version
import os
import shutil
import zipfile
import tempfile
import subprocess
from datetime import datetime

class UpdateManager:
    """Memory-efficient update management"""
    def __init__(self, config):
        self.config = config
        self.update_thread = None
        self.running = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()  # Add stop event
    
        # Mock mode support
        self.mock_mode = os.getenv('MOCK_UPDATE', 'false').lower() == 'true'
        if self.mock_mode:
            logging.info("🔧 Update manager running in MOCK MODE")

    def _mock_check_for_updates(self):
        """Mock method to simulate update checks"""
        logging.info("Check local mock server for updates...")
        try:
            # Use local mock server
            mock_url = "http://localhost:5001/repos/revvin76/addarr/releases/latest"
            response = requests.get(mock_url, timeout=5)
            
            if response.status_code == 200:
                mock_release = response.json()
                current_version = self.config.app.version
                latest_version = mock_release.get('tag_name', '').lstrip('v')
                
                # Always return update available in mock mode for testing
                logging.info(f"🔧 MOCK MODE: Update available: {latest_version} (current: {current_version})")
                
                return {
                    'update_available': True,
                    'current_version': current_version,
                    'latest_version': latest_version,
                    'release_url': mock_release.get('html_url'),
                    'release_notes': mock_release.get('body', '')[:500],
                    'published_at': mock_release.get('published_at'),
                    'zipball_url': mock_release.get('zipball_url'),
                    'mock': True  # Flag to indicate this is a mock update
                }
            
            # Fallback: simulate update available
            return {
                'update_available': True,
                'current_version': self.config.app.version,
                'latest_version': '99.0.0-test',
                'release_url': 'https://example.com/mock-update',
                'release_notes': 'Mock update for testing',
                'published_at': '2024-01-01T00:00:00Z',
                'mock': True
            }
            
        except Exception as e:
            logging.error(f"Mock update check failed: {str(e)}")
            # Simulate network failure or return mock update
            return {
                'update_available': True,
                'current_version': self.config.app.version,
                'latest_version': '99.0.0-test',
                'error': 'Mock network error',
                'mock': True
            }
        
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
        logging.info("Check GitHub for updates...")
        if self.mock_mode:
            return self._mock_check_for_updates()

        try:
            url = f"https://api.github.com/repos/{self.config.update.github_repo}/releases/latest"
            
            logging.info(url)
            # Add headers to avoid rate limiting
            headers = {
                'User-Agent': 'Addarr-Update-Checker',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            # Add GitHub token if available for higher rate limits
            github_token = os.getenv('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
            
            with requests.get(url, timeout=10, headers=headers) as response:
                if response.status_code == 200:
                    latest_release = response.json()
                    current_version = self.config.app.version
                    latest_version = latest_release.get('tag_name', '').lstrip('v')
                    
                    logging.info(f"Current: {current_version}, Latest: {latest_version}")
                    
                    if version.parse(latest_version) > version.parse(current_version):
                        return {
                            'update_available': True,
                            'current_version': current_version,
                            'latest_version': latest_version,
                            'release_url': latest_release.get('html_url'),
                            'release_notes': latest_release.get('body', '')[:500],
                            'published_at': latest_release.get('published_at')
                        }
                    else:
                        logging.info("No update available - already on latest version")
                else:
                    logging.warning(f"GitHub API returned status {response.status_code}")
                    
            return {'update_available': False}
        except Exception as e:
            logging.error(f"Error checking for updates: {str(e)}")
            return {'update_available': False, 'error': str(e)}
        
    def _handle_available_update(self, update_info):
        """Handle available update with memory considerations"""
        try:
            latest_version = update_info['latest_version']
            logging.info(f"🔄 Auto-check: Update available: {latest_version}")
            
            existing_updates = self.get_downloaded_updates_optimized()
            already_downloaded = any(update['version'] == latest_version for update in existing_updates)
            
            if not already_downloaded:
                logging.info(f"📥 Downloading new update: {latest_version}")
                download_result = self._download_update(latest_version)
                if download_result.get('success'):
                    logging.info(f"✅ Auto-downloaded update: {download_result['version']}")
                    # Small delay before applying to ensure download is complete
                    time.sleep(2)
                    apply_result = self._apply_update(download_result['version'])
                    if apply_result.get('success'):
                        logging.info(f"🎉 Successfully applied auto-update to {download_result['version']}")
                    else:
                        logging.error(f"❌ Failed to apply auto-update: {apply_result.get('error')}")
                else:
                    logging.error(f"❌ Failed to download update: {download_result.get('error')}")
            else:
                logging.info(f"📦 Update already downloaded, applying: {latest_version}")
                apply_result = self._apply_update(latest_version)
                if apply_result.get('success'):
                    logging.info(f"🎉 Successfully applied existing update to {latest_version}")
                else:
                    logging.error(f"❌ Failed to apply existing update: {apply_result.get('error')}")
                    
        except Exception as e:
            logging.error(f"❌ Error handling available update: {str(e)}")
                
    def _download_update(self, version):
        """Download update with memory efficiency"""
        try:
            logging.info(f"📥 Downloading update: {version}")
            
            if self.mock_mode:
                # Mock download for testing
                logging.info(f"🔧 MOCK MODE: Would download update {version}")
                time.sleep(2)  # Simulate download time
                return {'success': True, 'version': version}
            
            # Ensure updates folder exists
            updates_folder = self.ensure_updates_folder()
            
            # Construct download URL
            repo = self.config.update.github_repo
            download_url = f"https://github.com/{repo}/archive/refs/tags/v{version}.zip"
            
            # Download the release
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Save to file
            filename = f"addarr_{version}.zip"
            file_path = os.path.join(updates_folder, filename)
            
            # Stream download to file to save memory
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:  # filter out keep-alive chunks
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # Log progress for large downloads
                        if total_size > 0 and downloaded_size % (1024 * 1024) == 0:  # Every 1MB
                            progress = (downloaded_size / total_size) * 100
                            logging.info(f"Download progress: {progress:.1f}%")
            
            # Verify download
            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                logging.info(f"✅ Successfully downloaded update: {version}")
                
                # Clean up old updates
                self.cleanup_old_updates()
                
                return {
                    'success': True, 
                    'version': version,
                    'file_path': file_path,
                    'filename': filename
                }
            else:
                raise Exception("Downloaded file is empty or missing")
                
        except Exception as e:
            logging.error(f"❌ Download error: {str(e)}")
            # Clean up partial download
            if 'file_path' in locals() and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            return {'success': False, 'error': str(e)}

    def _apply_update(self, version):
        """Apply update with memory cleanup"""
        try:
            logging.info(f"🔄 Applying update: {version}")
            
            if self.mock_mode:
                # Mock apply for testing
                logging.info(f"🔧 MOCK MODE: Would apply update {version}")
                # Simulate update process
                self._simulate_update_application(version)
                return {'success': True, 'version': version}
            
            # Find the downloaded update
            updates = self.get_downloaded_updates_optimized()
            target_update = None
            
            for update in updates:
                if update['version'] == version:
                    target_update = update
                    break
            
            if not target_update:
                raise Exception(f"Update file for version {version} not found")
            
            # Create backup before applying update
            self.backup_env_file()
            
            # Extract and apply update
            success = self._extract_and_replace(target_update['file_path'])
            
            if success:
                logging.info(f"✅ Successfully applied update: {version}")
                
                # Update version in environment
                self.set_env('APP_VERSION', version)
                
                # Force garbage collection
                gc.collect()
                
                return {'success': True, 'version': version}
            else:
                raise Exception("Update extraction failed")
                
        except Exception as e:
            logging.error(f"❌ Apply error: {str(e)}")
            return {'success': False, 'error': str(e)}

    def _extract_and_replace(self, zip_path):
        """Extract update zip and replace files"""
        try:
            # Get current app directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            
            # Create temporary extraction directory
            with tempfile.TemporaryDirectory() as temp_dir:
                logging.info(f"📦 Extracting update to temporary directory...")
                
                # Extract zip file
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Find the extracted root directory (usually repo-name-version/)
                extracted_items = os.listdir(temp_dir)
                if len(extracted_items) == 1:
                    source_dir = os.path.join(temp_dir, extracted_items[0])
                else:
                    source_dir = temp_dir
                
                # Copy files, preserving .env and config
                self._copy_update_files(source_dir, parent_dir)
                
            return True
            
        except Exception as e:
            logging.error(f"❌ Extraction error: {str(e)}")
            return False

    def _copy_update_files(self, source_dir, target_dir):
        """Copy update files while preserving configuration"""
        try:
            # Files and directories to preserve (not overwrite)
            preserve_items = [
                '.env',
                'addarr.log',
                'updates',
                '__pycache__',
                'instance'
            ]
            
            # Walk through source directory
            for root, dirs, files in os.walk(source_dir):
                # Calculate relative path
                rel_path = os.path.relpath(root, source_dir)
                target_path = os.path.join(target_dir, rel_path)
                
                # Create target directory if it doesn't exist
                if rel_path != '.' and not os.path.exists(target_path):
                    os.makedirs(target_path)
                
                # Copy files
                for file in files:
                    source_file = os.path.join(root, file)
                    target_file = os.path.join(target_path, file)
                    
                    # Skip preserved files if they already exist
                    if file in preserve_items and os.path.exists(target_file):
                        logging.info(f"📋 Preserving existing file: {file}")
                        continue
                    
                    # Skip __pycache__ directories
                    if '__pycache__' in root:
                        continue
                    
                    try:
                        shutil.copy2(source_file, target_file)
                        if self.config.app.debug:
                            logging.debug(f"📄 Updated: {os.path.join(rel_path, file)}")
                    except Exception as e:
                        logging.warning(f"⚠️ Could not update {file}: {str(e)}")
            
            logging.info("✅ File update completed")
            return True
            
        except Exception as e:
            logging.error(f"❌ File copy error: {str(e)}")
            return False

    def _simulate_update_application(self, version):
        """Simulate update application for mock mode"""
        logging.info(f"🔧 MOCK: Simulating update application for version {version}")
        
        # Simulate some update activities
        time.sleep(1)
        
        # Update version in mock mode
        if hasattr(self.config, 'app') and hasattr(self.config.app, 'version'):
            old_version = self.config.app.version
            logging.info(f"🔧 MOCK: Version updated from {old_version} to {version}")
        
        # Simulate file operations
        updates_folder = self.ensure_updates_folder()
        mock_update_file = os.path.join(updates_folder, f"addarr_{version}.zip")
        
        if os.path.exists(mock_update_file):
            # Create a mock applied marker
            applied_marker = os.path.join(updates_folder, f"applied_{version}.txt")
            with open(applied_marker, 'w') as f:
                f.write(f"Mock update applied at {datetime.now().isoformat()}\n")
        
        logging.info("🔧 MOCK: Update simulation completed") 

    def backup_env_file(self):
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
        
    def set_env(self, key, value):
        """Set an environment variable in the .env file"""
        try:
            env_path = os.path.join(os.path.dirname(__file__), '.env')
            env_lines = []
            
            # Create backup before making changes (only once per session)
            if not hasattr(self, 'backup_created'):
                self.backup_env_file()
                self.backup_created = True
            
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
            if self.config.app.debug:  
                logging.info(f"Set {key}={value}")
            return True
            
        except Exception as e:
            logging.error(f"Error setting environment variable: {str(e)}")
            return False 
        
    def ensure_updates_folder(self):
        # Get the directory where the app is running from
        base_dir = os.path.dirname(os.path.abspath(__file__))
        updates_folder = os.path.join(base_dir, self.config.update.updates_folder)
        
        if not os.path.exists(updates_folder):
            os.makedirs(updates_folder)
            logging.info(f"Created updates folder: {updates_folder}")
        return updates_folder

    def format_file_size(self, size_bytes):  # ADD self parameter
        """Format file size in human-readable format"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.2f} {size_names[i]}"

    
    def get_downloaded_updates_optimized(self):
        # """Get downloaded updates"""
        try:
            updates_folder = self.ensure_updates_folder()
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
                        'formatted_size': self.format_file_size(file_stat.st_size),
                        'formatted_date': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
            
            # Sort by version (newest first)
            update_files.sort(key=lambda x: x['version'], reverse=True)
            return update_files
            
        except Exception as e:
            logging.error(f"Error getting downloaded updates: {str(e)}")
            return []

    def cleanup_old_updates(self, keep_count=3):
        # """Keep only the most recent updates and delete older ones"""
        try:
            update_files = self.get_downloaded_updates_optimized()
            
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
    