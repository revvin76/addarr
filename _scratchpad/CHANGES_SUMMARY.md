# Endpoint Logic Reversal - Summary of Changes

## Task Completed
Reversed the priority logic for two API endpoints to prioritize Plex over Radarr/Sonarr.

## Files Modified
- **C:\addarr\DEV\routes.py** - Lines 2250-2507

## Endpoints Updated

### 1. `/api/recently-downloaded/movies` (Lines 2250-2375)
**Status:** COMPLETE

**Old Flow:**
1. Try Radarr first
2. If Radarr returns data, return it immediately
3. Only if Radarr fails/disabled, try Plex
4. If both fail, return empty

**New Flow:**
1. Try Plex first (PRIMARY)
2. If Plex returns data with items, return immediately (no Radarr check)
3. If Plex disabled/fails/returns 0 items, fall back to Radarr
4. If Radarr returns data, return it
5. If both fail, return empty

### 2. `/api/recently-downloaded/tv` (Lines 2377-2507)
**Status:** COMPLETE

**Old Flow:**
1. Try Sonarr first
2. If Sonarr returns data, return it immediately
3. Only if Sonarr fails/disabled, try Plex
4. If both fail, return empty

**New Flow:**
1. Try Plex first (PRIMARY)
2. If Plex returns data with items, return immediately (no Sonarr check)
3. If Plex disabled/fails/returns 0 items, fall back to Sonarr
4. If Sonarr returns data, return it
5. If both fail, return empty

## Key Changes Made

### Logging Structure
Both endpoints now have consistent logging markers:
- `START REQUEST` - Begin of request
- `Plex is ENABLED/DISABLED` - Plex section
- `Plex success/failure messages` - Detailed outcome
- `RADARR/SONARR FALLBACK` - Transition to secondary source
- `No data from Plex or [Radarr/Sonarr]` - Final fallback

### Success Conditions
**Plex** returns immediately if:
- Response status is 200
- XML parses successfully
- `items` list is not empty

**Radarr/Sonarr** only checked if:
- Plex is disabled, OR
- Plex request fails, OR
- Plex returns empty list

### Fallback Scenarios
When Plex returns empty (0 items), logging explicitly states:
```
"Plex returned 0 items. Proceeding to Radarr/Sonarr fallback."
```

When Plex fails with exceptions:
```
"Plex exception occurred. Proceeding to Radarr/Sonarr fallback."
```

When Plex XML fails to parse:
```
"Plex XML parse failed. Proceeding to Radarr/Sonarr fallback."
```

## Testing Recommendations

1. **Test with Plex enabled and returning data:**
   - Should return Plex results immediately
   - Radarr/Sonarr should NOT be called
   - Response should include `"source": "plex"`

2. **Test with Plex enabled but returning empty:**
   - Should fall back to Radarr/Sonarr
   - Should return their results with appropriate source

3. **Test with Plex disabled:**
   - Should skip Plex entirely
   - Should go directly to Radarr/Sonarr

4. **Test with both sources returning data:**
   - Plex should always take priority
   - Radarr/Sonarr should never be called

5. **Test with both sources failing:**
   - Should return empty list `{'items': []}`

## Output Files
- **C:\addarr\DEV\_scratchpad\plex_primary_endpoints.py** - Reference implementation with full code
- **C:\addarr\DEV\_scratchpad\CHANGES_SUMMARY.md** - This document
