# Recently-Downloaded Endpoints - Testing Checklist

## Quick Summary of Changes
- Added `limit=20` to Plex API calls (movies and TV endpoints)
- Changed `requests.utils.quote()` to `urllib.parse.quote()` in all 3 endpoints
- Import added: `from urllib.parse import quote`

## Test Cases

### Test 1: Movies Endpoint Returns 20 Items
```bash
curl -X GET "http://localhost:5000/api/recently-downloaded/movies" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
Expected: 20 movie items (or fewer if library has less)
Previous: 1 movie item

### Test 2: TV Endpoint Returns 20 Items
```bash
curl -X GET "http://localhost:5000/api/recently-downloaded/tv" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
Expected: 20 TV show items (or fewer if library has less)
Previous: 1 TV show item

### Test 3: Books Endpoint Returns 20 Items
```bash
curl -X GET "http://localhost:5000/api/recently-downloaded/books" \
  -H "Authorization: Bearer YOUR_TOKEN"
```
Expected: 20 book items (or fewer if library has less)
Previous: Works fine (no limit issue, but URL encoding fixed)

### Test 4: Image Loading - Browser Inspector
1. Open browser DevTools (F12)
2. Go to Network tab
3. Visit recently-downloaded section in web UI
4. Check for `/api/img?url=...` requests

Expected behavior:
- Status 302 (first request) → redirect to source
- Status 200 (subsequent requests) → served from cache
- No 400 errors

Previous behavior:
- Status 400 (Bad URL error)
- Images never cached
- Fallback to placeholder green logo

### Test 5: URL Encoding Verification
Check that poster URLs are properly encoded:

Look for requests like:
```
✓ /api/img?url=https%3A%2F%2Fplex.example.com%2Flibrary%2Fmetadata%2F123%2Fthumb&w=150&h=225&t=Movie%20Title
✗ /api/img?url=requests.utils.quote(...) (BROKEN - don't see this)
```

### Test 6: Log Verification
Check `addarr.log` for healthy `[img_proxy]` behavior:

```
[img_proxy] MISS "Movie Title" — redirecting to source, caching in background
[img_proxy] SAVE "Movie Title" → cache updated (150×225px)
[img_proxy] HIT  "Movie Title" — serving from cache
```

## What to Watch For

### ✓ Signs of Success
- 20 items appear in each recently-downloaded category
- Poster images load immediately (no green placeholder)
- Image proxy cache logs show proper HIT/SAVE/MISS sequence
- No 400 errors in browser console
- addarr.log shows clean image proxy operations

### ✗ Signs of Remaining Issues
- Still showing only 1 item → limit parameter not working
- Green placeholder still showing → URL encoding still broken
- 400 errors in console → URL malformed
- No `[img_proxy]` logs → endpoint not being called

## Plex API Verification (Advanced)

If needed, test Plex API directly:

```bash
# Movies (type=1)
curl -X GET "http://plex-server:32400/library/recentlyAdded?type=1&limit=20" \
  -H "X-Plex-Token: YOUR_PLEX_TOKEN"

# TV Shows (type=2)
curl -X GET "http://plex-server:32400/library/recentlyAdded?type=2&limit=20" \
  -H "X-Plex-Token: YOUR_PLEX_TOKEN"
```

Expected: XML response with 20 `<Video>` or `<Directory>` elements

## Common Issues & Solutions

### Issue: Still seeing only 1 item
- Check if changes were saved to routes.py
- Check if Flask app restarted after changes
- Verify Plex is the active source (not Radarr/Sonarr)

### Issue: Images still not loading
- Check URL encoding in browser DevTools
- Look for `requests.utils.quote` references (should be gone)
- Verify `/api/img` endpoint can access poster URLs

### Issue: Images load but very slowly
- This is normal for first request (cache miss)
- Subsequent requests should be instant (cache hit)
- Check image cache directory permissions

## Deployment Steps

1. Stop Flask server
2. Apply fixes to `routes.py`
3. Restart Flask server
4. Clear browser cache (or wait for cache invalidation)
5. Test endpoints per above test cases
6. Monitor logs for 5-10 minutes

## Rollback (if needed)

If issues arise, revert to:
```python
# Line 16 - REMOVE:
from urllib.parse import quote

# Revert all quote() calls back to requests.utils.quote()
# Revert all params= changes to remove limit=20
```

But this shouldn't be necessary - the fixes are well-tested patterns.
