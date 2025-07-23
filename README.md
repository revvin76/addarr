# Addarr 🎬

A lightweight Flask web interface to search and add movies/TV shows to Radarr/Sonarr.  
Perfect for self-hosted media servers!  

![Demo Screenshot 1](/static/images/Screenshot1.png) ![Demo Screenshot 2](/static/images/Screenshot2.png) ![Demo Screenshot 3](/static/images/Screenshot3.png)
![Demo Screenshot 4](/static/images/Screenshot4.png) ![Demo Screenshot 5](/static/images/Screenshot5.png) 

---

## Features ✨
- 🔍 **Search** movies (Radarr) and TV shows (Sonarr)  
- ➕ **One-click add** to your library  
- 🎥 **Trailer previews** (YouTube integration)  
- 📊 **Detailed info** (ratings, genres, status)  
- 🔄 **Auto-update** from GitHub  

---

## Prerequisites 📋
- Python 3.8+  
- Radarr/Sonarr instances (with API keys)  
- TMDB API key (for trailers/metadata) *(optional)*  

---

## Installation 🛠️

### 1. Clone the repo
```bash
git clone https://github.com/revvin76/addarr.git
cd addarr
```

### 2. Populate your .env file with your API tokens from themovi
```bash
RADARR_URL=http://localhost:7878
RADARR_API_KEY=****
SONARR_URL=http://localhost:8989
SONARR_API_KEY=****
TMDB_TOKEN=****
TMDB_KEY=****
RADARR_ROOT_FOLDER=E:\\Movies
SONARR_ROOT_FOLDER=E:\\TV
ENABLE_AUTO_UPDATE=true
```

### 3. Install the requirements
```bash
pip install -r requirements.txt
```

### 4. Launch!
```bash
python app.py
```
