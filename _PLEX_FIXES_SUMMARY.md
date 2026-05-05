# Plex Recently Downloaded Carousel Fixes

## Problems Fixed

### 1. **Only 1 card showing per category (instead of 20)**
- **Root Cause:** Plex API calls were missing the `limit=20` parameter
- **Impact:** Only 1 item was returned from Plex
- **Fix Applied:** Added `'limit': 20` to Plex API params in:
  - `/api/recently-downloaded/movies` (line 2287)
  - `/api/recently-downloaded/tv` (line 2351)

### 2. **Thumbnail images not loading (green placeholder showing)**
- **Root Cause:** `requests.utils.quote()` function doesn't exist and was breaking URL encoding
- **Impact:** Image proxy received malformed URLs and couldn't cache images
- **Fix Applied:** Replaced `requests.utils.quote()` with `urllib.parse.quote()` (Python standard library)
  - Added import: `from urllib.parse import quote` (line 16)
  - Updated 6 locations across all three endpoints:
    - Movies: Radarr (line 2269), Plex (line 2302)
    - TV: Sonarr (line 2332), Plex (line 2365)
    - Books: Readarr (line 2402)

## How It Works Now

### Plex API Integration
- **Movies endpoint** (`/api/recently-downloaded/movies`):
  - Calls `GET {plex.url}/library/recentlyAdded?type=1&limit=20`
  - Parses XML response for `<Video>` elements
  - Extracts poster from `thumb` attribute
  - Returns up to 20 items with properly encoded poster URLs

- **TV endpoint** (`/api/recently-downloaded/tv`):
  - Calls `GET {plex.url}/library/recentlyAdded?type=2&limit=20`
  - Parses XML response for `<Directory>` elements (TV series)
  - Extracts poster from `thumb` attribute
  - Returns up to 20 items with properly encoded poster URLs

### Fallback Logic
- **Movies:** Radarr → Plex (if Radarr not available)
- **TV Shows:** Sonarr → Plex (if Sonarr not available)
- **Books:** Readarr only (Plex doesn't support book library)

## Testing

To verify the fixes work:

1. **Clear browser cache** to ensure carousel JS reloads
2. **Refresh the home page** at `/`
3. **Check browser console** (F12) for any errors
4. **Verify carousels** show 20 items (or fewer if less are available)
5. **Verify thumbnails load** properly without green placeholder

## Technical Details

### URL Encoding Fix
Changed from (broken):
```python
poster': f"/api/img?url={requests.utils.quote(url)}&w=150&h=225&t={requests.utils.quote(title)}"
```

To (correct):
```python
poster': f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(video.get('title', ''))}"
```

The `quote()` function properly encodes special characters in URLs, allowing the `/api/img` endpoint to parse them correctly and cache the images.

### Plex XML Response Structure
Plex returns recently added items as XML with poster URLs in the `thumb` attribute:
```xml
<Video ratingKey="..." thumb="/library/metadata/.../thumb/..." title="Movie Title" year="2024" />
```

The code constructs full URLs by prepending the Plex base URL:
```python
poster_url = f"{CONFIG.plex.url}{thumb}"  # e.g., http://plex:32400/library/metadata/.../thumb/...
```

Then passes to the image proxy for resizing and caching:
```python
/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(title)}
```

## Files Modified

- **C:\addarr\DEV\routes.py**
  - Line 16: Added import for `quote` function
  - Lines 2269, 2302: Movies endpoint URL encoding fixes
  - Lines 2287: Added limit parameter to Plex movies API
  - Lines 2332, 2365: TV endpoint URL encoding fixes
  - Lines 2351: Added limit parameter to Plex TV API
  - Line 2402: Books endpoint URL encoding fix
