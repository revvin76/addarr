# routes.py
from flask import render_template, request, jsonify, Response, session, redirect, url_for, send_from_directory
from functools import wraps
import logging
import time
import os
from collections import deque
import requests
import re
from datetime import datetime

# Import shared utilities (will be passed from app.py)
def init_routes(app, config_manager, update_manager, auth_decorator, debug_decorator, shared_utils, network_info_func=None):
    """
    Initialize all routes with shared dependencies
    """
    
    # Store shared utilities for route functions to use
    global CONFIG, requires_auth, conditional_debug_log, utils
    CONFIG = config_manager
    requires_auth = auth_decorator
    conditional_debug_log = debug_decorator
    utils = shared_utils
    update_manager = update_manager

    # ============ ROUTE DEFINITIONS ============
    @app.route('/')
    @conditional_debug_log
    @requires_auth  
    def index():
        try:
            return render_template('index.html', config=CONFIG._config)
        except Exception as e:
            logging.error(f"Error loading index: {str(e)}")
            return render_template('index.html', error="Page load failed")

    @app.route('/trending')
    @conditional_debug_log
    @requires_auth  
    def trending_media():
        try:
            media_type = request.args.get('type', 'all')
            trending_data = utils.fetch_trending_optimized(media_type)
            
            return render_template(
                'trending.html',
                trending_data=trending_data,
                media_type=media_type,
                config=CONFIG._config
            )
        except Exception as e:
            logging.error(f"Error loading trending media: {str(e)}")
            return render_template('error.html', error="Failed to load trending media")

    @app.route('/logs')
    @conditional_debug_log
    @requires_auth  
    def get_logs():
        try:
            log_path = 'addarr.log'
            lines_to_return = min(int(request.args.get('lines', 500)), 2000)
            
            if not os.path.exists(log_path):
                return jsonify({'success': False, 'error': 'Log file not found'})
            
            def generate():
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    buffer = deque(f, maxlen=lines_to_return)
                    yield ''.join(buffer)
            
            return Response(generate(), mimetype='text/plain')
            
        except Exception as e:
            logging.error(f"Error reading logs: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/debug/memory')
    @requires_auth
    def memory_status():
        """Memory monitoring endpoint"""
        try:
            import psutil
            import gc
            
            process = psutil.Process()
            memory_info = process.memory_info()
            system_memory = psutil.virtual_memory()
            
            return jsonify({
                'process_memory': {
                    'rss_mb': memory_info.rss / 1024 / 1024,
                    'vms_mb': memory_info.vms / 1024 / 1024,
                    'percent': process.memory_percent(),
                    'open_files': len(process.open_files()),
                    'threads': process.num_threads(),
                },
                'system_memory': {
                    'total_mb': system_memory.total / 1024 / 1024,
                    'available_mb': system_memory.available / 1024 / 1024,
                    'percent': system_memory.percent
                },
                'garbage_collection': {
                    'collected': gc.get_count(),
                    'thresholds': gc.get_threshold(),
                    'enabled': gc.isenabled()
                }
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/debug/cleanup', methods=['POST'])
    @requires_auth
    def force_cleanup():
        """Force memory cleanup"""
        try:
            import gc
            collected = gc.collect()
            return jsonify({
                'success': True,
                'collected': collected,
                'message': f'Garbage collector collected {collected} objects'
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/search', methods=['POST'])
    @conditional_debug_log
    @requires_auth
    def search():
        query = request.form['query']
        logging.info(f"Searching for: {query}")
        
        try:
            movie_results = utils.search_radarr(query)
            tv_results = utils.search_sonarr(query)
            
            movie_results = movie_results if isinstance(movie_results, list) else []
            tv_results = tv_results if isinstance(tv_results, list) else []
            
            for movie in movie_results:
                movie['media_type'] = 'movie'
            for tv_show in tv_results:
                tv_show['media_type'] = 'tv'
                
            combined_results = []
            max_length = max(len(movie_results), len(tv_results))
            
            for i in range(max_length):
                if i < len(tv_results):
                    combined_results.append(tv_results[i])
                if i < len(movie_results):
                    combined_results.append(movie_results[i])
            
            logging.info(f"Found {len(movie_results)} movies and {len(tv_results)} TV shows")
                
            return render_template(
                'results.html',
                results=combined_results,
                media_type='combined',
                movies=len(movie_results),
                tv_shows=len(tv_results),
                all_results=len(combined_results),
                query=query,
                config=CONFIG._config
            )
            
        except Exception as e:
            logging.error(f"Search error: {str(e)}")
            return render_template('error.html', error=str(e))

    @app.route('/add', methods=['POST'])
    @conditional_debug_log
    @requires_auth  
    def add_to_arr():
        data = request.json
        media_type = data['media_type']
        media_id = data['media_id']
        
        if media_type == 'movie':
            success = utils.add_to_radarr(media_id)
        else:
            success = utils.add_to_sonarr(media_id)
        
        return jsonify({'success': success})

    @app.route('/manage')
    @conditional_debug_log
    @requires_auth  
    def manage_media():
        try:
            movies = utils.get_radarr_movies()
            series = utils.get_sonarr_series()
            
            combined_media = []
            
            for movie in movies:
                movie['media_type'] = 'movie'
                combined_media.append(movie)
            
            for show in series:
                show['media_type'] = 'tv'
                combined_media.append(show)
            
            combined_media.sort(key=lambda x: x.get('title', '').lower())
            
            return render_template(
                'manage.html',
                media=combined_media,
                config=CONFIG._config
            )
        except Exception as e:
            logging.error(f"Error fetching media: {str(e)}")
            return render_template('error.html', error="Failed to load media library")

    @app.route('/get_media_details')
    @conditional_debug_log
    @requires_auth
    def get_media_details():
        media_type = request.args.get('type')
        media_id = request.args.get('id')

        logging.info(f"Fetching details for {media_type} with ID: {media_id}")
        
        if media_type == 'movie':
            return jsonify(utils.get_radarr_details(media_id))
        else:
            return jsonify(utils.get_sonarr_details(media_id))

    @app.route('/get_tmdb_details')
    @conditional_debug_log
    @requires_auth  
    def get_tmdb_details():
        media_type = request.args.get('type')
        tmdb_id = request.args.get('id')

        logging.info(f"Fetching TMDB details for type: {media_type}, ID: {tmdb_id}")
        
        if not media_type or not tmdb_id:
            return jsonify({'error': 'Missing type or ID'}), 400
        
        try:
            return jsonify(utils.get_tmdb_media_details(media_type, tmdb_id))
        except Exception as e:
            return jsonify({'error': str(e)}), 500

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

    # Radarr and Sonarr routes
    @app.route('/api/radarr/rootfolders')
    @conditional_debug_log
    @requires_auth
    def get_radarr_rootfolders():
        """Get Radarr root folders"""
        try:
            url = f"{CONFIG.radarr.url}/api/v3/rootfolder"
            response = requests.get(url, params={'apikey': CONFIG.radarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Radarr root folders: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/radarr/qualityprofile')
    @conditional_debug_log
    @requires_auth
    def get_radarr_qualityprofile():
        """Get Radarr quality profiles"""
        try:
            url = f"{CONFIG.radarr.url}/api/v3/qualityprofile"
            response = requests.get(url, params={'apikey': CONFIG.radarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Radarr quality profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/sonarr/rootfolder')
    @conditional_debug_log
    @requires_auth
    def get_sonarr_rootfolder():
        """Get Sonarr root folders"""
        try:
            url = f"{CONFIG.sonarr.url}/api/v3/rootfolder"
            response = requests.get(url, params={'apikey': CONFIG.sonarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Sonarr root folders: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/sonarr/qualityprofile')
    @conditional_debug_log
    @requires_auth
    def get_sonarr_qualityprofile():
        """Get Sonarr quality profiles"""
        try:
            url = f"{CONFIG.sonarr.url}/api/v3/qualityprofile"
            response = requests.get(url, params={'apikey': CONFIG.sonarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Sonarr quality profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/sonarr/languageprofile')
    @conditional_debug_log
    @requires_auth
    def get_sonarr_languageprofile():
        """Get Sonarr language profiles"""
        try:
            url = f"{CONFIG.sonarr.url}/api/v3/languageprofile"
            response = requests.get(url, params={'apikey': CONFIG.sonarr.api_key})
            return jsonify(response.json())
        except Exception as e:
            logging.error(f"Error fetching Sonarr language profiles: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/check_library_status')
    @conditional_debug_log
    @requires_auth  
    def check_library_status():
        media_type = request.args.get('type')
        media_id = request.args.get('id')
        
        if media_type == 'movie':
            # Check Radarr
            existing = requests.get(
                f"{CONFIG.radarr.url}/api/v3/movie",
                params={'apikey': CONFIG.radarr.api_key}
            ).json()
            in_library = any(str(m.get('tmdbId')) == str(media_id) for m in existing)
        else:
            # Check Sonarr
            existing = requests.get(
                f"{CONFIG.sonarr.url}/api/v3/series",
                params={'apikey': CONFIG.sonarr.api_key}
            ).json()
            in_library = any(str(s.get('tvdbId')) == str(media_id) for s in existing)
        
        return jsonify({'in_library': in_library})

    @app.route('/api/update/dismiss', methods=['POST'])
    @conditional_debug_log
    def dismiss_update_notification():
        # """Dismiss the update notification"""
        set_env('UPDATE_NOTIFICATION', 'false')
        return jsonify({'success': True})

    # Information page
    @app.route('/api/info/network')
    @conditional_debug_log
    @requires_auth
    def get_network_info():
        """Get network information for the info panel"""
        try:
            if network_info_func:
                return jsonify(network_info_func())
            else:
                # Fallback if function not provided
                return jsonify({
                    'local_ip': get_ip_address(),
                    'port': CONFIG.app.port,
                    'duckdns_enabled': CONFIG.duckdns.enabled,
                    'duckdns_domain': CONFIG.duckdns.domain,
                    'tunnel_enabled': CONFIG.tunnel.enabled,
                    'tunnel_url': None,
                    'tunnel_active': False
                })
        except Exception as e:
            logging.error(f"Error getting network info: {str(e)}")
            return jsonify({'error': str(e)}), 500
        
    @app.route('/api/info/changelog')
    @conditional_debug_log
    @requires_auth
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
    @conditional_debug_log
    @requires_auth
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


    # Update routes
    @app.route('/api/update/check')
    @conditional_debug_log
    def check_update():
        update_info = update_manager.check_github_for_updates()
        return jsonify(update_info)

    @app.route('/api/update/download', methods=['POST'])
    @conditional_debug_log
    def download_update_route():
        result = utils.download_update()
        return jsonify(result)

    @app.route('/api/update/status')
    @conditional_debug_log
    def update_status():
        return jsonify({
            'update_notification': os.getenv('UPDATE_NOTIFICATION', 'false') == 'true',
            'latest_version': os.getenv('LATEST_VERSION', ''),
            'current_version': CONFIG.app.version
        })

    @app.route('/api/update/list')
    @conditional_debug_log
    def list_downloaded_updates():
        # """Get list of downloaded updates"""
        update_files = update_manager.get_downloaded_updates_optimized()
        return jsonify({
            'updates': update_files,
            'total_count': len(update_files)
        })

    # Authentication routes
    @app.route('/login', methods=['GET', 'POST'])
    @conditional_debug_log
    def login():
        if not CONFIG.auth.enabled:
            return redirect('/')
        
        if session.get('authenticated'):
            return redirect('/')
        
        error = None
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            if utils.check_auth(username, password):
                session['authenticated'] = True
                session['username'] = username
                return redirect(request.args.get('next') or '/')
            else:
                error = 'Invalid username or password'
        
        return render_template('login.html', error=error, config=CONFIG._config)

    @app.route('/logout')
    @conditional_debug_log
    def logout():
        session.clear()
        return redirect('/')

    # Static file routes
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static', 'images'),
                                'favicon.ico', mimetype='image/vnd.microsoft.icon')

    @app.route('/images/<path:filename>')
    @conditional_debug_log
    @requires_auth  
    def serve_image(filename):
        return send_from_directory('static/images', filename)

    @app.route('/offline.html')
    @conditional_debug_log
    def offline():
        try:
            return render_template('offline.html')
        except Exception as e:
            logging.error(f"Template error: {e}")
            return "Page not found", 404

    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html'), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        logging.error(f"Unhandled exception: {str(e)}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500

    logging.info("All routes initialized successfully")