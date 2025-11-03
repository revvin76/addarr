# Addarr 🎬  
A comprehensive Flask-based media management web interface that seamlessly bridges the gap between your media discovery experience and your Radarr/Sonarr automation systems. Addarr transforms how you interact with your media library by providing a unified, intuitive interface for searching, adding, and managing movies and TV shows across all your devices.

![Main screen](/static/images/Screenshot1.png) ![Unified media search](/static/images/Screenshot2.png) ![Movie result](/static/images/Screenshot3.png)
![TV Show result](/static/images/Screenshot4.png) ![Media Manager](/static/images/Screenshot5.png) ![Manage Movie](/static/images/Screenshot4.png) ![Manage TV Show](/static/images/Screenshot5.png) 
![Server welcome screen](/static/images/welcome.png)

---

## 🎯 What is Addarr?
Addarr is a self-hosted web application designed to simplify and enhance your media library management experience. It acts as a sophisticated front-end for your existing Radarr and Sonarr instances, providing a unified interface that combines the power of both systems into a single, cohesive experience.

### The Problem Addarr Solves
Managing a media library typically involves juggling multiple applications:

-Radarr for movies
-Sonarr for TV shows
-Manual searches across different platforms
-Separate interfaces for discovery vs management

Addarr consolidates this entire workflow into one beautiful, responsive web interface that works perfectly on desktop, tablet, and mobile devices.

## ✨ Core Features
### 🔍 Intelligent Media Discovery

- Unified Search Engine: Simultaneously search both Radarr (movies) and Sonarr (TV shows) with a single query
- Smart Result Blending: Intelligently combines and alternates movie and TV show results for optimal browsing
- TMDB Integration: Enhanced metadata, high-quality artwork, official trailers, and detailed information from The Movie Database
- Real-time Availability: Instant visibility into whether media is already in your library or available to add

###🚀 One-Click Media Management

- Streamlined Addition: Add movies and TV shows to your library with a single click
- Automated Configuration: Automatically applies your preferred quality profiles, root folders, and monitoring settings
- Bulk Operations: Manage multiple items simultaneously through the comprehensive media manager
- Library Overview: Complete visibility into your existing media with detailed status information

### 🌐 Advanced Access & Connectivity

- Progressive Web App (PWA): Install as a native-like application on any device with offline capability
- Secure Tunnel Integration: Built-in Pinggy Pro tunnel support for secure remote access without complex networking
- Dynamic DNS: DuckDNS integration for persistent domain names pointing to your dynamic home IP
- Multi-access Support: Simultaneous access via local network, public tunnels, and custom domains

### ⚙️ Enterprise-Grade Management

- Self-Updating System: Automatic GitHub update checks with safe download and installation procedures
- Web-Based Configuration: Complete configuration management through an intuitive web interface
- Real-time Monitoring: Connection testing, service health checks, and comprehensive logging
- Version Control: Track update history and manage multiple downloaded versions

## 🎮 User Experience
### For Casual Users

- Simple Search: Type what you want to watch and get instant results from both movies and TV shows
- Visual Library: Browse your existing collection with beautiful posters and clear status indicators
- One-Click Actions: Add new content or manage existing items with intuitive controls
- Mobile-Friendly: Perfect experience on smartphones and tablets

---

## ⚙️ Configuration

Create a `.env` file in the root directory or copy from the provided `demo_env` template.

```bash
cp demo_env .env
```

Then modify your `.env` to include:
- Radarr/Sonarr API details
- TMDB API keys (optional)
- DuckDNS domain and token (optional)
- GitHub repo name for updates (e.g., `revvin76/addarr`)
- Optional SSH key path for tunnel authentication

---

## 🛠 Installation

### 1. Clone the repository
```bash
git clone https://github.com/revvin76/addarr.git
cd addarr
```

## 🏁 Getting Started
Addarr is designed for quick setup and immediate value:

```bash
# 1. Clone and setup
git clone https://github.com/revvin76/addarr.git
cd addarr
cp demo_env .env

# 2. Edit configuration
nano .env  # Add your Radarr/Sonarr details

# 3. Install and run
pip install -r requirements.txt
python app.py
```
Within minutes, you'll have a powerful, unified media management interface running and accessible from any device on your network.

---

## 💬 Join the Community

- GitHub Repository: github.com/revvin76/addarr
- Issue Tracking: Report bugs and request features
- Contributions: Welcome from developers of all skill levels
- Documentation: Comprehensive setup and usage guides

## 📄 License
MIT License © 2025 Revvin76

---

Transform your media management experience today with Addarr - the unified interface for your automated media library ecosystem! 🎉