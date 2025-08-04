# Addarr 🎬

A lightweight Flask web interface to search and add movies/TV shows to Radarr/Sonarr with automatic updates and dynamic DNS support.

![Demo Screenshot 1](/static/images/Screenshot1.png) ![Demo Screenshot 2](/static/images/Screenshot2.png) ![Demo Screenshot 3](/static/images/Screenshot3.png)
![Demo Screenshot 4](/static/images/Screenshot4.png) ![Demo Screenshot 5](/static/images/Screenshot5.png) 

---

## Features ✨
- 🔍 **Search** movies (Radarr) and TV shows (Sonarr)  
- ➕ **One-click add** to your library  
- 🎥 **Trailer previews** (YouTube integration via TMDB)  
- 📊 **Detailed info** (ratings, genres, status)  
- 🔄 **Auto-update** from GitHub  
- 🌐 **DuckDNS integration** for dynamic DNS updates  
- ⚙️ **Web-based configuration** for all settings  
- 📜 **Log viewer** built into the interface  
- 🐛 **Debug panel** for API testing  

---

## Prerequisites 📋
- Python 3.8+  
- Radarr/Sonarr instances (with API keys)  
- TMDB API key (for trailers/metadata) *(optional)*  
- DuckDNS account *(optional, for dynamic DNS)*  

---

## Installation 🛠️

### 1. Clone the repo
```bash
git clone https://github.com/revvin76/addarr.git
cd addarr
```

### 2. Create and configure your .env file
Create a .env file in the root folder. There is a demo_env file you can use as a template.
```bash
# .env file for Addarr application
# This file contains environment variables for configuring the application and its dependencies.

# Radarr and Sonarr settings
# Replace '****' with your actual API keys
# Ensure the URLs are correct and accessible from your application  
# Radarr settings
# Radarr is used for managing movie libraries  
RADARR_URL=http://localhost:7878
RADARR_API_KEY=****
RADARR_QUALITY_PROFILE=4
RADARR_ROOT_FOLDER=E:\Movies

# Sonarr settings
# Sonarr is used for managing TV series libraries   
SONARR_URL=http://localhost:8989
SONARR_API_KEY=****
SONARR_QUALITY_PROFILE=4
SONARR_LANGUAGE_PROFILE=1
SONARR_ROOT_FOLDER=E:\\TV

# TMDB settings
# TMDB is used for fetching movie and TV series metadata
TMDB_TOKEN=****
TMDB_KEY=****

# Application settings
# These settings control the behavior of the Addarr application
ENABLE_AUTO_UPDATE=false
FLASK_DEBUG=true

# DuckDNS Settings
DUCKDNS_DOMAIN=yourdomain.duckdns.org
DUCKDNS_TOKEN=your_duckdns_token
DUCKDNS_ENABLED=true
```

### 3. Install the requirements
```bash
pip install -r requirements.txt
```

### 4. Launch!
```bash
python app.py
```

The application will be available at http://localhost:5000


## Configuration Options ⚙️
All settings can be configured through the web interface after initial setup:

**Radarr/Sonarr Settings:**
- API endpoints
- Quality profiles
- Root folders
**Application Settings:**
- Auto-update toggle
- Debug mode
- DuckDNS configuration
**Version Control:**
- View current version
- Check for updates
- View release notes

## Usage 🖥️
### Search for media:
- Enter a movie or TV show title
- Select media type (Movie/TV)
- Click Search

### Add to library:
- View details of any result
- Click "Add to Radarr/Sonarr"

### Configure settings:
- Click the gear icon (⚙️) in the top right
- Modify any settings as needed
- Click "Save Configuration"

### View logs:
- Click the list icon (📋) in the top right
- View real-time application logs

## Advanced Features 🔧
### DuckDNS Integration
- Automatically updates your DuckDNS domain with your current IP
- Configure in the DuckDNS settings section
- Requires domain and token from DuckDNS

### Debug Panel
- Test API endpoints directly
- View request/response details
- Useful for troubleshooting

### Auto-Updates
- Checks GitHub for updates hourly
- Can be toggled on/off in settings
- Shows update notifications with release notes

## Troubleshooting 🛠️
### Issue: Can't connect to Radarr/Sonarr
- ✅ Verify URLs and API keys are correct
- ✅ Check that the services are running and accessible

### Issue: Auto-updates not working
- ✅ Ensure ENABLE_AUTO_UPDATE=true in .env
- ✅ Check internet connectivity

### Issue: DuckDNS not updating
- ✅ Verify domain and token are correct
- ✅ Check that DuckDNS is enabled in settings