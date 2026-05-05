# ────────────────────────────────────────────────────────────────────────────
# CORRECTED ENDPOINTS: Plex Primary, Radarr/Sonarr Fallback
# ────────────────────────────────────────────────────────────────────────────
# LOGIC REVERSED: These endpoints now prioritize Plex and only fall back to
# Radarr/Sonarr if Plex is disabled or fails.
# ────────────────────────────────────────────────────────────────────────────

@app.route('/api/recently-downloaded/movies')
@requires_auth
def get_recently_downloaded_movies():
    """Fetch recently downloaded movies from Plex first, fallback to Radarr"""
    logging.info("[recently_downloaded_movies] ========== START REQUEST ==========")

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 1: TRY PLEX FIRST (PRIMARY SOURCE)
    # ════════════════════════════════════════════════════════════════════════
    if CONFIG.plex.enabled:
        logging.info("[recently_downloaded_movies] Plex is ENABLED. Attempting Plex call...")
        logging.info("[recently_downloaded_movies] Plex URL: %s", CONFIG.plex.url)
        logging.info("[recently_downloaded_movies] Plex token present: %s", bool(CONFIG.plex.token))

        try:
            plex_url = f"{CONFIG.plex.url}/library/recentlyAdded"
            logging.info("[recently_downloaded_movies] Attempting Plex call to: %s", plex_url)

            headers = {'X-Plex-Token': CONFIG.plex.token}
            params = {'type': 1, 'limit': 20}  # type=1 for movies, limit to 20

            logging.info("[recently_downloaded_movies] Plex headers: %s", {'X-Plex-Token': '***REDACTED***'})
            logging.info("[recently_downloaded_movies] Plex params: %s", params)

            resp = requests.get(
                plex_url,
                headers=headers,
                params=params,
                timeout=15
            )

            logging.info("[recently_downloaded_movies] Plex response status code: %s", resp.status_code)
            logging.info("[recently_downloaded_movies] Plex response content-type: %s", resp.headers.get('Content-Type', 'unknown'))
            logging.info("[recently_downloaded_movies] Plex response length: %d bytes", len(resp.content))

            if resp.status_code == 200:
                try:
                    xml_root = resp.content
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(xml_root)
                    logging.info("[recently_downloaded_movies] XML parsed successfully. Root tag: %s", root.tag)

                    video_elements = root.findall('.//Video')
                    logging.info("[recently_downloaded_movies] Found %d Video elements in XML", len(video_elements))

                    items = []
                    for idx, video in enumerate(video_elements):
                        thumb = video.get('thumb', '')
                        title = video.get('title', 'Unknown')
                        poster_url = f"{CONFIG.plex.url}{thumb}" if thumb else ''
                        item = {
                            'id': video.get('ratingKey'),
                            'tmdbId': None,
                            'title': title,
                            'poster': f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(title)}" if poster_url else '/static/images/apple-touch-icon.png',
                            'hasFile': True,
                            'year': video.get('year', ''),
                            'rating': video.get('rating', 'N/A')
                        }
                        items.append(item)
                        if idx < 3:  # Log first 3 items for debugging
                            logging.info("[recently_downloaded_movies] Plex item #%d: '%s' (ratingKey=%s, thumb=%s)",
                                       idx + 1, title, video.get('ratingKey'), thumb)

                    items = items[:20]

                    # ✓ PLEX SUCCESS - Return immediately without checking Radarr
                    if items:
                        logging.info("[recently_downloaded_movies] Plex: returning %d items (source=plex). SUCCESS - not checking Radarr.", len(items))
                        return jsonify({'items': items, 'type': 'movie', 'source': 'plex'})
                    else:
                        logging.info("[recently_downloaded_movies] Plex returned 0 items. Proceeding to Radarr fallback.")

                except ET.ParseError as e:
                    logging.error("[recently_downloaded_movies] XML parsing error: %s | Response preview: %s",
                                e, resp.content[:500])
                    logging.info("[recently_downloaded_movies] Plex XML parse failed. Proceeding to Radarr fallback.")
            else:
                logging.warning("[recently_downloaded_movies] Plex returned non-200 status: %s. Response: %s",
                              resp.status_code, resp.text[:200])
                logging.info("[recently_downloaded_movies] Plex request failed. Proceeding to Radarr fallback.")

        except Exception as e:
            logging.error("[recently_downloaded_movies] Plex error: %s", e, exc_info=True)
            logging.info("[recently_downloaded_movies] Plex exception occurred. Proceeding to Radarr fallback.")
    else:
        logging.info("[recently_downloaded_movies] Plex is DISABLED. Skipping to Radarr fallback.")

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 2: FALLBACK TO RADARR (SECONDARY SOURCE)
    # ════════════════════════════════════════════════════════════════════════
    logging.info("[recently_downloaded_movies] ========== RADARR/SONARR FALLBACK ==========")
    if CONFIG.radarr.enabled:
        logging.info("[recently_downloaded_movies] Radarr is ENABLED. Attempting Radarr call...")
        try:
            logging.info("[recently_downloaded_movies] Radarr URL: %s", CONFIG.radarr.url)
            resp = requests.get(
                f"{CONFIG.radarr.url}/api/v3/movie",
                params={'apikey': CONFIG.radarr.api_key, 'sortKey': 'added', 'sortDirection': 'descending'},
                timeout=15
            )
            logging.info("[recently_downloaded_movies] Radarr response code: %s", resp.status_code)

            if resp.status_code == 200:
                movies = resp.json()
                logging.info("[recently_downloaded_movies] Radarr returned %d total movies", len(movies))

                items = [
                    {
                        'id': m.get('id'),
                        'tmdbId': m.get('tmdbId'),
                        'title': m.get('title'),
                        'poster': f"/api/img?url={quote(m.get('remotePoster', ''))}&w=150&h=225&t={quote(m.get('title', ''))}" if m.get('remotePoster') else '/static/images/apple-touch-icon.png',
                        'hasFile': m.get('hasFile', False),
                        'year': m.get('year'),
                        'rating': m.get('ratings', {}).get('value', 'N/A')
                    }
                    for m in movies if m.get('hasFile')
                ][:20]
                logging.info("[recently_downloaded_movies] Radarr: filtered to %d movies with files. Returning from Radarr.", len(items))
                return jsonify({'items': items, 'type': 'movie', 'source': 'radarr'})
            else:
                logging.warning("[recently_downloaded_movies] Radarr returned non-200 status: %s", resp.status_code)
        except Exception as e:
            logging.warning("[recently_downloaded_movies] Radarr error: %s", e, exc_info=True)
    else:
        logging.info("[recently_downloaded_movies] Radarr is DISABLED. Skipping Radarr.")

    # ════════════════════════════════════════════════════════════════════════
    # FALLBACK FINAL: No data from either source
    # ════════════════════════════════════════════════════════════════════════
    logging.info("[recently_downloaded_movies] No data from Plex or Radarr. Returning empty list.")
    return jsonify({'items': []})


@app.route('/api/recently-downloaded/tv')
@requires_auth
def get_recently_downloaded_tv():
    """Fetch recently downloaded TV shows from Plex first, fallback to Sonarr"""
    logging.info("[recently_downloaded_tv] ========== START REQUEST ==========")

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 1: TRY PLEX FIRST (PRIMARY SOURCE)
    # ════════════════════════════════════════════════════════════════════════
    if CONFIG.plex.enabled:
        logging.info("[recently_downloaded_tv] Plex is ENABLED. Attempting Plex call...")
        logging.info("[recently_downloaded_tv] Plex URL: %s", CONFIG.plex.url)
        logging.info("[recently_downloaded_tv] Plex token present: %s", bool(CONFIG.plex.token))

        try:
            plex_url = f"{CONFIG.plex.url}/library/recentlyAdded"
            logging.info("[recently_downloaded_tv] Attempting Plex call to: %s", plex_url)

            headers = {'X-Plex-Token': CONFIG.plex.token}
            params = {'type': 2, 'limit': 20}  # type=2 for TV shows, limit to 20

            logging.info("[recently_downloaded_tv] Plex headers: %s", {'X-Plex-Token': '***REDACTED***'})
            logging.info("[recently_downloaded_tv] Plex params: %s", params)

            resp = requests.get(
                plex_url,
                headers=headers,
                params=params,
                timeout=15
            )

            logging.info("[recently_downloaded_tv] Plex response status code: %s", resp.status_code)
            logging.info("[recently_downloaded_tv] Plex response content-type: %s", resp.headers.get('Content-Type', 'unknown'))
            logging.info("[recently_downloaded_tv] Plex response length: %d bytes", len(resp.content))

            if resp.status_code == 200:
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(resp.content)
                    logging.info("[recently_downloaded_tv] XML parsed successfully. Root tag: %s", root.tag)

                    directory_elements = root.findall('.//Directory')
                    logging.info("[recently_downloaded_tv] Found %d Directory elements in XML", len(directory_elements))

                    items = []
                    for idx, video in enumerate(directory_elements):
                        thumb = video.get('thumb', '')
                        title = video.get('title', 'Unknown')
                        poster_url = f"{CONFIG.plex.url}{thumb}" if thumb else ''

                        seasons = len(video.findall('.//Directory'))
                        episodes = len(video.findall('.//Video'))

                        item = {
                            'id': video.get('ratingKey'),
                            'tvdbId': None,
                            'title': title,
                            'poster': f"/api/img?url={quote(poster_url)}&w=150&h=225&t={quote(title)}" if poster_url else '/static/images/apple-touch-icon.png',
                            'year': video.get('year', ''),
                            'seasons': seasons,
                            'episodes': episodes,
                            'rating': video.get('rating', 'N/A')
                        }
                        items.append(item)
                        if idx < 3:  # Log first 3 items for debugging
                            logging.info("[recently_downloaded_tv] Plex item #%d: '%s' (ratingKey=%s, seasons=%d, episodes=%d)",
                                       idx + 1, title, video.get('ratingKey'), seasons, episodes)

                    items = items[:20]

                    # ✓ PLEX SUCCESS - Return immediately without checking Sonarr
                    if items:
                        logging.info("[recently_downloaded_tv] Plex: returning %d items (source=plex). SUCCESS - not checking Sonarr.", len(items))
                        return jsonify({'items': items, 'type': 'tv', 'source': 'plex'})
                    else:
                        logging.info("[recently_downloaded_tv] Plex returned 0 items. Proceeding to Sonarr fallback.")

                except ET.ParseError as e:
                    logging.error("[recently_downloaded_tv] XML parsing error: %s | Response preview: %s",
                                e, resp.content[:500])
                    logging.info("[recently_downloaded_tv] Plex XML parse failed. Proceeding to Sonarr fallback.")
            else:
                logging.warning("[recently_downloaded_tv] Plex returned non-200 status: %s. Response: %s",
                              resp.status_code, resp.text[:200])
                logging.info("[recently_downloaded_tv] Plex request failed. Proceeding to Sonarr fallback.")

        except Exception as e:
            logging.error("[recently_downloaded_tv] Plex error: %s", e, exc_info=True)
            logging.info("[recently_downloaded_tv] Plex exception occurred. Proceeding to Sonarr fallback.")
    else:
        logging.info("[recently_downloaded_tv] Plex is DISABLED. Skipping to Sonarr fallback.")

    # ════════════════════════════════════════════════════════════════════════
    # STAGE 2: FALLBACK TO SONARR (SECONDARY SOURCE)
    # ════════════════════════════════════════════════════════════════════════
    logging.info("[recently_downloaded_tv] ========== RADARR/SONARR FALLBACK ==========")
    if CONFIG.sonarr.enabled:
        logging.info("[recently_downloaded_tv] Sonarr is ENABLED. Attempting Sonarr call...")
        try:
            logging.info("[recently_downloaded_tv] Sonarr URL: %s", CONFIG.sonarr.url)
            resp = requests.get(
                f"{CONFIG.sonarr.url}/api/v3/series",
                params={'apikey': CONFIG.sonarr.api_key, 'sortKey': 'added', 'sortDirection': 'descending'},
                timeout=15
            )
            logging.info("[recently_downloaded_tv] Sonarr response code: %s", resp.status_code)

            if resp.status_code == 200:
                series = resp.json()
                logging.info("[recently_downloaded_tv] Sonarr returned %d total series", len(series))

                items = [
                    {
                        'id': s.get('id'),
                        'tvdbId': s.get('tvdbId'),
                        'title': s.get('title'),
                        'poster': f"/api/img?url={quote(s.get('remotePoster', ''))}&w=150&h=225&t={quote(s.get('title', ''))}" if s.get('remotePoster') else '/static/images/apple-touch-icon.png',
                        'year': s.get('year'),
                        'seasons': s.get('statistics', {}).get('seasonCount', 0),
                        'episodes': s.get('statistics', {}).get('episodeFileCount', 0),
                        'rating': s.get('ratings', {}).get('value', 'N/A')
                    }
                    for s in series if s.get('statistics', {}).get('episodeFileCount', 0) > 0
                ][:20]
                logging.info("[recently_downloaded_tv] Sonarr: filtered to %d series with episodes. Returning from Sonarr.", len(items))
                return jsonify({'items': items, 'type': 'tv', 'source': 'sonarr'})
            else:
                logging.warning("[recently_downloaded_tv] Sonarr returned non-200 status: %s", resp.status_code)
        except Exception as e:
            logging.warning("[recently_downloaded_tv] Sonarr error: %s", e, exc_info=True)
    else:
        logging.info("[recently_downloaded_tv] Sonarr is DISABLED. Skipping Sonarr.")

    # ════════════════════════════════════════════════════════════════════════
    # FALLBACK FINAL: No data from either source
    # ════════════════════════════════════════════════════════════════════════
    logging.info("[recently_downloaded_tv] No data from Plex or Sonarr. Returning empty list.")
    return jsonify({'items': []})
