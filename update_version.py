#!/usr/bin/env python3
"""
Version update script for Addarr.
Updates the VERSION file and propagates to all relevant files.
Usage: python update_version.py <new_version>
Example: python update_version.py 1.2.0
"""

import sys
import os
import re
from datetime import datetime

def update_version(new_version):
    """Update version across all files."""
    
    if not new_version:
        print("Error: Version not provided")
        print("Usage: python update_version.py <new_version>")
        sys.exit(1)
    
    # Validate version format (e.g., 1.2.3)
    if not re.match(r'^\d+\.\d+\.\d+$', new_version):
        print(f"Error: Invalid version format '{new_version}'. Expected format: X.Y.Z (e.g., 1.2.0)")
        sys.exit(1)
    
    project_root = os.path.dirname(__file__)
    
    files_to_update = [
        {
            'path': os.path.join(project_root, 'VERSION'),
            'content': f"{new_version}\n",
            'type': 'direct'
        },
        {
            'path': os.path.join(project_root, 'demo_env'),
            'pattern': r'# Addarr v[\d.]+',
            'replacement': f'# Addarr v{new_version}',
            'type': 'regex'
        },
        {
            'path': os.path.join(project_root, 'demo_env'),
            'pattern': r'APP_VERSION=[\d.]+',
            'replacement': f'APP_VERSION={new_version}',
            'type': 'regex'
        },
        {
            'path': os.path.join(project_root, 'static', 'manifest.json'),
            'pattern': r'"version": "[\d.]+"',
            'replacement': f'"version": "{new_version}"',
            'type': 'regex'
        }
    ]
    
    print(f"🔄 Updating Addarr version to {new_version}...\n")
    
    for file_config in files_to_update:
        filepath = file_config['path']
        
        if not os.path.exists(filepath):
            print(f"⚠️  File not found: {filepath}")
            continue
        
        try:
            if file_config['type'] == 'direct':
                with open(filepath, 'w') as f:
                    f.write(file_config['content'])
                print(f"✅ Updated: {os.path.relpath(filepath, project_root)}")
            
            elif file_config['type'] == 'regex':
                with open(filepath, 'r') as f:
                    content = f.read()
                
                new_content = re.sub(
                    file_config['pattern'],
                    file_config['replacement'],
                    content
                )
                
                if new_content != content:
                    with open(filepath, 'w') as f:
                        f.write(new_content)
                    print(f"✅ Updated: {os.path.relpath(filepath, project_root)}")
                else:
                    print(f"⚠️  No changes needed: {os.path.relpath(filepath, project_root)}")
        
        except Exception as e:
            print(f"❌ Error updating {os.path.relpath(filepath, project_root)}: {str(e)}")
            sys.exit(1)
    
    print(f"\n✨ Version successfully updated to {new_version}!")
    print(f"\nNext steps:")
    print(f"1. Review changes: git diff")
    print(f"2. Commit: git add . && git commit -m 'v{new_version}: [description]'")
    print(f"3. Tag: git tag -a v{new_version} -m 'Version {new_version}'")
    print(f"4. Push: git push origin prod --tags")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python update_version.py <new_version>")
        print("Example: python update_version.py 1.2.0")
        sys.exit(1)
    
    new_version = sys.argv[1]
    update_version(new_version)
