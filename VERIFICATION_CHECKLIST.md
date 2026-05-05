# Plex Recently Downloaded Carousel - Verification Checklist

## Code Changes Verification Status
**All changes verified as in-place and correct.**

### Backend Changes (routes.py)
- ✅ **Import Fixed** (Line 16): `from urllib.parse import quote` (was using non-existent `requests.utils.quote()`)
- ✅ **Movies Endpoint Plex-First Logic** (Lines 2252-2375):
  - Plex checked FIRST (line 2257)
  - Returns immediately on Plex success without checking Radarr (line 2327)
  - Only falls back to Radarr if Plex returns 0 items (line 2329)
  
- ✅ **TV Endpoint Plex-First Logic** (Lines 2377-2516):
  - Same Plex-first pattern as Movies
  - Returns immediately on Plex success
  
- ✅ **URL Normalization Applied**:
  - `plex_base_url = CONFIG.plex.url.rstrip('/')` (Line 2263 for movies, 2400 for TV)
  - Prevents double-slash issue (`//library/recentlyAdded` → `/library/recentlyAdded`)
  
- ✅ **API Parameters Set**:
  - `'limit': 20` added to both movies and TV endpoints (prevents returning only 1 item)
  - `'type': 1` for movies, `'type': 2` for TV (correct Plex type codes)
  
- ✅ **URL Encoding Fixed**:
  - All poster URLs use: `f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(title)}"`
  - Applied to Movies (line 2312) and TV (line 2451)
  
- ✅ **Debug Logging Comprehensive**:
  - Service enabled status logged
  - Full URLs logged for debugging
  - HTTP response codes logged
  - XML parsing results logged
  - First 3 items logged with metadata
  - Clear demarcation between Plex attempt and fallback (========== PLEX FALLBACK ==========)

### Frontend Changes (templates/index.html)
- ✅ **Carousel Navigation HTML**:
  - Each carousel wrapped in `.carousel-container` div
  - Prev/next buttons with `.carousel-nav` class
  - `data-carousel` attribute maps buttons to carousel ID
  
- ✅ **JavaScript Handler**:
  - `setupCarouselNavigation()` function attaches click handlers (line 387)
  - Scrolls carousel 200px smoothly on button click
  - Called after carousel population with 100ms delay (line 424)

### Styling Changes (static/css/styles.css)
- ✅ **Container Styling** (Line 5353):
  - `.carousel-container` uses flexbox layout with gap
  - Positions prev/next buttons on either side of carousel
  
- ✅ **Button Styling** (Line 5422):
  - `.carousel-nav` buttons are 40px × 40px
  - Hover and active states defined
  - Proper alignment and spacing

---

## What This Fixes

| Problem | Root Cause | Fix Applied |
|---------|-----------|------------|
| Only 1 card showing | Missing `limit=20` parameter | Added `'limit': 20` to Plex params |
| 404 errors from Plex | Double-slash in URL (`//library/`) | `plex_base_url.rstrip('/')` normalization |
| Thumbnails not loading | Wrong `quote()` function used | Changed to `urllib.parse.quote()` |
| Can't scroll carousel | No visual nav controls | Added prev/next buttons + JavaScript |
| Radarr checked first | Logic error in fallback order | Reversed to Plex-first check |

---

## Testing Instructions

### Step 1: Verify Backend (Plex API)
Run the diagnostic script to test Plex connectivity directly:
```bash
python C:\addarr\DEV\test_plex_api.py
```

Expected output:
- ✓ Configuration loaded
- ✓ URL structure correct (no double slashes)
- ✓ HTTP 200 response from Plex
- ✓ XML parsed successfully
- ✓ Found 20+ movie/TV elements
- ✓ Poster URLs correctly formatted

### Step 2: Restart Flask App
1. Stop your Flask app (Ctrl+C)
2. Clear browser cache (Ctrl+Shift+Del)
3. Start Flask app again
4. Restart browser (Ctrl+F5 hard refresh)

### Step 3: Check Server Logs
Watch for these log patterns:
```
[recently_downloaded_movies] ========== START REQUEST ==========
[recently_downloaded_movies] Plex is ENABLED. Attempting Plex call...
[recently_downloaded_movies] Attempting Plex call to: http://127.0.0.1:32400/library/recentlyAdded
[recently_downloaded_movies] Plex response status code: 200
[recently_downloaded_movies] XML parsed successfully
[recently_downloaded_movies] Found 20 Video elements
[recently_downloaded_movies] Plex: returning 20 items (source=plex). SUCCESS - not checking Radarr.
```

### Step 4: Verify Frontend
1. Navigate to home page (`/`)
2. **Expected behavior:**
   - Movies carousel shows 20 cards (or fewer if < 20 exist)
   - TV carousel shows 20 cards (or fewer if < 20 exist)
   - Prev/next buttons visible on each carousel
   - Clicking buttons scrolls carousel smoothly
   - Thumbnails load with proper images
   - No green placeholder images
   - Source badge shows "plex" or appropriate fallback

### Step 5: Check Browser Console
Open DevTools (F12 → Console) and verify:
- No JavaScript errors
- Network tab shows `/api/recently-downloaded/*` returning 200 with items

---

## Fallback Logic (Verified)

When a carousel loads:
1. **Primary:** Try Plex first
   - If Plex enabled AND returns items → Use Plex data, STOP
   - If Plex enabled BUT returns 0 items → Continue to step 2
   - If Plex disabled → Continue to step 2

2. **Secondary (Movies):** Try Radarr
   - If Radarr enabled AND returns items → Use Radarr data
   - Otherwise → Return empty carousel

3. **Secondary (TV):** Try Sonarr
   - If Sonarr enabled AND returns items → Use Sonarr data
   - Otherwise → Return empty carousel

---

## If Issues Persist

### Issue: Still getting 404 from Plex
**Debugging steps:**
1. Run `test_plex_api.py` to isolate Flask from the issue
2. Check Plex URL in config: should be `http://hostname:32400` (no trailing slash)
3. Verify Plex token is valid in your Plex settings
4. Check Plex is running: `curl http://127.0.0.1:32400/library/sections`

### Issue: Carousels still show only 1 item
**Debugging steps:**
1. Check Flask logs for "Found X items" message
2. Run `test_plex_api.py` to see if Plex returns 20+ elements
3. If `test_plex_api.py` shows 20 items but Flask shows 1, check `populateCarousel()` function in HTML

### Issue: Thumbnails still not loading
**Debugging steps:**
1. Right-click on green placeholder → "Inspect" in browser
2. Check the `<img>` tag's `src` attribute
3. Expected format: `/api/img?url=ENCODED_URL&w=150&h=225&t=TITLE`
4. Manually visit that URL in browser to verify it loads

---

## Summary of Changes

**Files Modified:**
- `C:\addarr\DEV\routes.py` — Backend Plex integration with debug logging
- `C:\addarr\DEV\templates\index.html` — Carousel navigation UI and handler
- `C:\addarr\DEV\static\css\styles.css` — Container and button styling
- `C:\addarr\DEV\lazy_config.py` — Plex config (url, token, enabled)

**Key Improvements:**
✅ Plex is primary source (checked first, returns immediately on success)
✅ URL normalization prevents 404 errors
✅ Correct `quote()` function ensures thumbnail URLs encode properly
✅ `limit=20` parameter returns full carousel instead of 1 item
✅ Carousel navigation buttons make scrolling discoverable and usable
✅ Comprehensive debug logging helps diagnose issues quickly

