#!/usr/bin/env python3
"""
Diagnostic tool to test Plex API connectivity and payload structure.
Helps identify whether Plex is the issue or the Flask app.
"""
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
import json

# Load config
import sys
sys.path.insert(0, 'C:\\addarr\\DEV')
from lazy_config import get_config

CONFIG = get_config()

print("\n" + "="*80)
print("PLEX API DIAGNOSTIC TEST")
print("="*80 + "\n")

# Test 1: Check Plex configuration
print("1. CONFIGURATION CHECK")
print("-" * 80)
print(f"   Plex Enabled: {CONFIG.plex.enabled}")
print(f"   Plex URL: {CONFIG.plex.url}")
print(f"   Plex Token Present: {bool(CONFIG.plex.token)}")
if not CONFIG.plex.enabled:
    print("\n   ⚠️  Plex is DISABLED in config. Enable it to proceed.")
    sys.exit(1)

# Test 2: Test URL normalization
print("\n2. URL NORMALIZATION CHECK")
print("-" * 80)
plex_base_url = CONFIG.plex.url.rstrip('/')
endpoint_url = f"{plex_base_url}/library/recentlyAdded"
print(f"   Original URL: {CONFIG.plex.url}")
print(f"   Normalized URL: {plex_base_url}")
print(f"   Full Endpoint: {endpoint_url}")
if "//" in endpoint_url.replace("://", ""):  # Check for double slash (accounting for http://)
    print("   ⚠️  DOUBLE SLASH DETECTED! This will cause 404 errors.")
else:
    print("   ✓ URL structure is correct (no double slashes)")

# Test 3: Test Plex Movies endpoint
print("\n3. PLEX MOVIES API TEST")
print("-" * 80)
try:
    headers = {'X-Plex-Token': CONFIG.plex.token}
    params = {'type': 1, 'limit': 20}  # type=1 = movies

    print(f"   URL: {endpoint_url}")
    print(f"   Method: GET")
    print(f"   Params: {params}")

    resp = requests.get(endpoint_url, headers=headers, params=params, timeout=15)
    print(f"   Response Status: {resp.status_code}")
    print(f"   Response Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
    print(f"   Response Length: {len(resp.content)} bytes")

    if resp.status_code == 200:
        try:
            root = ET.fromstring(resp.content)
            video_elements = root.findall('.//Video')
            print(f"   ✓ XML parsed successfully")
            print(f"   ✓ Found {len(video_elements)} movie elements")

            if len(video_elements) > 0:
                print("\n   First 3 movies:")
                for idx, video in enumerate(video_elements[:3]):
                    title = video.get('title', 'Unknown')
                    thumb = video.get('thumb', 'NO THUMB')
                    poster_url = f"{plex_base_url}{thumb}" if thumb else "NO POSTER"
                    print(f"      [{idx+1}] {title}")
                    print(f"          Thumb: {thumb}")
                    print(f"          Full URL: {poster_url}")
                    encoded = quote(poster_url)
                    print(f"          Encoded: {encoded}")
            else:
                print("   ⚠️  No movie elements found. Check your Plex library.")

        except ET.ParseError as e:
            print(f"   ✗ XML Parse Error: {e}")
            print(f"   Response Preview: {resp.content[:300]}")
    else:
        print(f"   ✗ Non-200 status code. Plex may be unreachable or token invalid.")
        print(f"   Response: {resp.text[:200]}")

except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Test Plex TV endpoint
print("\n4. PLEX TV API TEST")
print("-" * 80)
try:
    headers = {'X-Plex-Token': CONFIG.plex.token}
    params = {'type': 2, 'limit': 20}  # type=2 = TV shows

    print(f"   URL: {endpoint_url}")
    print(f"   Method: GET")
    print(f"   Params: {params}")

    resp = requests.get(endpoint_url, headers=headers, params=params, timeout=15)
    print(f"   Response Status: {resp.status_code}")
    print(f"   Response Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
    print(f"   Response Length: {len(resp.content)} bytes")

    if resp.status_code == 200:
        try:
            root = ET.fromstring(resp.content)
            dir_elements = root.findall('.//Directory')
            print(f"   ✓ XML parsed successfully")
            print(f"   ✓ Found {len(dir_elements)} TV show elements")

            if len(dir_elements) > 0:
                print("\n   First 3 TV shows:")
                for idx, video in enumerate(dir_elements[:3]):
                    title = video.get('title', 'Unknown')
                    thumb = video.get('thumb', 'NO THUMB')
                    poster_url = f"{plex_base_url}{thumb}" if thumb else "NO POSTER"
                    print(f"      [{idx+1}] {title}")
                    print(f"          Thumb: {thumb}")
                    print(f"          Full URL: {poster_url}")
                    encoded = quote(poster_url)
                    print(f"          Encoded: {encoded}")
            else:
                print("   ⚠️  No TV show elements found. Check your Plex library.")

        except ET.ParseError as e:
            print(f"   ✗ XML Parse Error: {e}")
            print(f"   Response Preview: {resp.content[:300]}")
    else:
        print(f"   ✗ Non-200 status code. Plex may be unreachable or token invalid.")
        print(f"   Response: {resp.text[:200]}")

except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("DIAGNOSTIC COMPLETE")
print("="*80 + "\n")
print("NEXT STEPS:")
print("  1. If all tests PASS (✓), the issue is in Flask or the frontend")
print("  2. If any test FAILS (✗), the issue is with Plex configuration or connectivity")
print("  3. Check the Flask logs at: tail -f <your-flask-app-log>")
print("  4. Reload the app and check if carousels display 20 items with thumbnails")
