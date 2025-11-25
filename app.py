# app.py (Simplified)
import os
from flask import Flask
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import atexit
import sys
import gc
import psutil
import requests
from packaging import version
from dotenv import load_dotenv

# Import our modules
from lazy_config import LazyConfig
from memory_manager import MemoryManager
from update_manager import UpdateManager
from utils import SharedUtils
import routes

# Global variables for tunnel functionality - define them at module level
tunnel_process = None
tunnel_url = None

# Setup basic logging
def setup_basic_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    handler = RotatingFileHandler(
        'addarr.log', 
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

setup_basic_logging()

# Initialize core components
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_DEBUG') if os.getenv('FLASK_DEBUG') else os.urandom(24)

CONFIG = LazyConfig()
memory_manager = MemoryManager(CONFIG)
update_manager = UpdateManager(CONFIG)
utils = SharedUtils(CONFIG)

# ============ TUNNEL AND NETWORK FUNCTIONS ============

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

def start_pinggy_tunnel():
    """Start Pinggy tunnel with Pro support"""
    global tunnel_process, tunnel_url
    
    # Check if pinggy is available
    try:
        import pinggy
        PINGGY_AVAILABLE = True
    except ImportError:
        PINGGY_AVAILABLE = False
        print("❌ Pinggy module not available. Cannot start tunnel.")
        logging.error("Pinggy module not available. Cannot start tunnel.")
        return
    
    def tunnel_worker():
        global tunnel_process, tunnel_url
        try:
            print("🚀 Starting Pinggy Pro tunnel...")
            logging.info("Starting Pinggy Pro tunnel...")
            
            # For Pinggy Pro: Use token and reserved subdomain
            pinggy_token = CONFIG.tunnel.auth_token
            reserved_subdomain = CONFIG.tunnel.reserved_subdomain
            
            # Build the connection arguments
            connection_args = {
                'forwardto': f"localhost:{CONFIG.app.port}",
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
            
            print(f"🎯 Starting tunnel on port {CONFIG.app.port}...")
            print("🔄 Establishing tunnel connection...")
            
            # Start the tunnel with the correct parameters
            tunnel_process = pinggy.start_tunnel(**connection_args)
            
            # Wait for tunnel with timeout
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
            tunnel_url = None
    
    # Start tunnel in separate thread
    print("🧵 Starting tunnel thread...")
    tunnel_thread = threading.Thread(target=tunnel_worker, daemon=True, name="PinggyTunnel")
    tunnel_thread.start()

def cleanup_tunnel():
    """Clean up tunnel on shutdown"""
    global tunnel_process, tunnel_url
    if tunnel_process:
        try:
            print("🔄 Stopping tunnel...")
            logging.info("Stopping tunnel...")
            # Try to close the tunnel gracefully
            if hasattr(tunnel_process, 'close'):
                try:
                    tunnel_process.close()
                except Exception as e:
                    print(f"Warning: Error closing tunnel gracefully: {e}")
            tunnel_process = None
            tunnel_url = None
        except Exception as e:
            print(f"Warning: Error during tunnel cleanup: {e}")
            logging.warning(f"Error during tunnel cleanup: {str(e)}")

def get_network_info():
    """Get comprehensive network information"""
    global tunnel_url
    return {
        'local_ip': get_ip_address(),
        'port': CONFIG.app.port,
        'duckdns_enabled': CONFIG.duckdns.enabled,
        'duckdns_domain': CONFIG.duckdns.domain,
        'tunnel_enabled': CONFIG.tunnel.enabled,
        'tunnel_url': tunnel_url,
        'tunnel_active': tunnel_url is not None
    }

# ============ WELCOME FUNCTION ============
def print_welcome():
    """Print welcome message and logo only once"""
    from colorama import Fore, Style
    global tunnel_url  # Add this line to access the global variable

    app_info = f"""
    {Fore.GREEN}🚀 ADDARR MEDIA MANAGER{Style.RESET_ALL}
    {Fore.WHITE}• Version: {CONFIG.app.version}
    {Fore.WHITE}• Local: {Fore.CYAN}http://127.0.0.1:{CONFIG.app.port}{Style.RESET_ALL}
    {Fore.WHITE}• Network: {Fore.CYAN}http://{get_ip_address()}:{CONFIG.app.port}{Style.RESET_ALL}
    """
    
    # Check if tunnel URL is available (it might be set by the tunnel thread)
    if tunnel_url:
        app_info += f"{Fore.WHITE}• Tunnel: {Fore.CYAN}{tunnel_url}{Style.RESET_ALL}\n"
    elif CONFIG.tunnel.enabled:
        app_info += f"{Fore.WHITE}• Tunnel: {Fore.YELLOW}Starting...{Style.RESET_ALL}\n"
    
    if CONFIG.duckdns.enabled and CONFIG.duckdns.domain:
        app_info += f"""\t{Fore.WHITE}• DuckDNS: {Fore.CYAN}http://{CONFIG.duckdns.domain}.duckdns.org:{CONFIG.app.port}{Style.RESET_ALL}\n"""
    
    try:
        from ascii_magic import AsciiArt
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

# ============ AUTO UPDATE AND RESTART FUNCTION ============
def perform_immediate_update_check():
    """Perform immediate update check and apply if available"""
    try:
        print("🔍 Checking for updates...")
        
        # Force config reload to get latest version
        CONFIG._reload_config()
        
        # Check for updates synchronously
        update_info = update_manager._check_github_for_updates()
        
        if update_info.get('update_available'):
            latest_version = update_info['latest_version']
            current_version = CONFIG.app.version
            
            print(f"🎯 Update available: {current_version} → {latest_version}")
            print("📥 Downloading and applying update...")
            
            # Check if already downloaded
            existing_updates = update_manager.get_downloaded_updates_optimized()
            already_downloaded = any(update['version'] == latest_version for update in existing_updates)
            
            if not already_downloaded:
                # Download the update
                download_result = update_manager._download_update(latest_version)
                if not download_result.get('success'):
                    print(f"❌ Download failed: {download_result.get('error')}")
                    return False
            
            # Apply the update
            apply_result = update_manager._apply_update(latest_version)
            if apply_result.get('success'):
                print(f"✅ Successfully updated to version {latest_version}")
                
                # Update environment with new version
                update_manager.set_env('APP_VERSION', latest_version)
                update_manager.set_env('UPDATE_APPLIED', 'true')
                update_manager.set_env('UPDATE_APPLIED_VERSION', latest_version)
                update_manager.set_env('LAST_CHECKED', str(int(time.time())))
                
                return True
            else:
                print(f"❌ Update application failed: {apply_result.get('error')}")
                return False
        else:
            print("✅ No updates available")
            # Update last checked time even when no update is available
            update_manager.set_env('LAST_CHECKED', str(int(time.time())))
            return False
            
    except Exception as e:
        print(f"❌ Update check failed: {str(e)}")
        logging.error(f"Immediate update check failed: {str(e)}")
        return False

def restart_application():
    """Restart the application after update"""
    try:
        print("🔄 Restarting application...")
        
        # Stop managers gracefully
        try:
            update_manager.stop()
        except:
            pass
            
        try:
            memory_manager.stop()
        except:
            pass
            
        try:
            cleanup_tunnel()
        except:
            pass
        
        # Use subprocess to restart
        python = sys.executable
        os.execv(python, [python] + sys.argv)
        
    except Exception as e:
        print(f"❌ Failed to restart: {str(e)}")
        # If restart fails, just exit and let the system restart it
        sys.exit(0)

# ============ AUTH DECORATORS ============

def requires_auth(f):
    from functools import wraps
    from flask import session, redirect, url_for, request, Response
    
    @wraps(f)
    def decorated(*args, **kwargs):
        if not CONFIG.auth.enabled:
            return f(*args, **kwargs)
            
        if session.get('authenticated'):
            return f(*args, **kwargs)
            
        auth = request.authorization
        if auth and utils.check_auth(auth.username, auth.password):
            session['authenticated'] = True
            session['username'] = auth.username
            return f(*args, **kwargs)
            
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return Response(
                'Could not verify your access level for that URL.\n'
                'You have to login with proper credentials', 401,
                {'WWW-Authenticate': 'Basic realm="Login Required"'})
        else:
            return redirect(url_for('login', next=request.url))
    return decorated

def conditional_debug_log(func):
    from functools import wraps
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not CONFIG.app.debug:
            return func(*args, **kwargs)
        
        import time
        start_time = time.time()
        logger = logging.getLogger(func.__module__)
        
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            
            if duration > 1.0 or CONFIG.app.debug:
                logger.debug(f"{func.__name__} took {duration:.3f}s")
            
            return result
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=CONFIG.app.debug)
            raise
    return wrapper

# Initialize routes
routes.init_routes(
    app=app,
    config_manager=CONFIG,
    auth_decorator=requires_auth,
    debug_decorator=conditional_debug_log,
    shared_utils=utils,
    network_info_func=get_network_info,
    update_manager=update_manager
)

# ============ STARTUP AND SHUTDOWN ============

def startup_sequence():
    global tunnel_url  # Add this line to access the global variable
    
    import gc
    gc.collect()
    
    # Only run in the main process, not the reloader process
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return
        
    # Check for updates FIRST before anything else
    if CONFIG.update.enabled:
        print("🔧 Checking for updates...")
        update_applied = perform_immediate_update_check()
        if update_applied:
            # If update was applied, we need to restart
            print("🔄 Update applied. Restarting application...")
            restart_application()
            return  # Don't continue if we're restarting

    # Only continue if no update was applied
    # Start tunnel if enabled
    if CONFIG.tunnel.enabled:
        print("🔧 Starting tunnel...")
        start_pinggy_tunnel()
        
        # Wait for tunnel to establish
        print("⏳ Waiting for tunnel to establish...", end="", flush=True)
        for i in range(15):  # Wait up to 15 seconds
            if tunnel_url is not None:
                break
            time.sleep(1)
            print(".", end="", flush=True)
        print()  # New line after progress dots

    
    # Start update manager if enabled (background checks)
    if CONFIG.update.enabled:
        update_manager.start()
    
    # Start memory manager
    memory_manager.start()
    
    # Print welcome message
    print_welcome()

    # # Print welcome message in main process only
    # if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    #     print_welcome()

def shutdown_sequence():
    global tunnel_process  # Add this line to access the global variable
    
    logging.info("Shutting down application...")
    
    # Stop managers with error handling
    try:
        if hasattr(update_manager, 'stop'):
            update_manager.stop()
    except Exception as e:
        logging.warning(f"Error stopping update manager: {e}")
    
    try:
        if hasattr(memory_manager, 'stop'):
            memory_manager.stop()
    except Exception as e:
        logging.warning(f"Error stopping memory manager: {e}")
    
    try:
        cleanup_tunnel()
    except Exception as e:
        logging.warning(f"Error during tunnel cleanup: {e}")
    
    logging.info("Shutdown complete")

atexit.register(shutdown_sequence)

if __name__ == '__main__':
    startup_sequence()
    
    try:
        app.run(
            host='0.0.0.0', 
            debug=CONFIG.app.debug, 
            port=CONFIG.app.port, 
            use_reloader=CONFIG.app.debug,
            threaded=True,
            processes=1
        )
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        shutdown_sequence()
        sys.exit(0)