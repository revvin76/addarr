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
import sys

class UpdateManager:
    """Memory-efficient update management"""
    def __init__(self, config):
        self.config = config
        self.update_thread = None
        self.running = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event() 
        self.current_channel = self.config.update.channel
        self._update_in_progress = False
        self._update_lock = threading.Lock()
    
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
        """Check GitHub for updates with branch/channel support"""
        logging.info(f"Check GitHub for updates on {self.current_channel} channel...")
        if self.mock_mode:
            return self._mock_check_for_updates()

        try:
            # Use releases for PROD, latest commit for DEV
            if self.current_channel == 'prod':
                return self._check_prod_updates()
            else:
                return self._check_dev_updates()
                
        except Exception as e:
            logging.error(f"Error checking for updates: {str(e)}")
            return {'update_available': False, 'error': str(e)}
        
    def _handle_available_update(self, update_info):
            """Handle available update with memory considerations"""
            # Prevent concurrent updates
            with self._update_lock:
                if self._update_in_progress:
                    logging.info("🔄 Update already in progress, skipping...")
                    return
                    
                self._update_in_progress = True
            
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
            finally:
                # Always release the lock
                with self._update_lock:
                    self._update_in_progress = False

    def _check_prod_updates(self):
            """Check for PROD updates using releases"""
            url = f"https://api.github.com/repos/{self.config.update.github_repo}/releases/latest"
            
            logging.info(f"Checking PROD releases: {url}")
            headers = {
                'User-Agent': 'Addarr-Update-Checker',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            github_token = os.getenv('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
            
            with requests.get(url, timeout=10, headers=headers) as response:
                if response.status_code == 200:
                    latest_release = response.json()
                    current_version = self.config.app.version
                    latest_version = latest_release.get('tag_name', '').lstrip('v')
                    
                    logging.info(f"PROD - Current: {current_version}, Latest: {latest_version}")
                    
                    if version.parse(latest_version) > version.parse(current_version):
                        return {
                            'update_available': True,
                            'current_version': current_version,
                            'latest_version': latest_version,
                            'release_url': latest_release.get('html_url'),
                            'release_notes': latest_release.get('body', '')[:500],
                            'published_at': latest_release.get('published_at'),
                            'channel': 'prod'
                        }
                    else:
                        logging.info("No PROD update available")
                else:
                    logging.warning(f"GitHub API returned status {response.status_code}")
                    
            return {'update_available': False, 'channel': 'prod'}
        
    def _check_dev_updates(self):
        """Check for DEV updates using latest commit on dev branch"""
        try:
            # Get latest commit from dev branch
            url = f"https://api.github.com/repos/{self.config.update.github_repo}/branches/dev"
            
            headers = {
                'User-Agent': 'Addarr-Update-Checker',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            github_token = os.getenv('GITHUB_TOKEN')
            if github_token:
                headers['Authorization'] = f'token {github_token}'
            
            with requests.get(url, timeout=10, headers=headers) as response:
                if response.status_code == 200:
                    branch_info = response.json()
                    latest_commit_sha = branch_info['commit']['sha'][:7]  # Short SHA
                    latest_commit_date = branch_info['commit']['commit']['committer']['date']
                    
                    # Get current version/commit from environment
                    current_version = self.config.app.version  # This is "1.1.0-dev"
                    current_commit = os.getenv('APP_COMMIT', '')  # This should be "8d55f80"
                    
                    # For DEV updates, we'll use the full version format
                    needs_update = current_commit != latest_commit_sha
                    
                    if needs_update:
                        # Use the full version format: base_version + commit
                        dev_version = f"{current_version}-{latest_commit_sha}"  # "1.1.0-dev-694ba95"
                        
                        return {
                            'update_available': True,
                            'current_version': f"{current_version}-{current_commit}" if current_commit else current_version,
                            'latest_version': dev_version,  # This will be "1.1.0-dev-694ba95"
                            'latest_commit': latest_commit_sha,
                            'commit_date': latest_commit_date,
                            'release_url': f"https://github.com/{self.config.update.github_repo}/commit/{latest_commit_sha}",
                            'release_notes': f"Dev update - Commit: {latest_commit_sha}",
                            'channel': 'dev'
                        }
                    else:
                        logging.info("No DEV update available - already on latest commit")
                else:
                    logging.warning(f"GitHub API returned status {response.status_code}")
                    
            return {'update_available': False, 'channel': 'dev'}
            
        except Exception as e:
            logging.error(f"Error checking DEV updates: {str(e)}")
            return {'update_available': False, 'error': str(e), 'channel': 'dev'}
               
    def _download_update(self, version):
        """Download update with improved DEV branch support"""
        try:
            logging.info(f"📥 Downloading {self.current_channel} update: {version}")
            
            if self.mock_mode:
                logging.info(f"🔧 MOCK MODE: Would download {self.current_channel} update {version}")
                time.sleep(2)
                return {'success': True, 'version': version, 'channel': self.current_channel}
            
            updates_folder = self.ensure_updates_folder()
            repo = self.config.update.github_repo
            
            if self.current_channel == 'prod':
                # Download from release
                download_url = f"https://github.com/{repo}/archive/refs/tags/v{version}.zip"
                # Use simple filename for PROD
                filename = f"addarr_{version}.zip"
            else:
                # Download from dev branch
                download_url = f"https://github.com/{repo}/archive/refs/heads/dev.zip"
                # For DEV, use the exact version string for filename
                filename = f"addarr_dev_{version}.zip"
            
            logging.info(f"🔗 Download URL: {download_url}")
            logging.info(f"📁 Target filename: {filename}")
            
            # Download the file
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            file_path = os.path.join(updates_folder, filename)
            
            # Stream download to file
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        if total_size > 0 and downloaded_size % (1024 * 1024) == 0:
                            progress = (downloaded_size / total_size) * 100
                            logging.info(f"Download progress: {progress:.1f}%")
            
            # Verify the file was created
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                logging.info(f"✅ Successfully downloaded {self.current_channel} update: {filename}")
                logging.info(f"📁 File saved as: {file_path} (size: {file_size} bytes)")
                
                # List files in updates folder to confirm
                updates_files = os.listdir(updates_folder)
                logging.info(f"📋 Updates folder now contains: {updates_files}")
                
                # Clean up old updates
                self.cleanup_old_updates()
                
                return {
                    'success': True, 
                    'version': version,
                    'file_path': file_path,
                    'filename': filename,
                    'channel': self.current_channel
                }
            else:
                raise Exception(f"Downloaded file missing: {file_path}")
                
        except Exception as e:
            logging.error(f"❌ Download error: {str(e)}")
            if 'file_path' in locals() and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logging.info(f"🗑️ Cleaned up partial download: {file_path}")
                except Exception as cleanup_error:
                    logging.error(f"❌ Cleanup error: {cleanup_error}")
            return {'success': False, 'error': str(e), 'channel': self.current_channel}
    
    def _apply_update(self, version):
        """Apply update with improved version matching"""
        try:
            logging.info(f"🔄 Applying update: {version}")
            
            if self.mock_mode:
                logging.info(f"🔧 MOCK MODE: Would apply update {version}")
                self._simulate_update_application(version)
                return {'success': True, 'version': version}
            
            # Find the downloaded update
            updates = self.get_downloaded_updates_optimized()
            target_update = None
            
            logging.info(f"🔍 Looking for update version: '{version}'")
            logging.info(f"📁 Available updates: {[u['version'] for u in updates]}")
            
            # First try exact match
            for update in updates:
                if update['version'] == version:
                    target_update = update
                    logging.info(f"✅ Found exact match: {update['filename']} -> {update['version']}")
                    break
            
            if not target_update:
                # For DEV updates, try matching by commit part
                if self.current_channel == 'dev' and '-' in version:
                    commit_part = version.split('-')[-1]
                    logging.info(f"🔍 Trying commit match: '{commit_part}'")
                    
                    for update in updates:
                        if update['version'].endswith(commit_part):
                            target_update = update
                            logging.info(f"✅ Found commit match: {update['filename']} -> {update['version']}")
                            break
            
            if not target_update and updates:
                # If no match found but updates exist, use the most recent one
                target_update = updates[0]
                logging.info(f"⚠️ No exact match found, using most recent: {target_update['filename']}")
            
            if not target_update:
                available_versions = [u['version'] for u in updates]
                raise Exception(f"Update file for version '{version}' not found. Available: {available_versions}")
            
            # Verify the file actually exists
            if not os.path.exists(target_update['file_path']):
                raise Exception(f"Update file missing: {target_update['file_path']}")
            
            logging.info(f"✅ Using update file: {target_update['file_path']}")
            
            # Create backup before applying update
            backup_path = self.backup_env_file()
            if backup_path:
                logging.info(f"📋 Created backup: {backup_path}")
            
            # Extract and apply update
            success = self._extract_and_replace(target_update['file_path'])
            
            if success:
                logging.info(f"✅ Successfully applied update: {version}")
                
                # Update version and commit in environment
                self.set_env('APP_VERSION', version)
                if self.current_channel == 'dev':
                    # Extract and store the commit SHA for future update checks
                    commit_part = version.split('-')[-1] if '-' in version else version
                    self.set_env('APP_COMMIT', commit_part)
                    logging.info(f"💾 Updated APP_COMMIT to: {commit_part}")
                
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
            app_root = os.path.dirname(os.path.abspath(sys.argv[0]))
            
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
                self._copy_update_files(source_dir, app_root)
                
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
        """Get downloaded updates with improved version parsing"""
        try:
            updates_folder = self.ensure_updates_folder()
            update_files = []
            
            logging.info(f"🔍 Scanning updates folder: {updates_folder}")
            
            # List all files in the updates folder for debugging
            all_files = os.listdir(updates_folder)
            logging.info(f"📁 All files in updates folder: {all_files}")
            
            for filename in os.listdir(updates_folder):
                if filename.startswith('addarr_') and filename.endswith('.zip'):
                    file_path = os.path.join(updates_folder, filename)
                    if not os.path.exists(file_path):
                        continue
                        
                    file_stat = os.stat(file_path)
                    
                    logging.info(f"📄 Processing file: {filename}")
                    
                    # Handle the exact filename pattern: addarr_dev_1.0.0-dev-694ba95.zip
                    if filename.startswith('addarr_dev_'):
                        # Remove 'addarr_dev_' prefix (11 chars) and '.zip' suffix (4 chars)
                        # filename: "addarr_dev_1.0.0-dev-694ba95.zip" -> version: "1.0.0-dev-694ba95"
                        version = filename[11:-4]  # FIXED: Changed from 12 to 11
                        logging.info(f"🔧 DEV file detected, version: {version}")
                    elif filename.startswith('addarr_prod_'):
                        # PROD branch format: addarr_prod_1.0.0.zip  
                        version = filename[12:-4]  # Remove 'addarr_prod_' (12 chars) and '.zip' (4 chars)
                    else:
                        # Legacy format: addarr_1.0.0.zip
                        version = filename[7:-4]  # Remove 'addarr_' (7 chars) and '.zip' (4 chars)
                    
                    update_files.append({
                        'filename': filename,
                        'version': version,  # This should now be "1.0.0-dev-694ba95"
                        'file_path': file_path,
                        'size': file_stat.st_size,
                        'downloaded_at': file_stat.st_mtime,
                        'formatted_size': self.format_file_size(file_stat.st_size),
                        'formatted_date': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
            
            logging.info(f"📋 Found {len(update_files)} update files: {[u['version'] for u in update_files]}")
            
            # Sort by date (newest first)
            update_files.sort(key=lambda x: x['downloaded_at'], reverse=True)
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
    