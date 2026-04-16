"""
Version information for Addarr application.
This module provides centralized version management.
"""

import os

def get_version():
    """
    Get the current version from the VERSION file at project root.
    Falls back to environment variable APP_VERSION if file not found.
    """
    try:
        version_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'VERSION')
        if os.path.exists(version_file):
            with open(version_file, 'r') as f:
                return f.read().strip()
    except Exception:
        pass
    
    # Fallback to environment variable
    return os.getenv('APP_VERSION', '1.1.15')

__version__ = get_version()
VERSION = __version__
