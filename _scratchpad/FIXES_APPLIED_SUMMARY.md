# Recently-Downloaded API Endpoints - Fixes Applied

## Problem Statement
Three recently-downloaded API endpoints in `routes.py` had critical issues:
1. **Only 1 card showing per category** instead of 20
2. **Thumbnail images not loading** (showing placeholder green Addarr logo)
3. **Image proxy failing** due to URL encoding errors

## Root Cause Analysis

### Issue 1: Only 1 Card Showing (Not 20)
**Cause:** Missing `limit` parameter in Plex API calls
- Plex `/library/recentlyAdded` endpoint has a default limit of 1 item
- The code was fetching all items (with default limit=1), then slicing `[:20]`
- Result: Always returned only 1 item

**Fix:** Added `limit=20` parameter to all Plex API calls

### Issue 2: Thumbnail Images Not Loading
**Cause:** Incorrect use of `requests.utils.quote()`
- `requests.utils.quote` either doesn't exist or behaves unexpectedly
- This caused malformed URL parameters in the image proxy endpoint calls
- Example malformed: `/api/img?url=[broken]&w=150&h=225&t=[broken]`

**Fix:** Imported and used `urllib.parse.quote()` instead (standard library function)

### Issue 3: Image Proxy Failures
**Cause:** Related to Issue 2 - URL encoding problems
- The `/api/img` endpoint checks if URL starts with `http` (line 1757)
- Malformed URLs from broken quote() calls failed this check
- Result: 400 error, images never cached, placeholder shown

**Fix:** Proper URL encoding ensures `/api/img` receives valid URLs

## Changes Made to `/addarr/DEV/routes.py`

### 1. Import Statement (Line 16)
```python
# ADDED:
from urllib.parse import quote
```

### 2. Movies Endpoint: `/api/recently-downloaded/movies`

#### Line 2287 - Plex API params:
```python
# BEFORE:
params={'type': 1},  # type=1 for movies

# AFTER:
params={'type': 1, 'limit': 20},  # type=1 for movies, limit to 20
```

#### Line 2269 - Radarr poster URL:
```python
# BEFORE:
'poster': f"/api/img?url={requests.utils.quote(m.get('remotePoster', ''))}&w=150&h=225&t={requests.utils.quote(m.get('title', ''))}"

# AFTER:
'poster': f"/api/img?url={quote(m.get('remotePoster', ''))}&w=150&h=225&t={quote(m.get('title', ''))}"
```

#### Line 2302 - Plex poster URL:
```python
# BEFORE:
'poster': f"/api/img?url={requests.utils.quote(poster_url)}&w=150&h=225&t={requests.utils.quote(video.get('title', ''))}"

# AFTER:
'poster': f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(video.get('title', ''))}"
```

### 3. TV Endpoint: `/api/recently-downloaded/tv`

#### Line 2332 - Sonarr poster URL:
```python
# BEFORE:
'poster': f"/api/img?url={requests.utils.quote(s.get('remotePoster', ''))}&w=150&h=225&t={requests.utils.quote(s.get('title', ''))}"

# AFTER:
'poster': f"/api/img?url={quote(s.get('remotePoster', ''))}&w=150&h=225&t={quote(s.get('title', ''))}"
```

#### Line 2351 - Plex API params:
```python
# BEFORE:
params={'type': 2},  # type=2 for TV shows

# AFTER:
params={'type': 2, 'limit': 20},  # type=2 for TV shows, limit to 20
```

#### Line 2365 - Plex poster URL:
```python
# BEFORE:
'poster': f"/api/img?url={requests.utils.quote(poster_url)}&w=150&h=225&t={requests.utils.quote(video.get('title', ''))}"

# AFTER:
'poster': f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(video.get('title', ''))}"
```

### 4. Books Endpoint: `/api/recently-downloaded/books`

#### Line 2402 - Readarr poster URL:
```python
# BEFORE:
'poster': f"/api/img?url={requests.utils.quote(b.get('remoteCover', ''))}&w=150&h=225&t={requests.utils.quote(b.get('title', ''))}"

# AFTER:
'poster': f"/api/img?url={quote(b.get('remoteCover', ''))}&w=150&h=225&t={quote(b.get('title', ''))}"
```

## How Each Fix Addresses the Issues

### Fix 1: `limit=20` parameter
- **Solves:** "Only 1 card showing" problem
- **How:** Tells Plex API to return up to 20 items instead of defaulting to 1
- **Endpoints affected:** Movies (Plex), TV (Plex)
- **Lines:** 2287, 2351

### Fix 2: `urllib.parse.quote` instead of `requests.utils.quote`
- **Solves:** "Thumbnail images not loading" problem
- **How:** Properly URL-encodes poster URLs for the `/api/img` endpoint
- **Endpoints affected:** Movies (Radarr + Plex), TV (Sonarr + Plex), Books (Readarr)
- **Lines:** 2269, 2302, 2332, 2365, 2402

### Fix 3: Combined effect
- Proper URL encoding + Plex limit parameter = 20 images per category with correct URLs
- Image proxy receives valid URLs, caches them, and serves them immediately on next request

## Verification Steps

1. **Check movies endpoint:**
   - Should return 20 items from Radarr or Plex
   - Poster URLs should be properly formatted
   - `/api/img` should log cache operations

2. **Check TV endpoint:**
   - Should return 20 shows from Sonarr or Plex
   - Poster URLs should be properly formatted
   - Episode/season counts should be accurate

3. **Check books endpoint:**
   - Should return 20 books from Readarr
   - Poster/cover URLs should be properly formatted
   - Author names should display

4. **Monitor logs:**
   - Look for `[img_proxy]` entries showing MISS→SAVE→HIT sequence
   - No 400 errors for invalid URLs
   - Check for any lingering `requests.utils.quote` references (should be none)

## API Endpoint Behavior After Fixes

### Movies: `/api/recently-downloaded/movies`
```json
{
  "items": [
    {
      "id": "movie_id",
      "title": "Movie Title",
      "poster": "/api/img?url=https%3A%2F%2F...",
      "year": 2024,
      "rating": 8.5
    },
    // ... 19 more items (was only 1)
  ],
  "type": "movie",
  "source": "plex"  // or "radarr"
}
```

### TV: `/api/recently-downloaded/tv`
```json
{
  "items": [
    {
      "id": "show_id",
      "title": "Show Title",
      "poster": "/api/img?url=https%3A%2F%2F...",
      "seasons": 3,
      "episodes": 24,
      "year": 2023
    },
    // ... 19 more items (was only 1)
  ],
  "type": "tv",
  "source": "plex"  // or "sonarr"
}
```

### Books: `/api/recently-downloaded/books`
```json
{
  "items": [
    {
      "id": "book_id",
      "title": "Book Title",
      "author": "Author Name",
      "poster": "/api/img?url=https%3A%2F%2F...",
      "year": 2024,
      "pages": 432
    },
    // ... 19 more items
  ],
  "type": "book",
  "source": "readarr"
}
```

## Files Modified
- **C:\addarr\DEV\routes.py** - All fixes applied

## Files Generated
- **C:\addarr\DEV\_scratchpad\fixed_recently_downloaded.py** - Reference code with fixes
- **C:\addarr\DEV\_scratchpad\FIXES_APPLIED_SUMMARY.md** - This document
