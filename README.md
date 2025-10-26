# Addarr 🎬  
A lightweight Flask web interface to search and add movies/TV shows to Radarr/Sonarr — now with automatic updates, secure tunnels, and dynamic DNS support.

![Main screen](/static/images/Screenshot1.png) ![Unified media search](/static/images/Screenshot2.png) ![Movie result](/static/images/Screenshot3.png)
![TV Show result](/static/images/Screenshot4.png) ![Media Manager](/static/images/Screenshot5.png) ![Manage Movie](/static/images/Screenshot4.png) ![Manage TV Show](/static/images/Screenshot5.png) 

---

## 🚀 Version 1.0.5 Highlights

### 🧩 New Features
- **Automated GitHub Update System**
  - Checks for new releases and downloads updates automatically.
  - Option to manually trigger updates via API or UI.
  - Can auto-apply updates and restart the application seamlessly.
- **Localhost.run Tunnel Integration**
  - One-click public URL generation for remote access.
  - Automatic hostname generation and persistence.
  - SSH key support and live health monitoring.
- **Enhanced Logging & Debugging**
  - Full request/response logging.
  - `/logs` endpoint for viewing live logs.
  - Rotating log file handling to prevent size bloat.
- **DuckDNS IP Updater**
  - Automatically updates DuckDNS domain if IP changes.
  - Logs updates and previous IPs.
- **Improved Configuration Handling**
  - `.env` values are editable and auto-updated when environment changes.
  - Added safe environment writer with validation.
- **Update Management APIs**
  - `/api/update/check` — check GitHub for new releases.
  - `/api/update/download` — download latest release.
  - `/api/update/apply/<version>` — apply an update.
  - `/api/update/apply-latest` — one-click update to newest version.
  - `/api/update/cleanup` — delete old versions, keeping only the most recent.
  - `/api/update/list` — list all downloaded updates.
- **Tunnel Management APIs**
  - `/api/tunnel/start`, `/api/tunnel/stop`, `/api/tunnel/restart`
  - `/api/tunnel/status` — live tunnel information.
  - `/api/tunnel/regenerate-hostname` — generate new tunnel hostname instantly.
  - `/api/tunnel/set-ssh-key` — assign SSH key and restart tunnel.

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

### 2. Create and configure environment
```bash
cp demo_env .env
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run Addarr
```bash
python app.py
```

Visit:  
👉 [http://localhost:5000](http://localhost:5000)

---

## 🧠 API Reference (v1.0.5)

| Endpoint | Method | Description |
|-----------|---------|-------------|
| `/api/update/check` | GET | Check for new releases on GitHub |
| `/api/update/download` | POST | Download the latest available update |
| `/api/update/apply/<version>` | POST | Apply downloaded update |
| `/api/update/apply-latest` | POST | Automatically apply the newest update |
| `/api/update/cleanup` | POST | Clean old updates (keep 3 latest) |
| `/api/tunnel/start` | POST | Start localhost.run tunnel |
| `/api/tunnel/stop` | POST | Stop the tunnel |
| `/api/tunnel/status` | GET | Get tunnel status |
| `/api/tunnel/regenerate-hostname` | POST | Generate new tunnel hostname |
| `/api/tunnel/set-ssh-key` | POST | Assign SSH key for secure tunnel |
| `/api/debug/update-status` | GET | Debug info on update state |
| `/api/debug/tunnel` | GET | Debug tunnel connectivity |

---

## 🧩 Features Summary
- 🔍 Search movies (Radarr) and TV shows (Sonarr)
- ➕ One-click add to library
- 🎬 TMDB trailer and metadata integration
- 📦 Auto-updater with version control
- 🌍 Localhost.run tunnel for secure public access
- 🦆 DuckDNS dynamic IP updater
- 🧾 Log viewer (`/logs`)
- 🧠 Debug panel for update/tunnel testing
- ⚙️ Configuration persistence through `.env`

---

## 🧰 Troubleshooting

**❌ Auto-update not working**  
- Ensure `.env` includes `GITHUB_REPO` and `ENABLE_AUTO_UPDATE=true`

**❌ Tunnel fails to connect**  
- Check that `ssh` is installed and in PATH  
- Try clearing `TUNNEL_HOSTNAME` and restarting the app

**❌ DuckDNS not updating**  
- Verify `DUCKDNS_ENABLED=true`  
- Check your DuckDNS token and domain name

---

## 🧾 License
MIT License © 2025 Revvin76
