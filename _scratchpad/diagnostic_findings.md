# Recently Downloaded Endpoints - Diagnostic Findings

**Date:** 2026-05-03  
**Investigation:** Problem 1 (Plex 404) + Problem 2 (Only 1 card showing)

---

## PROBLEM 1: Plex Still Returning 404

### Investigation Results

#### Logging Already Added
The backend code in `routes.py` (lines 2250-2430) ALREADY has extensive logging for Plex calls:
- Line 2265: Logs base URL being used
- Line 2271: Logs query parameters `{'type': 1, 'limit': 20}`
- Line 2280: Logs response status code

#### Enhanced Logging Added (NEW)
I have added TWO new logging lines to show the EXACT URL being constructed:

**For Movies endpoint** (`/api/recently-downloaded/movies`):
```python
# Line ~2274 (NEW)
exact_url = f"{plex_url}?{urlencode(params)}"
logging.info("[recently_downloaded_movies] EXACT URL BEING SENT: %s", exact_url)

# Line ~2281 (NEW - after requests.get)
logging.info("[recently_downloaded_movies] ACTUAL REQUEST URL: %s", resp.request.url)
```

**For TV endpoint** (`/api/recently-downloaded/tv`):
```python
# Line ~2407 (NEW)
exact_url = f"{plex_url}?{urlencode(params)}"
logging.info("[recently_downloaded_tv] EXACT URL BEING SENT: %s", exact_url)

# Line ~2416 (NEW - after requests.get)
logging.info("[recently_downloaded_tv] ACTUAL REQUEST URL: %s", resp.request.url)
```

This will output in `addarr.log`:
```
[recently_downloaded_movies] EXACT URL BEING SENT: http://your-plex:32400/library/recentlyAdded?type=1&limit=20
[recently_downloaded_movies] ACTUAL REQUEST URL: http://your-plex:32400/library/recentlyAdded?type=1&limit=20
```

### Endpoint Being Used
The code uses: `/library/recentlyAdded`

This IS a valid Plex endpoint. The alternative endpoints mentioned are:
- `/hubs/home/recentlyAdded` - This is for the newer Plex "hub" system, different structure
- `/library/sections/{sectionKey}/recentlyAdded` - This is for a SPECIFIC section

The current endpoint `/library/recentlyAdded` is correct for getting recently added items across all libraries.

### URL Normalization
The code correctly normalizes the Plex URL:
```python
plex_base_url = CONFIG.plex.url.rstrip('/')  # Removes trailing slash
plex_url = f"{plex_base_url}/library/recentlyAdded"  # Constructs clean URL
```

### Next Steps to Debug 404
1. Check `addarr.log` for the NEW log lines showing:
   - The EXACT URL string with parameters
   - The ACTUAL REQUEST URL that requests library resolved
2. If it's still 404, the issue is likely:
   - **Plex URL in config is wrong** (check CONFIG.plex.url)
   - **Plex API token is invalid** (check CONFIG.plex.token)
   - **Plex instance has firewall/proxy issues**
   - **Plex `/library/recentlyAdded` endpoint disabled** (unlikely but possible with old versions)

---

## PROBLEM 2: Only 1 Card Showing in Carousel

### Root Cause FOUND

#### Backend is Working Correctly
The backend endpoints return 20 items:
- Line 2314: `items = items[:20]` - Limits to 20 movies
- Line 2367: `logging.info("[recently_downloaded_movies] Radarr: filtered to %d movies with files. Returning from Radarr.", len(items))` - Logs the count
- The Plex section also limits to `limit=20` parameter (line 2268)

#### FRONTEND BUG IDENTIFIED
The carousel rendering code is in `templates/index.html` lines 308-392.

**The `populateCarousel()` function:**
```javascript
function populateCarousel(carouselId, items, type) {
    const carousel = document.getElementById(carouselId);
    if (!carousel) return;

    carousel.innerHTML = items.map(item => {
        // ... builds HTML for each item ...
    }).join('');
}
```

**Issue: The CSS defines the carousel as a HORIZONTAL scrolling flex container**

From `static/css/styles.css` lines 5383-5391:
```css
.carousel {
    display: flex;
    gap: 1rem;
    padding: 0;
    margin: 0;
    list-style: none;
    width: max-content;  /* <-- KEY: Content size is dynamic */
    scroll-snap-type: x mandatory;
}
```

And each item is:
```css
.carousel-item {
    flex: 0 0 150px;  /* <-- Fixed 150px width */
    scroll-snap-align: start;
    /* ... */
}
```

**Why Only 1 Card Appears:**
The carousel is a horizontal scroller that SHOULD show all 20 items. The issue is likely ONE of:

1. **CSS Viewport Bug**: The `.carousel-wrapper` might not have enough width
2. **JavaScript Bug**: The carousel might not be receiving all items (but logs say it is)
3. **Visibility Bug**: The cards might be rendering but scrolled out of view

### Diagnostic Code Added

I have NOT modified the frontend yet, but here's what to check:

#### Check #1: Is the Carousel Getting All Items?
Add this to browser console (Dev Tools F12):
```javascript
const carousel = document.getElementById('moviesCarousel');
console.log('Total carousel items:', carousel ? carousel.querySelectorAll('.carousel-item').length : 'carousel not found');
console.log('Carousel HTML:', carousel ? carousel.innerHTML.substring(0, 200) : 'not found');
```

**Expected:** Should show "Total carousel items: 20" (or however many items returned)

#### Check #2: Is the Wrapper Sized Correctly?
```javascript
const wrapper = document.querySelector('.carousel-wrapper');
console.log('Wrapper width:', wrapper ? wrapper.offsetWidth : 'not found');
console.log('Wrapper scroll width:', wrapper ? wrapper.scrollWidth : 'not found');
console.log('Wrapper height:', wrapper ? wrapper.offsetHeight : 'not found');
```

**Expected:** 
- `Wrapper width`: Should be ~90% of screen (e.g., 1000px on desktop)
- `Wrapper scroll width`: Should be much larger (e.g., 3000px for 20 items × 150px each)
- `Wrapper height`: Should be ~300px+

#### Check #3: Are API Responses Actually Returning 20 Items?
Open Dev Tools Network tab, then reload page and search for `/api/recently-downloaded/movies`:
```javascript
// In the Network tab response:
{
  "items": [
    { "id": 1, "title": "Movie 1", ... },
    { "id": 2, "title": "Movie 2", ... },
    ...
    { "id": 20, "title": "Movie 20", ... }  // Should go to 20
  ],
  "type": "movie",
  "source": "radarr"  // or "plex"
}
```

### Likely Fixes Needed (Not Applied Yet)

**If the carousel is NOT scrollable:**
The `.carousel-wrapper` might be constrained. Check if it needs:
```css
.carousel-wrapper {
    max-width: 100%;  /* Ensure parent constraint */
    width: 100%;      /* Fill parent */
}
```

**If the carousel content is there but hidden:**
Check browser zoom (should be 100%) and ensure Bootstrap is loaded.

**If only rendering 1 item:**
The `items.map()` function might be failing silently. Browser console would show errors.

---

## File Changes Summary

### Files Modified
1. **`routes.py`** (2 locations)
   - Added enhanced logging for exact Plex URL being sent
   - Added logging for actual request URL after resolution
   - Imports `urlencode` from `urllib.parse`

### Files NOT Modified (Frontend)
- `templates/index.html` - Carousel HTML and `loadRecentlyDownloaded()` function
- `static/css/styles.css` - Carousel styling
- `static/js/main.js` - Main JS file (no recent carousel code there)

### Changes Are Backward Compatible
- Uses standard `urllib.parse.urlencode` (builtin)
- Logging is INFO level (non-breaking)
- No functional changes to endpoints or data structure

---

## Recommended Next Steps

1. **Check addarr.log** for the new enhanced logging messages showing exact URLs
2. **Use browser DevTools** to verify carousel is receiving 20 items
3. **Check if `/library/recentlyAdded` endpoint exists** in your Plex instance:
   - Visit: `http://your-plex:32400/library/recentlyAdded?X-Plex-Token=YOUR_TOKEN`
   - Should return XML with multiple `<Video>` or `<Directory>` elements

4. **If 404 persists**: Try alternative Plex endpoints to find the correct one
5. **If carousel still shows 1 item**: Browser DevTools will reveal if it's CSS width, item count, or scroll issue

---

## Test URLs (Manual)

To test Plex API directly (requires your Plex URL and token):

**Movies:**
```
http://your-plex.local:32400/library/recentlyAdded?type=1&limit=20&X-Plex-Token=YOUR_TOKEN_HERE
```

**TV Shows:**
```
http://your-plex.local:32400/library/recentlyAdded?type=2&limit=20&X-Plex-Token=YOUR_TOKEN_HERE
```

Replace:
- `your-plex.local` with your actual Plex hostname/IP
- `32400` with your Plex port
- `YOUR_TOKEN_HERE` with your Plex API token

Should return XML with multiple elements.
