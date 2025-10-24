# version_manager.py
import subprocess
import json
import os
from datetime import datetime

class VersionManager:
    def __init__(self):
        self.version_file = 'version.json'
        self.repo_path = os.path.dirname(os.path.abspath(__file__))
    
    def get_current_version(self):
        """Get current version from version file or Git"""
        try:
            # Try to read from version file first
            if os.path.exists(self.version_file):
                with open(self.version_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        
        # Fallback to Git-based version
        return self._get_git_version()
    
    def _get_git_version(self):
        """Get version info from Git"""
        try:
            # Get latest commit hash and date
            commit_hash = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'], 
                cwd=self.repo_path
            ).decode().strip()
            
            commit_date = subprocess.check_output(
                ['git', 'show', '-s', '--format=%ci', 'HEAD'],
                cwd=self.repo_path
            ).decode().strip()
            
            # Count total commits for version number
            commit_count = subprocess.check_output(
                ['git', 'rev-list', '--count', 'HEAD'],
                cwd=self.repo_path
            ).decode().strip()
            
            return {
                'version': f"1.0.{commit_count}",
                'commit_hash': commit_hash,
                'commit_date': commit_date,
                'commit_count': int(commit_count),
                'build_date': datetime.now().isoformat()
            }
        except Exception as e:
            # Fallback if Git is not available
            return {
                'version': '1.0.0',
                'commit_hash': 'unknown',
                'commit_date': datetime.now().isoformat(),
                'commit_count': 0,
                'build_date': datetime.now().isoformat()
            }
    
    def save_version(self, version_info):
        """Save version info to file"""
        with open(self.version_file, 'w') as f:
            json.dump(version_info, f, indent=2)
    
    def check_for_updates(self):
        """Check if updates are available and return update info"""
        try:
            # Fetch latest changes
            subprocess.run(['git', 'fetch', 'origin'], 
                         cwd=self.repo_path, capture_output=True)
            
            # Get current and remote commit info
            local_commit = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=self.repo_path
            ).decode().strip()
            
            remote_commit = subprocess.check_output(
                ['git', 'rev-parse', 'origin/main'], cwd=self.repo_path
            ).decode().strip()
            
            if local_commit != remote_commit:
                # Get commit messages between local and remote
                commit_messages = subprocess.check_output(
                    ['git', 'log', '--pretty=format:%s', f'{local_commit}..{remote_commit}'],
                    cwd=self.repo_path
                ).decode().split('\n')
                
                # Get new version info
                new_commit_count = subprocess.check_output(
                    ['git', 'rev-list', '--count', 'HEAD'],
                    cwd=self.repo_path
                ).decode().strip()
                
                new_version = f"1.0.{new_commit_count}"
                
                return {
                    'update_available': True,
                    'current_version': self.get_current_version()['version'],
                    'new_version': new_version,
                    'changes': commit_messages,
                    'commit_hash': remote_commit[:7],
                    'update_date': datetime.now().isoformat()
                }
            
            return {'update_available': False}
            
        except Exception as e:
            logging.error(f"Update check failed: {str(e)}")
            return {'update_available': False, 'error': str(e)}
    
    def apply_update(self):
        """Apply available updates"""
        try:
            # Stash any local changes
            subprocess.run(['git', 'stash'], cwd=self.repo_path, capture_output=True)
            
            # Pull latest changes
            result = subprocess.run(
                ['git', 'pull', 'origin', 'main'], 
                cwd=self.repo_path, capture_output=True, text=True
            )
            
            if result.returncode == 0:
                # Update version file
                new_version = self._get_git_version()
                self.save_version(new_version)
                
                return {
                    'success': True,
                    'message': 'Update applied successfully',
                    'new_version': new_version,
                    'output': result.stdout
                }
            else:
                return {
                    'success': False,
                    'message': 'Update failed',
                    'error': result.stderr
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': 'Update failed',
                'error': str(e)
            }