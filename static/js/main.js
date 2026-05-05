let currentShowId = null; // track show id for delete/search actions

/**
 * imgProxy(url, w, h, title)
 * Routes any remote image URL through the local caching proxy (/api/img).
 * The server normalises TMDB /original/ → /w342/ before fetching, so
 * downloads are ~10× smaller while still looking sharp at card sizes.
 * Local and relative URLs (starting with '/') are returned unchanged.
 * The optional title appears in arrdash.log so cache events are readable.
 *
 * @param {string} url   - Remote image URL
 * @param {number} w     - Target display width  (default 174)
 * @param {number} h     - Target display height (default 261)
 * @param {string} title - Human-readable label for server logs (optional)
 */
function imgProxy(url, w = 174, h = 261, title = '') {
    if (!url || url.startsWith('/')) return url;
    let qs = `/api/img?url=${encodeURIComponent(url)}&w=${w}&h=${h}`;
    if (title) qs += `&t=${encodeURIComponent(title)}`;
    return qs;
}
let deferredPrompt;
let player = null;
const installButton = document.getElementById('install-button'); // Add this button to your HTML

// ── Background fetch priority management ─────────────────────────────────────
// showDetails / showManageDetails call _pauseBackgroundFetches() the moment
// they fire. Any in-flight background request (batch library status, manage
// grid details, book enrichment) is aborted so the browser's connection pool
// is freed for the detail request. Aborted tasks register a resume callback
// and restart automatically when the details modal closes.
const _bg = {
    controller:  new AbortController(),
    resumeQueue: [],
    navigating: false,
    get signal() { return this.controller.signal; }
};
// Expose to inline page scripts (trending.html, manage-books.html)
window._bg = _bg;
window._registerBgResume = fn => {
    if (_bg.navigating) return;
    _bg.resumeQueue.push(fn);
};

const _detailsScrollLock = {
    y: 0,
    locked: false
};

function _lockDetailsModalScroll() {
    if (_detailsScrollLock.locked) return;
    _detailsScrollLock.y = window.scrollY || window.pageYOffset || 0;
    document.body.classList.add('details-modal-open');
    document.body.style.top = `-${_detailsScrollLock.y}px`;
    _detailsScrollLock.locked = true;
}

function _unlockDetailsModalScroll() {
    if (!_detailsScrollLock.locked) return;
    const y = _detailsScrollLock.y || 0;
    document.body.classList.remove('details-modal-open');
    document.body.style.top = '';
    window.scrollTo(0, y);
    _detailsScrollLock.locked = false;
}

function _pauseBackgroundFetches() {
    _bg.controller.abort();
    _bg.controller = new AbortController();   // fresh controller for next use
}
function _stopBackgroundWorkForNavigation() {
    _bg.navigating = true;
    _bg.resumeQueue.length = 0;
    _pauseBackgroundFetches();
}
function _resumeBackgroundFetches() {
    if (_bg.navigating) return;
    const fns = _bg.resumeQueue.splice(0);
    fns.forEach(fn => { try { fn(); } catch(e) { console.error('[bg resume]', e); } });
}
// Wire modal close → resume (works for both detailsModal and confirmModal)
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.modal').forEach(el => {
        el.addEventListener('hidden.bs.modal', _resumeBackgroundFetches);
    });
    const detailsModal = document.getElementById('detailsModal');
    if (detailsModal) {
        detailsModal.addEventListener('shown.bs.modal', _lockDetailsModalScroll);
        detailsModal.addEventListener('hidden.bs.modal', _unlockDetailsModalScroll);
    }

    initAutoHideHeader();
});

function initAutoHideHeader() {
    const topbar = document.getElementById('appTopbar');
    if (!topbar) return;
    const params = new URLSearchParams(window.location.search);
    const source = params.get('source');
    const path = window.location.pathname || '';
    const isHomeLaunchSurface = source === 'home' && (
        path.includes('/manage') ||
        path.includes('/manage-books') ||
        path.includes('/search') ||
        path.includes('/results')
    );

    if (isHomeLaunchSurface) {
        document.body.classList.add('app-header-hidden');
        return;
    }

    let lastY = window.scrollY || 0;
    let ticking = false;

    const setHeaderHidden = (hidden) => {
        document.body.classList.toggle('app-header-hidden', hidden);
    };

    const shouldKeepVisible = () => {
        return (
            (window.scrollY || 0) < 24 ||
            document.body.classList.contains('settings-drawer-open') ||
            document.body.classList.contains('restart-pending') ||
            document.body.classList.contains('spinner-active')
        );
    };

    const onScroll = () => {
        const currentY = window.scrollY || 0;
        const delta = currentY - lastY;
        lastY = currentY;

        if (shouldKeepVisible()) {
            setHeaderHidden(false);
            return;
        }

        if (Math.abs(delta) < 8) return;

        if (delta > 0) {
            setHeaderHidden(true);
        } else {
            setHeaderHidden(false);
        }
    };

    window.addEventListener('scroll', () => {
        if (!ticking) {
            window.requestAnimationFrame(() => {
                onScroll();
                ticking = false;
            });
            ticking = true;
        }
    }, { passive: true });

    setHeaderHidden(false);
}

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  
  const installButton = document.getElementById('install-button');
  if (installButton) {
    installButton.style.display = 'block';
    installButton.addEventListener('click', async () => {
      installButton.style.display = 'none';
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      console.log(`User response to the install prompt: ${outcome}`);
      deferredPrompt = null;
    });
  }
});

window.addEventListener('appinstalled', () => {
  console.log('PWA was installed');
  if (installButton) installButton.style.display = 'none';
  deferredPrompt = null;
  
  // Optionally send analytics that PWA was installed
});

// Global cache for quality profiles and selection state
const _addItemCache = {
    qualityProfiles: null,
    rootFolders: null,
    selectedQuality: {},
    selectedSeason: {},
    movieAddPrefs: {}
};

const _detailCache = {
    manage: {},
    tmdb: {}
};

function addItem(mediaType, mediaId) {
    console.log(`[addItem] Adding ${mediaType} ID: ${mediaId}`);

    // For movies, show quality selection modal
    if (mediaType === 'movie') {
        showQualitySelectionModal(mediaType, mediaId);
        return;
    }

    // For TV shows, show season selection modal
    if (mediaType === 'tv') {
        showSeasonSelectionModal(mediaType, mediaId);
        return;
    }

    // For books, add directly (no quality/season selection)
    performAdd(mediaType, mediaId);
}

function showQualitySelectionModal(mediaType, mediaId) {
    console.log('[showQualitySelectionModal] Fetching quality profiles...');

    // Create modal if it doesn't exist
    let modal = document.getElementById('qualitySelectionModal');
    if (!modal) {
        const modalHtml = `
        <div class="modal fade" id="qualitySelectionModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content bg-dark border-secondary">
                    <div class="modal-header border-secondary">
                        <h5 class="modal-title">Select Quality Profile</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <div id="qualityProfilesContent" class="text-center">
                            <div class="spinner-border text-primary" role="status">
                                <span class="visually-hidden">Loading...</span>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer border-secondary">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" id="qualityAddBtn" onclick="performAddWithQuality()">Add</button>
                    </div>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        modal = document.getElementById('qualitySelectionModal');
    }

    // Fetch quality profiles if not cached
    if (!_addItemCache.qualityProfiles) {
        fetch('/api/radarr/qualityprofile')
            .then(res => res.json())
            .then(profiles => {
                console.log('[showQualitySelectionModal] Profiles:', profiles);
                _addItemCache.qualityProfiles = profiles;
                renderQualitySelection(profiles, mediaId);
            })
            .catch(error => {
                console.error('[showQualitySelectionModal] Error:', error);
                document.getElementById('qualityProfilesContent').innerHTML =
                    '<div class="alert alert-danger">Failed to load quality profiles</div>';
            });
    } else {
        renderQualitySelection(_addItemCache.qualityProfiles, mediaId);
    }

    modal.dataset.mediaId = mediaId;
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

function renderQualitySelection(profiles, mediaId) {
    const content = document.getElementById('qualityProfilesContent');
    const defaultProfile = profiles.find(p => p.name === 'Default') || profiles[0];
    const defaultId = defaultProfile?.id || null;

    _addItemCache.selectedQuality[mediaId] = defaultId;

    const html = `
        <div class="mb-3">
            <label class="form-label">Quality Profile</label>
            <select id="qualityProfileSelect" class="form-select form-select-sm bg-secondary text-white" onchange="updateSelectedQuality('${mediaId}')">
                ${profiles.map(profile => `
                    <option value="${profile.id}" ${profile.id === defaultId ? 'selected' : ''}>
                        ${profile.name}
                    </option>
                `).join('')}
            </select>
        </div>
        <small class="text-muted">
            Selected: <strong id="qualityName">${defaultProfile?.name || 'Default'}</strong>
        </small>
    `;
    content.innerHTML = html;
}

function updateSelectedQuality(mediaId) {
    const select = document.getElementById('qualityProfileSelect');
    _addItemCache.selectedQuality[mediaId] = parseInt(select.value);
    const profile = _addItemCache.qualityProfiles.find(p => p.id === _addItemCache.selectedQuality[mediaId]);
    document.getElementById('qualityName').textContent = profile?.name || 'Unknown';
}

function performAddWithQuality() {
    // This will be called from the modal, but we need mediaId context
    // Store it in data attribute or use a better approach
    const mediaId = document.getElementById('qualitySelectionModal').dataset.mediaId;
    if (!mediaId) {
        console.error('[performAddWithQuality] No media ID found');
        return;
    }
    const qualityId = _addItemCache.selectedQuality[mediaId];
    performAdd('movie', mediaId, qualityId);
    bootstrap.Modal.getInstance(document.getElementById('qualitySelectionModal')).hide();
}

function showSeasonSelectionModal(mediaType, mediaId) {
    console.log('[showSeasonSelectionModal] Showing season selection for TV:', mediaId);

    // Create modal if it doesn't exist
    let modal = document.getElementById('seasonSelectionModal');
    if (!modal) {
        const modalHtml = `
        <div class="modal fade" id="seasonSelectionModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content bg-dark border-secondary">
                    <div class="modal-header border-secondary">
                        <h5 class="modal-title">Select Season(s) to Monitor</h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <div id="seasonOptionsContent"></div>
                    </div>
                    <div class="modal-footer border-secondary">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" id="seasonAddBtn" onclick="performAddWithSeason()">Add</button>
                    </div>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        modal = document.getElementById('seasonSelectionModal');
    }

    _addItemCache.selectedSeason[String(mediaId)] = 'latest'; // Default

    const html = `
        <div class="season-selection">
            <div class="form-check mb-2">
                <input class="form-check-input" type="radio" name="seasonFilter" value="latest" id="seasonLatest" checked onchange="updateSelectedSeason('${mediaId}')">
                <label class="form-check-label" for="seasonLatest">
                    <strong>Latest Season</strong>
                    <small class="text-muted d-block">Monitor only the most recent season</small>
                </label>
            </div>
            <div class="form-check mb-2">
                <input class="form-check-input" type="radio" name="seasonFilter" value="all" id="seasonAll" onchange="updateSelectedSeason('${mediaId}')">
                <label class="form-check-label" for="seasonAll">
                    <strong>All Seasons</strong>
                    <small class="text-muted d-block">Monitor all seasons including past ones</small>
                </label>
            </div>
            <div class="form-check">
                <input class="form-check-input" type="radio" name="seasonFilter" value="future" id="seasonFuture" onchange="updateSelectedSeason('${mediaId}')">
                <label class="form-check-label" for="seasonFuture">
                    <strong>Future Seasons</strong>
                    <small class="text-muted d-block">Monitor only upcoming/unaired seasons</small>
                </label>
            </div>
        </div>
    `;
    document.getElementById('seasonOptionsContent').innerHTML = html;

    modal.dataset.mediaId = mediaId;
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

function updateSelectedSeason(mediaId) {
    const selected = document.querySelector('input[name="seasonFilter"]:checked');
    _addItemCache.selectedSeason[String(mediaId)] = selected?.value || 'latest';
}

function performAddWithSeason() {
    const modal = document.getElementById('seasonSelectionModal');
    const mediaId = String(modal.dataset.mediaId);
    if (!mediaId) {
        console.error('[performAddWithSeason] No media ID found');
        return;
    }
    const seasonFilter = _addItemCache.selectedSeason[String(mediaId)] || 'latest';
    performAdd('tv', mediaId, null, seasonFilter);
    bootstrap.Modal.getInstance(modal).hide();
}

function performAdd(mediaType, mediaId, qualityProfileId=null, seasonFilter='latest') {
    const btn = document.querySelector(`[data-media-type="${mediaType}"][data-media-id="${mediaId}"]`)?.querySelector('.add-btn');

    console.log(`[performAdd] Adding ${mediaType} ID: ${mediaId}`, { qualityProfileId, seasonFilter });

    const payload = { media_type: mediaType, media_id: mediaId };
    if (qualityProfileId !== null && qualityProfileId !== undefined) {
        payload.quality_profile_id = qualityProfileId;
    }
    if (seasonFilter && mediaType === 'tv') {
        payload.season_filter = seasonFilter;
    }

    fetch('/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        console.log(`[performAdd] Response:`, data);

        if (data.success) {
            showNotification('Added successfully!', 'success');

            // Update button to "View in Library" after successful add
            if (btn) {
                updateAddButtonToViewInLibrary(btn, mediaType, mediaId);
            }

            // Refresh the status badge after delay
            setTimeout(() => {
                const resultItem = document.querySelector(
                    `.result-item[data-media-type="${mediaType}"][data-media-id="${mediaId}"]`
                );

                if (resultItem) {
                    const card = resultItem.querySelector('.search-result-card');
                    if (card && typeof checkLibraryStatus === 'function') {
                        checkLibraryStatus(mediaType, mediaId, card);
                    }
                }
            }, 1000);
        } else {
            showNotification('Error adding item: ' + (data.error || 'Unknown error'), 'error');
            if (btn) {
                btn.disabled = false;
                btn.textContent = `Add to ${mediaType === 'tv' ? 'Sonarr' : mediaType === 'book' ? 'Readarr' : 'Radarr'}`;
            }
        }
    })
    .catch(error => {
        console.error('[performAdd] Error:', error);
        showNotification('Error adding item: ' + error.message, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = `Add to ${mediaType === 'tv' ? 'Sonarr' : mediaType === 'book' ? 'Readarr' : 'Radarr'}`;
        }
    });
}

function updateAddButtonToViewInLibrary(btn, mediaType, mediaId) {
    // Fetch the internal ID to link to the library entry
    fetch(`/get_media_details?type=${mediaType}&id=${mediaId}`)
        .then(response => response.json())
        .then(data => {
            const itemData = data.data || data;
            const internalId = itemData.id;

            // Update button styling
            btn.className = 'btn btn-success add-btn';
            btn.innerHTML = '<i class="fas fa-external-link-alt me-2"></i>View in Library';
            btn.disabled = false;
            btn.title = 'Go to library entry';

            // Update onclick to navigate to library
            btn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                window.location.href = `/manage?open=${encodeURIComponent(internalId)}&type=${mediaType}`;
            };
        })
        .catch(error => {
            console.error('Error fetching media details for button update:', error);
            // Fallback: just show a generic "View in Library" link
            btn.className = 'btn btn-success add-btn';
            btn.innerHTML = '<i class="fas fa-external-link-alt me-2"></i>View in Library';
            btn.disabled = false;
            btn.title = 'Go to library';

            btn.onclick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                window.location.href = `/manage?type=${mediaType}`;
            };
        });
}

function createDefaultPoster(title, year) {
    // Simple SVG solution instead of canvas
    return `data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='500' height='750'>
        <rect width='100%' height='100%' fill='%232c3e50'/>
        <image href='/static/images/logo.png' width='60%' x='20%' y='25%'/>
        <text x='50%' y='15%' font-family='Arial' font-size='24' fill='white' text-anchor='middle' font-weight='bold'>${encodeURIComponent(title || 'No Title')}</text>
        <text x='50%' y='18%' font-family='Arial' font-size='18' fill='white' text-anchor='middle'>${year ? `(${encodeURIComponent(year)})` : ''}</text>
    </svg>`;
}

function showFullImage(src) {
    const modalBackdrop = document.getElementById('modal-overlay-backdrop');
    
    // Show overlay first (with higher z-index)
    modalBackdrop.style.display = 'block';

    // Create or update the modal
    let imageModal = document.getElementById('imageModal');
    if (!imageModal) {
        const modalHtml = `
        <div class="modal fade" id="imageModal" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-xl modal-dialog-centered">
                <div class="modal-content bg-transparent border-0">
                    <button type="button" class="btn-close btn-close-white position-absolute top-0 end-0 m-2" 
                            data-bs-dismiss="modal" aria-label="Close"></button>
                    <img src="${src}" class="img-fluid mx-auto d-block full-image-preview" alt="Full size">
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        imageModal = document.getElementById('imageModal');
    } else {
        imageModal.querySelector('img').src = src;
    }

    // Initialize and show modal
    const modal = new bootstrap.Modal(imageModal, {
        backdrop: false // We're using our own backdrop
    });
    modal.show();

    // Ensure modal is above our overlay
    imageModal.style.zIndex = '1070';

    // Hide overlay when modal closes
    imageModal.addEventListener('hidden.bs.modal', function () {
        modalBackdrop.style.display = 'none';
        // Optional: Remove modal from DOM if you want
        // imageModal.remove();
    }, { once: true });
}

function showManageDetails(mediaType, externalId, internalId, lookupSource = '', homeContext = null) {
    _pauseBackgroundFetches();
    console.log('Showing details for:', mediaType, externalId, internalId);
    
    const modalEl = document.getElementById('detailsModal');
    const modal = new bootstrap.Modal(modalEl);
    const modalTitle = document.getElementById('detailsModalLabel');
    const overlay = document.getElementById('overlay-backdrop');
    modalEl._homeLaunchContext = homeContext || modalEl._homeLaunchContext || null;
    const deferModalOpen = !!homeContext;
    
    setDetailsModalVariant(mediaType);
    
    // Set modal title based on media type
    const typeLabel = mediaType === 'tv' ? 'TV Show' : mediaType === 'book' ? 'Book' : 'Movie';
    modalTitle.textContent = `${typeLabel} Details`;

    const showManageModalChrome = () => {
        overlay.style.display = 'block';
        modal.show();
    };
    
    // Add event listener to hide overlay when modal is closed
    const hideModalHandler = function() {
        overlay.style.display = 'none';
        modalEl.removeEventListener('hidden.bs.modal', hideModalHandler);
    };
    
    modalEl.addEventListener('hidden.bs.modal', hideModalHandler);

    if (!deferModalOpen) {
        document.getElementById('detailsContent').innerHTML = renderDetailLoadingSkeleton(mediaType);
        showManageModalChrome();
    }

    const cacheKey = `${mediaType}:${lookupSource || 'default'}:${externalId}`;
    const cachedDetail = _detailCache.manage[cacheKey];
    const tmdbCacheKey = mediaType === 'movie' ? `movie:${externalId}` : '';
    const cachedTmdb = tmdbCacheKey ? _detailCache.tmdb[tmdbCacheKey] : null;

    if (cachedDetail && !deferModalOpen) {
        populateManageModalDetails(cachedDetail, mediaType, internalId, cachedTmdb || null);
    }

    // Fetch details from your backend
    const lookupQuery = lookupSource ? `&source=${encodeURIComponent(lookupSource)}` : '';
    const detailPromise = fetch(`/get_media_details?type=${mediaType}&id=${externalId}${lookupQuery}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(async data => {
            let tmdbData = null;
            if (mediaType === 'movie' && externalId) {
                try {
                    if (cachedTmdb) {
                        tmdbData = cachedTmdb;
                    } else {
                        const tmdbResponse = await fetch(`/get_tmdb_details?type=movie&id=${externalId}`);
                        if (tmdbResponse.ok) {
                            tmdbData = await tmdbResponse.json();
                            _detailCache.tmdb[tmdbCacheKey] = tmdbData;
                        }
                    }
                } catch (tmdbError) {
                    console.warn('TMDB details unavailable for movie modal:', tmdbError);
                }
            }
            _detailCache.manage[cacheKey] = data;
            populateManageModalDetails(data, mediaType, internalId, tmdbData);
            if (deferModalOpen && !modalEl.classList.contains('show')) {
                showManageModalChrome();
            }
        })
        .catch(error => {
            console.error('Error fetching details:', error);
            document.getElementById('detailsContent').innerHTML = `
                <div class="alert alert-danger">
                    Error loading details: ${error.message}
                </div>`;
            if (deferModalOpen && !modalEl.classList.contains('show')) {
                showManageModalChrome();
            }
        });

    const shouldBlockGlobalLoader = !!homeContext && !!window.trackGlobalLoading;
    if (shouldBlockGlobalLoader) {
        window.trackGlobalLoading(detailPromise, 'Loading details...');
    }
}

function renderDetailLoadingSkeleton(mediaType) {
    const title = mediaType === 'tv' ? 'TV Show' : mediaType === 'book' ? 'Book' : 'Movie';
    return `
        <section class="movie-detail movie-detail--loading" aria-label="Loading ${title} details">
            <div class="movie-detail__hero">
                <div class="movie-detail__hero-bg movie-detail__skeleton-block"></div>
                <div class="movie-detail__hero-overlay"></div>
            </div>

            <div class="movie-detail__sheet">
                <div class="movie-detail__summary">
                    <div class="movie-detail__poster-wrap">
                        <div class="movie-detail__poster movie-detail__skeleton-block"></div>
                    </div>
                    <div class="movie-detail__headline">
                        <div class="movie-detail__skeleton-line movie-detail__skeleton-line--sm"></div>
                        <div class="movie-detail__skeleton-line movie-detail__skeleton-line--title"></div>
                        <div class="movie-detail__meta-row movie-detail__meta-row--loading">
                            <span class="movie-detail__skeleton-pill"></span>
                            <span class="movie-detail__skeleton-pill"></span>
                            <span class="movie-detail__skeleton-pill"></span>
                        </div>
                    </div>
                </div>

                <div class="movie-detail__actions movie-detail__actions--loading">
                    <div class="movie-detail__action movie-detail__skeleton-block"></div>
                    <div class="movie-detail__action movie-detail__skeleton-block"></div>
                    <div class="movie-detail__action movie-detail__skeleton-block"></div>
                </div>

                <div class="movie-detail__divider"></div>

                <div class="movie-detail__file-card movie-detail__skeleton-block movie-detail__skeleton-card"></div>

                <div class="movie-detail__overview movie-detail__overview--loading">
                    <div class="movie-detail__skeleton-line"></div>
                    <div class="movie-detail__skeleton-line"></div>
                    <div class="movie-detail__skeleton-line movie-detail__skeleton-line--lg"></div>
                </div>
            </div>
        </section>`;
}

async function parseApiResponse(response) {
    const text = await response.text();
    let data = {};

    try {
        data = text ? JSON.parse(text) : {};
    } catch (error) {
        const snippet = text ? text.slice(0, 120).replace(/\s+/g, ' ').trim() : `HTTP ${response.status}`;
        throw new Error(`Unexpected response from server (${response.status}): ${snippet}`);
    }

    return { ok: response.ok, data };
}

// Function to populate modal with details for manage page
function setDetailsModalVariant(variant) {
    const modalEl = document.getElementById('detailsModal');
    if (!modalEl) return;
    modalEl.classList.remove('details-modal--movie');
    if (variant) {
        modalEl.classList.add('details-modal--movie');
    }
}

function populateManageModalDetails(data, mediaType, internalId, tmdbData = null) {
    const detailsContent = document.getElementById('detailsContent');

    // Extract the actual media data
    const mediaData = data.data || data;

    if (mediaType === 'movie') {
        setDetailsModalVariant('movie');
        renderMovieDetails(mediaData, data, mediaType, internalId, tmdbData);
    } else if (mediaType === 'book') {
        setDetailsModalVariant('book');
        renderBookDetails(mediaData, data, mediaType, internalId);
    } else {
        setDetailsModalVariant('tv');
        renderTVDetails(mediaData, data, mediaType, internalId, tmdbData);
    }
}

function buildDetailTrailerSection(trailerKey, title) {
    if (!trailerKey) return '';
    return `
        <section class="movie-detail__section">
            <h3 class="movie-detail__section-title">Trailer</h3>
            <div class="movie-detail__embed ratio ratio-16x9">
                <iframe src="https://www.youtube.com/embed/${trailerKey}?rel=0&modestbranding=1"
                        title="${title} trailer"
                        frameborder="0"
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                        allowfullscreen>
                </iframe>
            </div>
        </section>`;
}

function buildDetailOverviewSection(overview, sectionKey = 'default') {
    const safeOverview = overview || 'No overview available.';
    const needsToggle = safeOverview.length > 260;
    const targetId = `detailOverview_${sectionKey}`;
    return `
        <section class="movie-detail__section movie-detail__section--overview">
            <div class="movie-detail__section-head">
                <h3 class="movie-detail__section-title">Overview</h3>
                ${needsToggle ? `
                <button type="button"
                        class="movie-detail__overview-toggle"
                        aria-expanded="false"
                        aria-controls="${targetId}"
                        onclick="toggleDetailOverview(this, '${targetId}')">
                    <i class="fas fa-chevron-down"></i>
                </button>` : ''}
            </div>
            <div class="movie-detail__overview-body ${needsToggle ? 'is-collapsed' : ''}" id="${targetId}">
                <p class="movie-detail__overview">${safeOverview}</p>
            </div>
        </section>`;
}

function buildDetailInfoGrid(items) {
    if (!Array.isArray(items) || !items.length) return '';
    return `
        <div class="movie-detail__info-grid">
            ${items.map(item => `
                <div class="movie-detail__info-item ${item.full ? 'movie-detail__info-item--full' : ''}">
                    <span class="movie-detail__info-label">${item.label}</span>
                    <strong class="movie-detail__info-value ${item.code ? 'movie-detail__info-value--code' : ''}">${item.value}</strong>
                </div>
            `).join('')}
        </div>`;
}

function toggleDetailOverview(button, targetId) {
    const body = document.getElementById(targetId);
    if (!body) return;
    const isCollapsed = body.classList.contains('is-collapsed');
    body.classList.toggle('is-collapsed', !isCollapsed);
    body.classList.toggle('is-expanded', isCollapsed);
    button.setAttribute('aria-expanded', isCollapsed ? 'true' : 'false');
    button.classList.toggle('is-expanded', isCollapsed);
}

function renderBookDetails(mediaData, fullData, mediaType, internalId) {
    const detailsContent = document.getElementById('detailsContent');
    const secondaryActionsId = `bookDetailActions_${internalId || mediaData.id || mediaData.internal_id || 'temp'}`;
    const author = typeof mediaData.author === 'object'
        ? (mediaData.author?.authorName || mediaData.author?.name || 'Unknown Author')
        : (mediaData.author || 'Unknown Author');

    const posterImage = mediaData.images?.find(img => img.coverType === 'poster' || img.coverType === 'cover');
    const posterSource = posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png';
    const posterUrl = imgProxy(posterSource, 300, 450, mediaData.title);
    const backdropUrl = imgProxy(posterSource || '/static/images/apple-touch-icon.png', 1280, 720, mediaData.title);

    const releaseYear = mediaData.releaseDate ? mediaData.releaseDate.substring(0, 4) : 'N/A';
    const pageCount = mediaData.pageCount ? `${mediaData.pageCount} pages` : '';
    const overview = mediaData.overview || 'No description available.';
    const sizeOnDisk = mediaData.statistics?.sizeOnDisk
        ? formatFileSize(mediaData.statistics.sizeOnDisk)
        : 'N/A';
    const onDisk = fullData.on_disk || false;
    const monitored = fullData.monitored || false;
    const pathLabel = mediaData.path || 'N/A';
    const addedDate = mediaData.added ? formatReadableDate(mediaData.added) : 'Unknown';
    const formatLabel = mediaData.format || mediaData.fileType || 'Library';
    const hasMetadataEditor = typeof window.triggerImport === 'function';
    const canRelinkBook = !!mediaData.id;
    const overviewSection = buildDetailOverviewSection(overview, `book_${internalId || mediaData.id || mediaData.foreignBookId || 'detail'}`);
    const infoGrid = buildDetailInfoGrid([
        { label: 'Author', value: author },
        { label: 'Published', value: mediaData.releaseDate ? mediaData.releaseDate.substring(0, 10) : 'Unknown' },
        { label: 'Pages', value: mediaData.pageCount || 'Unknown' },
        { label: 'Added', value: addedDate },
        { label: 'Path', value: pathLabel, code: true, full: true }
    ]);

    // Bookmark info from localStorage (key matches epub reader's BM_KEY)
    const bmId   = internalId || mediaData.id;
    const bmCfi  = bmId ? localStorage.getItem(`epub_bm_${bmId}`) : null;
    const bmPage = bmId ? localStorage.getItem(`epub_bm_${bmId}_page`) : null;
    let bmBadge  = '';
    if (bmCfi) {
        const bmLabel = bmPage
            ? (() => { const [pg, total] = bmPage.split('/'); return `🔖 p.${pg} / ${total}`; })()
            : '🔖 Bookmarked';
        const bmTitle = bmPage
            ? (() => { const [pg, total] = bmPage.split('/'); return `Bookmarked at page ${pg} of ${total} — click to remove`; })()
            : 'Bookmarked — click to remove';
        bmBadge = `<button id="bmRemoveBtn"
            class="badge border-0 me-1 bookmark-remove-btn"
            data-bm-id="${bmId}"
            title="${bmTitle}"
            onclick="(function(){
                localStorage.removeItem('epub_bm_${bmId}');
                localStorage.removeItem('epub_bm_${bmId}_page');
                document.getElementById('bmRemoveBtn').remove();
                if (typeof applyBookmarkBadges === 'function') applyBookmarkBadges();
            })()">
            ${bmLabel}
        </button>`;
    }

    const html = `
        <section class="movie-detail movie-detail--book">
            <div class="movie-detail__hero">
                <img src="${backdropUrl}"
                     class="movie-detail__hero-bg"
                     alt="${mediaData.title}"
                     onerror="this.src='${posterUrl}'">
                <div class="movie-detail__hero-overlay"></div>
                <button type="button" class="movie-detail__back" data-bs-dismiss="modal" aria-label="Close">
                    <i class="fas fa-arrow-left"></i>
                </button>
            </div>

            <div class="movie-detail__sheet">
                <div class="movie-detail__summary">
                    <div class="movie-detail__poster-wrap">
                        <img src="${posterUrl}"
                             class="movie-detail__poster"
                             alt="${mediaData.title}"
                             onerror="this.src='/static/images/favicon.png'">
                    </div>
                    <div class="movie-detail__headline">
                        <div class="movie-detail__subtitle">${author}</div>
                        <h2 class="movie-detail__title">${mediaData.title || 'Unknown Title'}</h2>
                        <div class="movie-detail__meta-row">
                            <span>${releaseYear}</span>
                            ${pageCount ? `<span>${pageCount}</span>` : ''}
                            <span>${onDisk ? 'Downloaded' : 'Missing'}</span>
                        </div>
                    </div>
                </div>

                ${overviewSection}

                ${infoGrid}

                <div class="movie-detail__divider"></div>

                <div class="movie-detail__actions movie-detail__actions--book">
                    ${onDisk && mediaData.id ? `
                    <a href="/read/local/${mediaData.id}" target="_blank" class="movie-detail__action movie-detail__action--button movie-detail__action--book-primary" title="Read this book (${monitored ? 'Monitored' : 'Unmonitored'})">
                        <i class="fas fa-book-open me-2"></i>Read Now
                    </a>` : `
                    <div class="movie-detail__action movie-detail__action--stat movie-detail__action--book-primary movie-detail__action--stacked" title="Status: ${monitored ? 'Monitored' : 'Unmonitored'}">
                        <i class="fas ${onDisk ? 'fa-check-circle' : 'fa-exclamation-circle'} me-2"></i>
                        ${onDisk ? 'Ready to Read' : 'Not Downloaded'}
                    </div>`}
                    ${hasMetadataEditor ? `
                    <button type="button" class="movie-detail__action movie-detail__action--button" onclick="openBookMetadataEditorFromDetails()">
                        <i class="fas fa-pen-to-square me-2"></i>Edit Metadata
                    </button>` : ''}

                </div>

                ${bmBadge ? `<div class="movie-detail__bookmark-row">${bmBadge}</div>` : ''}


            </div>
        </section>
    `;

    detailsContent.innerHTML = html;
}

function openBookMetadataEditorFromDetails() {
    if (typeof window.triggerImport !== 'function') return;

    const modalEl = document.getElementById('detailsModal');
    const card = modalEl ? modalEl._bookCard : null;
    const directFilePath = modalEl?._bookFilePath || card?.dataset.filePath || '';
    const dbId = modalEl?._bookId || card?.dataset.dbId || null;

    if (directFilePath) {
        window.triggerImport(directFilePath, dbId);
        return;
    }

    if (!dbId) {
        console.warn('[openBookMetadataEditorFromDetails] No file path or DB ID available');
        return;
    }

    fetch(`/api/books/local/${dbId}`)
        .then(parseApiResponse)
        .then(({ ok, data }) => {
            if (!ok) throw new Error(data.error || 'Failed to load local book');
            const resolvedPath = data.file_path || data.path || '';
            if (!resolvedPath) {
                throw new Error('No local file path available');
            }
            window.triggerImport(resolvedPath, data.id || dbId);
        })
        .catch(error => {
            console.warn('[openBookMetadataEditorFromDetails] API failed:', error.message);

            // Fallback 1: try to use file path from card
            if (card?.dataset?.filePath) {
                console.log('[openBookMetadataEditorFromDetails] Falling back to card file path');
                window.triggerImport(card.dataset.filePath, dbId);
                return;
            }

            // Fallback 2: check if a file path exists in modal data
            const modalData = modalEl?.innerText || '';
            if (modalData) {
                console.log('[openBookMetadataEditorFromDetails] Checking for file path in modal...');
            }

            // If all else fails, show user message
            if (dbId) {
                alert('Could not locate book file. The book may have been moved or deleted. Please check that the file still exists in your library.');
            } else {
                alert('Could not identify the book. Please try clicking the book card again.');
            }
            console.error('[openBookMetadataEditorFromDetails] Could not resolve file path. DB ID:', dbId, 'Card:', !!card, 'Error:', error);
        });
}

function getDefaultMovieAddPrefs(mediaId) {
    const key = String(mediaId);
    if (!_addItemCache.movieAddPrefs[key]) {
        _addItemCache.movieAddPrefs[key] = {
            monitored: true,
            qualityProfileId: null,
            minimumAvailability: 'announced',
            rootFolderPath: '',
            collectionEnabled: false
        };
    }
    return _addItemCache.movieAddPrefs[key];
}

function fetchMovieAddOptions() {
    const qualityPromise = _addItemCache.qualityProfiles
        ? Promise.resolve(_addItemCache.qualityProfiles)
        : fetch('/api/radarr/qualityprofile')
            .then(res => res.json())
            .then(profiles => {
                _addItemCache.qualityProfiles = profiles;
                return profiles;
            });

    const rootFolderPromise = _addItemCache.rootFolders
        ? Promise.resolve(_addItemCache.rootFolders)
        : fetch('/api/radarr/rootfolders')
            .then(res => res.json())
            .then(folders => {
                _addItemCache.rootFolders = folders;
                return folders;
            });

    return Promise.all([qualityPromise, rootFolderPromise]);
}

function syncMovieAddPrefsFromUI(mediaId) {
    const prefs = getDefaultMovieAddPrefs(mediaId);
    const monitoredInput = document.getElementById(`movieAddMonitored_${mediaId}`);
    const qualitySelect = document.getElementById(`movieAddQuality_${mediaId}`);
    const availabilitySelect = document.getElementById(`movieAddAvailability_${mediaId}`);
    const rootFolderSelect = document.getElementById(`movieAddRootFolder_${mediaId}`);
    const collectionCheckbox = document.getElementById(`movieAddCollection_${mediaId}`);

    if (monitoredInput) prefs.monitored = monitoredInput.classList.contains('is-active');
    if (qualitySelect) prefs.qualityProfileId = qualitySelect.value ? parseInt(qualitySelect.value, 10) : null;
    if (availabilitySelect) prefs.minimumAvailability = availabilitySelect.value || 'announced';
    if (rootFolderSelect) prefs.rootFolderPath = rootFolderSelect.value || '';
    if (collectionCheckbox) prefs.collectionEnabled = collectionCheckbox.checked;

    return prefs;
}

function toggleMovieAddMonitor(mediaId, button) {
    button.classList.toggle('is-active');
    syncMovieAddPrefsFromUI(mediaId);
}

function initializeMovieAddOptions(mediaId, collectionName = '') {
    fetchMovieAddOptions()
        .then(([profiles, rootFolders]) => {
            const prefs = getDefaultMovieAddPrefs(mediaId);
            const qualitySelect = document.getElementById(`movieAddQuality_${mediaId}`);
            const availabilitySelect = document.getElementById(`movieAddAvailability_${mediaId}`);
            const rootFolderSelect = document.getElementById(`movieAddRootFolder_${mediaId}`);
            const collectionLabel = document.getElementById(`movieAddCollectionLabel_${mediaId}`);
            const collectionCheckbox = document.getElementById(`movieAddCollection_${mediaId}`);

            if (qualitySelect) {
                const defaultProfile = profiles.find(p => p.name === 'Any') || profiles.find(p => p.name === 'Default') || profiles[0];
                if (!prefs.qualityProfileId) prefs.qualityProfileId = defaultProfile?.id || null;
                qualitySelect.innerHTML = profiles.map(profile => `
                    <option value="${profile.id}" ${String(profile.id) === String(prefs.qualityProfileId) ? 'selected' : ''}>
                        ${profile.name}
                    </option>`).join('');
            }

            if (availabilitySelect) {
                availabilitySelect.value = prefs.minimumAvailability || 'announced';
            }

            if (rootFolderSelect) {
                const defaultFolder = rootFolders.find(folder => folder.path === prefs.rootFolderPath) || rootFolders[0];
                if (!prefs.rootFolderPath) prefs.rootFolderPath = defaultFolder?.path || '';
                rootFolderSelect.innerHTML = rootFolders.map(folder => {
                    const freeLabel = folder.freeSpace ? `(${formatFileSize(folder.freeSpace)} free)` : '';
                    return `<option value="${folder.path}" ${folder.path === prefs.rootFolderPath ? 'selected' : ''}>
                        ${folder.path} ${freeLabel}
                    </option>`;
                }).join('');
            }

            if (collectionLabel) {
                collectionLabel.textContent = collectionName
                    ? `Add the rest of the ${collectionName}?`
                    : 'Collection support coming soon';
            }

            if (collectionCheckbox) {
                collectionCheckbox.disabled = !collectionName;
                collectionCheckbox.checked = !!(collectionName && prefs.collectionEnabled);
            }

            syncMovieAddPrefsFromUI(mediaId);
        })
        .catch(error => {
            console.error('Failed to load movie add options:', error);
            const qualitySelect = document.getElementById(`movieAddQuality_${mediaId}`);
            const rootFolderSelect = document.getElementById(`movieAddRootFolder_${mediaId}`);
            if (qualitySelect) qualitySelect.innerHTML = '<option value="">Unavailable</option>';
            if (rootFolderSelect) rootFolderSelect.innerHTML = '<option value="">Unavailable</option>';
        });
}

function performConfiguredMovieAdd(mediaId, triggerSearch) {
    const prefs = syncMovieAddPrefsFromUI(mediaId);
    performAddFromModal('movie', mediaId, prefs.qualityProfileId, 'latest', {
        buttonId: triggerSearch ? 'modalSearchAddButton' : 'modalAddButton',
        rootFolderPath: prefs.rootFolderPath,
        minimumAvailability: prefs.minimumAvailability,
        monitored: prefs.monitored,
        searchForMovie: !!triggerSearch
    });
}


function renderMovieDetails(mediaData, fullData, mediaType, internalId, tmdbData = null) {
    const detailsContent = document.getElementById('detailsContent');
    const modalEl = document.getElementById('detailsModal');
    const homeContext = modalEl ? modalEl._homeLaunchContext : null;
    const modules = window.appModuleAvailability || {};
    const radarrAvailable = !!modules.radarr;
    const resolvedInternalId = internalId || mediaData.id || fullData.internal_id;

    const posterImage = mediaData.images?.find(img => img.coverType === 'poster');
    const backdropImage = mediaData.images?.find(img => img.coverType === 'fanart' || img.coverType === 'backdrop');
    const cachedPoster = homeContext?.posterSrc && !homeContext.posterSrc.includes('/static/images/placeholder.png')
        ? homeContext.posterSrc
        : '';
    const cachedBackdrop = homeContext?.backdropSrc && !homeContext.backdropSrc.includes('/static/images/placeholder.png')
        ? homeContext.backdropSrc
        : '';
    const posterUrl = cachedPoster || imgProxy(posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png', 320, 480, mediaData.title);
    const fallbackBackdrop = backdropImage?.remoteUrl || backdropImage?.url || '';
    const tmdbBackdrop = tmdbData?.backdrop_path ? `https://image.tmdb.org/t/p/original${tmdbData.backdrop_path}` : '';
    const backdropUrl = cachedBackdrop || cachedPoster || imgProxy(tmdbBackdrop || fallbackBackdrop || posterImage?.remoteUrl || posterImage?.url || '/static/images/apple-touch-icon.png', 1280, 720, mediaData.title);

    const runtime = mediaData.runtime ? `${Math.floor(mediaData.runtime / 60)}h ${mediaData.runtime % 60}m` : 'N/A';
    const fileSize = mediaData.sizeOnDisk ? formatFileSize(mediaData.sizeOnDisk) : 'N/A';
    const quality = mediaData.movieFile?.quality?.quality?.name || 'Unknown';
    const movieFile = mediaData.movieFile || {};
    const relativePath = movieFile.relativePath || 'No file downloaded';
    const ratingValue = mediaData.ratings?.value || tmdbData?.vote_average || null;
    const ratingLabel = ratingValue ? Number(ratingValue).toFixed(1) : null;
    const certification = mediaData.certification || mediaData.minimumAvailability || '';
    const imdbUrl = mediaData.imdbId ? `https://www.imdb.com/title/${mediaData.imdbId}/` : '';
    const studio = mediaData.studio || mediaData.originalStudio || 'Unknown';
    const overview = mediaData.overview || tmdbData?.overview || 'No overview available.';
    const genres = mediaData.genres || tmdbData?.genres || [];
    const addedDate = mediaData.added ? formatReadableDate(mediaData.added) : 'Unknown';
    const inCinemas = mediaData.inCinemas ? formatReadableDate(mediaData.inCinemas) : 'Unknown';
    const digitalRelease = mediaData.digitalRelease ? formatReadableDate(mediaData.digitalRelease) : 'Unknown';
    const physicalRelease = mediaData.physicalRelease ? formatReadableDate(mediaData.physicalRelease) : 'Unknown';
    const trailerKey = tmdbData?.trailer?.key || mediaData.youTubeTrailerId || null;
    const secondaryActionsId = `movieDetailActions_${resolvedInternalId || 'temp'}`;
    const hasMissing = !fullData.on_disk;
    const showSearchButtons = radarrAvailable && fullData.monitored && hasMissing;
    const overviewSection = buildDetailOverviewSection(overview, `movie_${resolvedInternalId || mediaData.tmdbId || mediaData.id || 'detail'}`);
    const infoGrid = buildDetailInfoGrid([
        { label: 'Studio', value: studio },
        { label: 'Added', value: addedDate },
        { label: 'Status', value: fullData.on_disk ? 'Downloaded' : (mediaData.status || 'Missing') },
        { label: 'Quality', value: quality },
        { label: 'Path', value: mediaData.path || 'N/A', code: true, full: true }
    ]);

    const html = `
        <section class="movie-detail">
            <div class="movie-detail__hero">
                <img src="${backdropUrl}"
                     class="movie-detail__hero-bg"
                     alt="${mediaData.title}"
                     onerror="this.src='${posterUrl}'">
                <div class="movie-detail__hero-overlay"></div>
                <button type="button" class="movie-detail__back" data-bs-dismiss="modal" aria-label="Close">
                    <i class="fas fa-arrow-left"></i>
                </button>
            </div>

            <div class="movie-detail__sheet">
                <div class="movie-detail__summary">
                    <div class="movie-detail__poster-wrap">
                        <img src="${posterUrl}"
                             class="movie-detail__poster"
                             alt="${mediaData.title}"
                             onerror="this.src='/static/images/favicon.png'">
                    </div>
                    <div class="movie-detail__headline">
                        ${certification ? `<span class="movie-detail__cert">${certification}</span>` : ''}
                        <h2 class="movie-detail__title">${mediaData.title || 'Unknown Title'}</h2>
                        <div class="movie-detail__meta-row">
                            ${ratingLabel ? `<span class="movie-detail__score">${ratingLabel} <i class="fas fa-star"></i></span>` : ''}
                            <span>${mediaData.year || 'N/A'}</span>
                            <span>${runtime}</span>
                        </div>
                    </div>
                </div>

                ${overviewSection}

                ${genres.length ? `
                <div class="movie-detail__genres">
                    ${genres.map(genre => `<span class="movie-detail__genre-chip">${typeof genre === 'string' ? genre : genre.name}</span>`).join('')}
                </div>` : ''}

                ${infoGrid}

                <div class="movie-detail__divider"></div>

                <div class="movie-detail__actions">
                    <button class="movie-detail__action movie-detail__action--icon monitor-toggle"
                            data-type="${mediaType}"
                            data-id="${resolvedInternalId}"
                            data-monitored="${fullData.monitored}"
                            data-has-missing="${hasMissing}"
                            title="${fullData.monitored ? 'Unmonitor' : 'Monitor'}">
                        <i class="fas fa-bookmark"></i>
                    </button>
                    <div class="movie-detail__action movie-detail__action--stat">${quality}</div>
                    ${showSearchButtons ? `
                    <button class="movie-detail__action movie-detail__action--button search-btn"
                            data-type="${mediaType}"
                            data-id="${resolvedInternalId}">
                        Search
                    </button>` : `
                    <div class="movie-detail__action movie-detail__action--stat">${fullData.on_disk ? 'Downloaded' : (mediaData.status || 'Missing')}</div>`}
                    ${imdbUrl ? `
                    <a class="movie-detail__action movie-detail__action--button"
                       href="${imdbUrl}"
                       target="_blank"
                       rel="noopener noreferrer">
                        IMDb
                    </a>` : `
                    <div class="movie-detail__action movie-detail__action--stat">Library</div>`}
                    <button class="movie-detail__action movie-detail__action--icon"
                            type="button"
                            aria-expanded="false"
                            aria-controls="${secondaryActionsId}"
                            onclick="toggleMovieDetailActions('${secondaryActionsId}', this)">
                        <i class="fas fa-ellipsis-vertical"></i>
                    </button>
                </div>

                <div class="movie-detail__secondary-actions" id="${secondaryActionsId}" hidden>
                    ${showSearchButtons ? `
                    <button class="btn btn-outline-info interactive-search-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-list me-2"></i>Choose Source
                    </button>` : ''}
                    ${homeContext && homeContext.plexId ? `
                    <button class="btn btn-outline-secondary"
                            type="button"
                            onclick="refreshMovieOnlineMatches()">
                        <i class="fas fa-link me-2"></i>Re-link Movie
                    </button>` : ''}
                    <button class="btn btn-outline-warning refresh-files-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-rotate me-2"></i>Refresh Files
                    </button>
                    <button class="btn btn-danger delete-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-trash me-2"></i>Delete
                    </button>
                </div>

                <div id="interactiveSearchContainer" class="card bg-dark border-secondary my-3 interactive-search-container">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h6 class="mb-0">RELEASES</h6>
                        <button class="btn btn-sm btn-outline-secondary" type="button"
                                onclick="hideInteractiveSearchResults()">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="card-body p-2" id="interactiveSearchResults">
                        <div class="text-center text-muted py-3">Loading releases...</div>
                    </div>
                </div>

                <div id="movieOnlineMatchContainer" class="card bg-dark border-secondary my-3 interactive-search-container movie-online-match-container-hidden">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h6 class="mb-0">MATCH MOVIE</h6>
                        <button class="btn btn-sm btn-outline-secondary" type="button"
                                onclick="hideMovieOnlineMatches()">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="card-body p-2" id="movieOnlineMatchResults">
                        <div class="text-center text-muted py-3">Loading matches...</div>
                    </div>
                </div>

                <div class="movie-detail__file-card">
                    <div class="movie-detail__file-row">
                        <div class="movie-detail__file-status ${fullData.on_disk ? 'is-present' : 'is-missing'}">
                            <i class="fas ${fullData.on_disk ? 'fa-circle-check' : 'fa-circle-xmark'}"></i>
                        </div>

                    </div>
                </div>

                <div class="movie-detail__release-grid">
                    <div>
                        <span class="movie-detail__release-label">Cinemas Release</span>
                        <strong class="movie-detail__release-value">${inCinemas}</strong>
                    </div>
                    <div>
                        <span class="movie-detail__release-label">Digital Release</span>
                        <strong class="movie-detail__release-value">${digitalRelease}</strong>
                    </div>
                    <div>
                        <span class="movie-detail__release-label">Physical Release</span>
                        <strong class="movie-detail__release-value">${physicalRelease}</strong>
                    </div>
                </div>

                ${buildDetailTrailerSection(trailerKey, mediaData.title || 'Movie')}
            </div>
        </section>
    `;
    
    detailsContent.innerHTML = html;
    
    // Add event listeners to the new buttons
    attachButtonEventListeners();
}

function formatReadableDate(value) {
    if (!value) return 'Unknown';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return 'Unknown';
    return parsed.toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
    });
}

function toggleMovieDetailActions(targetId, button) {
    const panel = document.getElementById(targetId);
    if (!panel) return;
    const willOpen = panel.hasAttribute('hidden');
    panel.toggleAttribute('hidden', !willOpen);
    if (button) {
        button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    }
}

function renderTVDetails(mediaData, fullData, mediaType, internalId, tmdbData = null) {
    const detailsContent = document.getElementById('detailsContent');
    const modalEl = document.getElementById('detailsModal');
    const homeContext = modalEl ? modalEl._homeLaunchContext : null;
    const modules = window.appModuleAvailability || {};
    const sonarrAvailable = !!modules.sonarr;
    const resolvedInternalId = internalId || mediaData.id || fullData.internal_id;
    
    const posterImage = mediaData.images?.find(img => img.coverType === 'poster');
    const backdropImage = mediaData.images?.find(img => img.coverType === 'fanart' || img.coverType === 'backdrop');
    const cachedPoster = homeContext?.posterSrc && !homeContext.posterSrc.includes('/static/images/placeholder.png')
        ? homeContext.posterSrc
        : '';
    const cachedBackdrop = homeContext?.backdropSrc && !homeContext.backdropSrc.includes('/static/images/placeholder.png')
        ? homeContext.backdropSrc
        : '';
    const posterUrl = cachedPoster || imgProxy(posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png', 300, 450, mediaData.title);
    const tmdbBackdrop = tmdbData?.backdrop_path ? `https://image.tmdb.org/t/p/original${tmdbData.backdrop_path}` : '';
    const backdropUrl = cachedBackdrop || cachedPoster || imgProxy(tmdbBackdrop || backdropImage?.remoteUrl || backdropImage?.url || posterImage?.remoteUrl || posterImage?.url || '/static/images/apple-touch-icon.png', 1280, 720, mediaData.title);
    const fileSize = mediaData.sizeOnDisk ? formatFileSize(mediaData.sizeOnDisk) : 'N/A';
    const quality = mediaData.seriesType || 'Standard';
    const stats = mediaData.statistics || {};
    const totalEpisodes = stats.episodeCount || 0;
    const downloadedEpisodes = stats.episodeFileCount || 0;
    const completionPercent = stats.percentOfEpisodes || 0;
    const ratingValue = mediaData.ratings?.value || tmdbData?.vote_average || null;
    const ratingLabel = ratingValue ? Number(ratingValue).toFixed(1) : null;
    const backdropTitle = mediaData.title || 'TV Show';
    const trailerKey = tmdbData?.trailer?.key || mediaData.youTubeTrailerId || null;
    const secondaryActionsId = `tvDetailActions_${resolvedInternalId || 'temp'}`;
    const network = mediaData.network || tmdbData?.networks?.[0]?.name || 'TV';
    const statusLabel = mediaData.status || tmdbData?.status || (downloadedEpisodes < totalEpisodes ? 'Missing' : 'Current');
    const hasMissing = downloadedEpisodes < totalEpisodes;
    const firstAired = mediaData.firstAired ? formatReadableDate(mediaData.firstAired) : 'Unknown';
    const lastInfo = mediaData.previousAiring ? formatReadableDate(mediaData.previousAiring) : (mediaData.added ? formatReadableDate(mediaData.added) : 'Unknown');
    const seasonsCount = stats.seasonCount || mediaData.seasons?.filter(season => season.seasonNumber > 0).length || 0;
    const overview = mediaData.overview || tmdbData?.overview || 'No overview available.';
    const genres = (tmdbData?.genres || mediaData.genres || []).map(genre => typeof genre === 'string' ? genre : genre.name);
    const overviewSection = buildDetailOverviewSection(overview, `tv_${resolvedInternalId || mediaData.tvdbId || mediaData.id || 'detail'}`);
    const infoGrid = buildDetailInfoGrid([
        { label: 'Network', value: network },
        { label: 'Series Type', value: quality },
        { label: 'Episodes', value: `${downloadedEpisodes}/${totalEpisodes}` },
        { label: 'Monitored', value: fullData.monitored ? 'Yes' : 'No' },
        { label: 'Path', value: mediaData.path || 'N/A', code: true, full: true }
    ]);
    
    const html = `
        <section class="movie-detail movie-detail--tv">
            <div class="movie-detail__hero">
                <img src="${backdropUrl}"
                     class="movie-detail__hero-bg"
                     alt="${backdropTitle}"
                     onerror="this.src='${posterUrl}'">
                <div class="movie-detail__hero-overlay"></div>
                <button type="button" class="movie-detail__back" data-bs-dismiss="modal" aria-label="Close">
                    <i class="fas fa-arrow-left"></i>
                </button>
            </div>

            <div class="movie-detail__sheet">
                <div class="movie-detail__summary">
                    <div class="movie-detail__poster-wrap">
                        <img src="${posterUrl}"
                             class="movie-detail__poster"
                             alt="${backdropTitle}"
                             onerror="this.src='/static/images/favicon.png'">
                    </div>
                    <div class="movie-detail__headline">
                        ${mediaData.certification ? `<span class="movie-detail__cert">${mediaData.certification}</span>` : ''}
                        <h2 class="movie-detail__title">${backdropTitle}</h2>
                        <div class="movie-detail__subtitle">${network}</div>
                        <div class="movie-detail__meta-row">
                            ${ratingLabel ? `<span class="movie-detail__score">${ratingLabel} <i class="fas fa-star"></i></span>` : ''}
                            <span>${mediaData.year || 'N/A'}</span>
                            <span>${seasonsCount} season${seasonsCount === 1 ? '' : 's'}</span>
                        </div>
                    </div>
                </div>

                ${overviewSection}

                ${genres.length ? `
                <div class="movie-detail__genres">
                    ${genres.map(genre => `<span class="movie-detail__genre-chip">${genre}</span>`).join('')}
                </div>` : ''}

                ${infoGrid}

                <div class="movie-detail__divider"></div>

                <div class="movie-detail__actions movie-detail__actions--tv">
                    <button class="movie-detail__action movie-detail__action--icon monitor-toggle"
                            data-type="${mediaType}"
                            data-id="${resolvedInternalId}"
                            data-monitored="${fullData.monitored}"
                            data-has-missing="${hasMissing}"
                            title="${fullData.monitored ? 'Unmonitor' : 'Monitor'}">
                        <i class="fas fa-bookmark"></i>
                    </button>
                    <div class="movie-detail__action movie-detail__action--stat">${quality}</div>
                    ${sonarrAvailable && fullData.monitored && hasMissing ? `
                    <button class="movie-detail__action movie-detail__action--button search-btn"
                            data-type="${mediaType}"
                            data-id="${resolvedInternalId}">
                        Search
                    </button>` : `
                    <div class="movie-detail__action movie-detail__action--stat">${fullData.on_disk ? 'Downloaded' : statusLabel}</div>`}
                    <div class="movie-detail__action movie-detail__action--stat">${downloadedEpisodes}/${totalEpisodes} eps</div>
                    <button class="movie-detail__action movie-detail__action--icon"
                            type="button"
                            aria-expanded="false"
                            aria-controls="${secondaryActionsId}"
                            onclick="toggleMovieDetailActions('${secondaryActionsId}', this)">
                        <i class="fas fa-ellipsis-vertical"></i>
                    </button>
                </div>

                <div class="movie-detail__secondary-actions" id="${secondaryActionsId}" hidden>
                    ${sonarrAvailable && fullData.monitored && hasMissing ? `
                    <button class="btn btn-outline-info interactive-search-btn"
                            data-type="${mediaType}"
                            data-id="${resolvedInternalId}">
                        <i class="fas fa-list me-2"></i>Choose Source
                    </button>` : ''}
                    ${homeContext && homeContext.plexId ? `
                    <button class="btn btn-outline-secondary"
                            type="button"
                            onclick="refreshTvOnlineMatches()">
                        <i class="fas fa-link me-2"></i>Re-link Show
                    </button>` : ''}
                    <button class="btn btn-outline-warning refresh-files-btn"
                            data-type="${mediaType}"
                            data-id="${resolvedInternalId}">
                        <i class="fas fa-rotate me-2"></i>Refresh Files
                    </button>
                    <button class="btn btn-danger delete-btn"
                            data-type="${mediaType}"
                            data-id="${resolvedInternalId}">
                        <i class="fas fa-trash me-2"></i>Delete
                    </button>
                </div>

                <div id="interactiveSearchContainer" class="card bg-dark border-secondary my-3 interactive-search-container">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h6 class="mb-0">RELEASES</h6>
                        <button class="btn btn-sm btn-outline-secondary" type="button"
                                onclick="hideInteractiveSearchResults()">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="card-body p-2" id="interactiveSearchResults">
                        <div class="text-center text-muted py-3">Loading releases...</div>
                    </div>
                </div>

                <div id="tvOnlineMatchContainer" class="card bg-dark border-secondary my-3 interactive-search-container tv-online-match-container-hidden">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h6 class="mb-0">MATCH SHOW</h6>
                        <button class="btn btn-sm btn-outline-secondary" type="button"
                                onclick="hideTvOnlineMatches()">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="card-body p-2" id="tvOnlineMatchResults">
                        <div class="text-center text-muted py-3">Loading matches...</div>
                    </div>
                </div>

                <div class="movie-detail__file-card">
                    <div class="movie-detail__file-row">
                        <div class="movie-detail__file-status ${fullData.on_disk ? 'is-present' : 'is-missing'}">
                            <i class="fas ${fullData.on_disk ? 'fa-circle-check' : 'fa-circle-xmark'}"></i>
                        </div>
                    </div>
                </div>

                <div class="movie-detail__release-grid">
                    <div>
                        <span class="movie-detail__release-label">First Aired</span>
                        <strong class="movie-detail__release-value">${firstAired}</strong>
                    </div>
                    <div>
                        <span class="movie-detail__release-label">Last Update</span>
                        <strong class="movie-detail__release-value">${lastInfo}</strong>
                    </div>
                    <div>
                        <span class="movie-detail__release-label">Status</span>
                        <strong class="movie-detail__release-value">${statusLabel}</strong>
                    </div>
                </div>

                <section class="movie-detail__section">
                    <h3 class="movie-detail__section-title">Seasons</h3>
                    <div class="seasons-container">
                        <div id="seasonsList">
                            <div class="text-center text-muted p-4">
                                <div class="spinner-border spinner-border-sm mb-2" role="status"></div>
                                <p class="mb-0">Loading episodes...</p>
                            </div>
                        </div>
                    </div>
                </section>

                ${buildDetailTrailerSection(trailerKey, backdropTitle)}
            </div>
        </section>
    `;
    
    detailsContent.innerHTML = html;

    detailsContent.querySelectorAll('.detail-progress-bar[data-progress]').forEach(bar => {
        bar.style.width = `${bar.dataset.progress || 0}%`;
    });

    // Add event listeners to the new buttons
    attachButtonEventListeners();
    loadTVShowEpisodes(resolvedInternalId);
}

// New function to load episodes for TV shows
function loadTVShowEpisodes(seriesId) {
    const seasonsList = document.getElementById('seasonsList');
    
    if (!seasonsList) {
        console.error('Required elements not found');
        return;
    }
    
    seasonsList.innerHTML = `
        <div class="text-center text-muted p-4">
            <div class="spinner-border spinner-border-sm mb-2" role="status"></div>
            <p class="mb-0">Loading episodes...</p>
        </div>`;
    
    fetch(`/api/series/${seriesId}/seasons`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch episodes');
            }
            return response.json();
        })
        .then(seasonsWithEpisodes => {
            renderSeasonCards(seasonsWithEpisodes);
        })
        .catch(error => {
            console.error('Error loading episodes:', error);
            seasonsList.innerHTML = `
                <div class="alert alert-danger">
                    Error loading episodes: ${error.message}
                    <button class="btn btn-sm btn-outline-danger ms-2" onclick="loadTVShowEpisodes(${seriesId})">Retry</button>
                </div>`;
        });
}

function hideInteractiveSearchResults() {
    const container = document.getElementById('interactiveSearchContainer');
    const results = document.getElementById('interactiveSearchResults');
    if (results) results.innerHTML = '';
    if (container) container.style.display = 'none';
}

function hideTvOnlineMatches() {
    const container = document.getElementById('tvOnlineMatchContainer');
    const results = document.getElementById('tvOnlineMatchResults');
    if (results) results.innerHTML = '';
    if (container) container.style.display = 'none';
}

function hideMovieOnlineMatches() {
    const container = document.getElementById('movieOnlineMatchContainer');
    const results = document.getElementById('movieOnlineMatchResults');
    if (results) results.innerHTML = '';
    if (container) container.style.display = 'none';
}

function hideBookOnlineMatches() {
    const container = document.getElementById('bookOnlineMatchContainer');
    const results = document.getElementById('bookOnlineMatchResults');
    if (results) results.innerHTML = '';
    if (container) container.style.display = 'none';
}

function renderTvOnlineMatches(results) {
    const container = document.getElementById('tvOnlineMatchContainer');
    const resultsEl = document.getElementById('tvOnlineMatchResults');
    if (!container || !resultsEl) return;

    if (!Array.isArray(results) || !results.length) {
        resultsEl.innerHTML = '<div class="text-muted text-center py-3">No matching shows found.</div>';
        container.style.display = 'block';
        return;
    }

    resultsEl.innerHTML = results.map(result => `
        <div class="border rounded p-2 mb-2">
            <div class="d-flex justify-content-between align-items-start gap-2">
                <div class="d-flex gap-2 flex-grow-1">
                    <img src="${result.poster || '/static/images/apple-touch-icon.png'}"
                         alt="${result.title || 'TV show'}"
                         class="tv-online-match-poster"
                         onerror="this.src='/static/images/apple-touch-icon.png'">
                    <div class="flex-grow-1 interactive-release-copy">
                        <div class="text-light fw-semibold">${result.title || 'Unknown show'}</div>
                        <div class="text-muted small">${result.year || 'Unknown year'}${result.status ? ` • ${result.status}` : ''}</div>
                        <div class="text-muted small">TVDB ${result.tvdbId}${result.sonarrId ? ` • Sonarr ${result.sonarrId}` : ''}</div>
                    </div>
                </div>
                <button class="btn btn-sm btn-primary flex-shrink-0"
                        data-tvdb="${String(result.tvdbId || '').replace(/"/g, '&quot;')}"
                        data-sonarr="${String(result.sonarrId || '').replace(/"/g, '&quot;')}"
                        data-title="${String(result.title || '').replace(/"/g, '&quot;')}"
                        data-year="${String(result.year || '').replace(/"/g, '&quot;')}"
                        data-poster="${String(result.poster || '').replace(/"/g, '&quot;')}"
                        onclick="applyTvOnlineMatch(this)">
                    Use Match
                </button>
            </div>
        </div>
    `).join('');
    container.style.display = 'block';
}

function renderMovieOnlineMatches(results) {
    const container = document.getElementById('movieOnlineMatchContainer');
    const resultsEl = document.getElementById('movieOnlineMatchResults');
    if (!container || !resultsEl) return;

    if (!Array.isArray(results) || !results.length) {
        resultsEl.innerHTML = '<div class="text-muted text-center py-3">No matching movies found.</div>';
        container.style.display = 'block';
        return;
    }

    resultsEl.innerHTML = results.map(result => `
        <div class="border rounded p-2 mb-2 bg-dark-subtle">
            <div class="d-flex justify-content-between align-items-start gap-2">
                <div class="d-flex gap-2 flex-grow-1">
                    <img src="${result.poster || '/static/images/apple-touch-icon.png'}"
                         alt="${result.title || 'Movie'}"
                         class="tv-online-match-poster"
                         onerror="this.src='/static/images/apple-touch-icon.png'">
                    <div class="flex-grow-1 interactive-release-copy">
                        <div class="text-light fw-semibold">${result.title || 'Unknown movie'}</div>
                        <div class="text-muted small">${result.year || 'Unknown year'}${result.status ? ` • ${result.status}` : ''}</div>
                        <div class="text-muted small">TMDB ${result.tmdbId}${result.radarrId ? ` • Radarr ${result.radarrId}` : ''}</div>
                    </div>
                </div>
                <button class="btn btn-sm btn-primary flex-shrink-0"
                        data-tmdb="${String(result.tmdbId || '').replace(/"/g, '&quot;')}"
                        data-title="${String(result.title || '').replace(/"/g, '&quot;')}"
                        data-year="${String(result.year || '').replace(/"/g, '&quot;')}"
                        data-poster="${String(result.poster || '').replace(/"/g, '&quot;')}"
                        onclick="applyMovieOnlineMatch(this)">
                    Use Match
                </button>
            </div>
        </div>
    `).join('');
    container.style.display = 'block';
}

function renderBookOnlineMatches(results) {
    const container = document.getElementById('bookOnlineMatchContainer');
    const resultsEl = document.getElementById('bookOnlineMatchResults');
    if (!container || !resultsEl) return;

    if (!Array.isArray(results) || !results.length) {
        resultsEl.innerHTML = '<div class="text-muted text-center py-3">No matching books found.</div>';
        container.style.display = 'block';
        return;
    }

    resultsEl.innerHTML = results.map((result, index) => `
        <div class="border rounded p-2 mb-2 bg-dark-subtle">
            <div class="d-flex justify-content-between align-items-start gap-2">
                <div class="d-flex gap-2 flex-grow-1">
                    <img src="${result.cover_preview_url || result.cover_url || '/static/images/apple-touch-icon.png'}"
                         alt="${result.title || 'Book'}"
                         class="tv-online-match-poster"
                         onerror="this.src='/static/images/apple-touch-icon.png'">
                    <div class="flex-grow-1 interactive-release-copy">
                        <div class="text-light fw-semibold">${result.title || 'Unknown book'}</div>
                        <div class="text-muted small">${result.author || 'Unknown author'}${result.year ? ` • ${result.year}` : ''}</div>
                        <div class="text-muted small">${result.source || 'Unknown source'}${result.genre_str ? ` • ${result.genre_str}` : ''}</div>
                    </div>
                </div>
                <button class="btn btn-sm btn-primary flex-shrink-0"
                        onclick="applyBookOnlineMatch(${index})">
                    Use Match
                </button>
            </div>
        </div>
    `).join('');
    window._bookOnlineMatchResults = results;
    container.style.display = 'block';
}

async function refreshTvOnlineMatches() {
    const modalEl = document.getElementById('detailsModal');
    const context = modalEl ? modalEl._homeLaunchContext : null;
    const container = document.getElementById('tvOnlineMatchContainer');
    const resultsEl = document.getElementById('tvOnlineMatchResults');
    if (!context || !context.plexId || !container || !resultsEl) return;

    resultsEl.innerHTML = '<div class="text-center text-muted py-3">Loading matches...</div>';
    container.style.display = 'block';

    try {
        const response = await fetch('/api/tv/search-online', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plex_id: context.plexId,
                title: context.plexTitle,
                year: context.plexYear
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to search library');
        }
        renderTvOnlineMatches(data.results || []);
    } catch (error) {
        resultsEl.innerHTML = `<div class="text-danger text-center py-3">${error.message}</div>`;
        container.style.display = 'block';
    }
}

async function refreshMovieOnlineMatches() {
    const modalEl = document.getElementById('detailsModal');
    const context = modalEl ? modalEl._homeLaunchContext : null;
    const container = document.getElementById('movieOnlineMatchContainer');
    const resultsEl = document.getElementById('movieOnlineMatchResults');
    if (!context || !context.plexId || !container || !resultsEl) return;

    resultsEl.innerHTML = '<div class="text-center text-muted py-3">Loading matches...</div>';
    container.style.display = 'block';

    try {
        const response = await fetch('/api/movie/search-online', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plex_id: context.plexId,
                title: context.plexTitle,
                year: context.plexYear
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to search library');
        }
        renderMovieOnlineMatches(data.results || []);
    } catch (error) {
        resultsEl.innerHTML = `<div class="text-danger text-center py-3">${error.message}</div>`;
        container.style.display = 'block';
    }
}

async function refreshBookOnlineMatches() {
    const modalEl = document.getElementById('detailsModal');
    const dbId = modalEl?._bookId || modalEl?._bookCard?.dataset?.dbId || null;
    const container = document.getElementById('bookOnlineMatchContainer');
    const resultsEl = document.getElementById('bookOnlineMatchResults');
    if (!dbId || !container || !resultsEl) return;

    resultsEl.innerHTML = '<div class="text-center text-muted py-3">Loading matches...</div>';
    container.style.display = 'block';

    try {
        const response = await fetch(`/api/books/search-online/${dbId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to search books');
        }
        renderBookOnlineMatches(data.results || []);
    } catch (error) {
        resultsEl.innerHTML = `<div class="text-danger text-center py-3">${error.message}</div>`;
        container.style.display = 'block';
    }
}

async function applyTvOnlineMatch(button) {
    const modalEl = document.getElementById('detailsModal');
    const context = modalEl ? modalEl._homeLaunchContext : null;
    if (!button || !context || !context.plexId) return;

    const tvdbId = button.dataset.tvdb;
    const sonarrId = button.dataset.sonarr;
    if (!tvdbId) return;

    try {
        const response = await fetch('/api/tv/rebind-plex', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plex_id: context.plexId,
                title: context.plexTitle,
                year: context.plexYear,
                tvdb_id: tvdbId,
                sonarr_id: sonarrId,
                poster: button.dataset.poster || '',
                matched_title: button.dataset.title || '',
                matched_year: button.dataset.year || ''
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to update linked show');
        }

        hideTvOnlineMatches();
        showManageDetails('tv', sonarrId || tvdbId, sonarrId || tvdbId, sonarrId ? 'sonarr' : '', context);
    } catch (error) {
        alert(error.message);
    }
}

async function applyMovieOnlineMatch(button) {
    const modalEl = document.getElementById('detailsModal');
    const context = modalEl ? modalEl._homeLaunchContext : null;
    if (!button || !context || !context.plexId) return;

    const tmdbId = button.dataset.tmdb;
    if (!tmdbId) return;

    try {
        const response = await fetch('/api/movie/rebind-plex', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                plex_id: context.plexId,
                title: context.plexTitle,
                year: context.plexYear,
                tmdb_id: tmdbId,
                poster: button.dataset.poster || '',
                matched_title: button.dataset.title || '',
                matched_year: button.dataset.year || ''
            })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to update linked movie');
        }

        hideMovieOnlineMatches();
        showManageDetails('movie', tmdbId, tmdbId, '', context);
    } catch (error) {
        alert(error.message);
    }
}

async function applyBookOnlineMatch(index) {
    const modalEl = document.getElementById('detailsModal');
    const dbId = modalEl?._bookId || modalEl?._bookCard?.dataset?.dbId || null;
    const matches = window._bookOnlineMatchResults || [];
    const match = matches[index];
    if (!dbId || !match) return;

    try {
        const response = await fetch(`/api/books/relink/${dbId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ match })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to update linked book');
        }

        hideBookOnlineMatches();
        if (modalEl?._bookCard && typeof patchBookCard === 'function') {
            patchBookCard(modalEl._bookCard, data.book);
        }
        if (typeof _renderBookDetailModal === 'function') {
            _renderBookDetailModal(data.book, modalEl?._bookCard || null);
        }
    } catch (error) {
        alert(error.message);
    }
}

function renderInteractiveSearchResults(mediaType, internalId, releases) {
    const container = document.getElementById('interactiveSearchContainer');
    const resultsEl = document.getElementById('interactiveSearchResults');
    if (!container || !resultsEl) return;

    if (!Array.isArray(releases) || !releases.length) {
        resultsEl.innerHTML = '<div class="text-muted text-center py-3">No releases found.</div>';
        container.style.display = 'block';
        return;
    }

    const sorted = releases.slice().sort((a, b) => (b.age || 0) - (a.age || 0));
    resultsEl.innerHTML = sorted.map((release, idx) => {
        const title = release.title || release.releaseTitle || 'Unknown release';
        const indexer = release.indexer || release.indexerName || 'Unknown source';
        const quality = release.quality?.quality?.name || release.quality?.name || release.quality || 'Unknown';
        const size = release.size ? formatFileSize(release.size) : 'Unknown size';
        const age = release.age ? `${release.age}d` : 'new';
        const protocol = (release.protocol || '').toUpperCase();
        const score = release.customFormatScore ?? release.rejections?.length ?? '';
        const info = [quality, size, protocol, age].filter(Boolean).join(' • ');
        return `
            <div class="border rounded p-2 mb-2 bg-dark-subtle">
                <div class="d-flex justify-content-between align-items-start gap-2">
                    <div class="flex-grow-1 interactive-release-copy">
                        <div class="text-light fw-semibold text-truncate" title="${title.replace(/"/g, '&quot;')}">${title}</div>
                        <div class="text-muted small">${indexer}</div>
                        <div class="text-muted small">${info}${score !== '' ? ` • score ${score}` : ''}</div>
                    </div>
                    <button class="btn btn-sm btn-primary flex-shrink-0"
                            onclick="grabInteractiveRelease('${mediaType}', ${internalId}, ${idx}, this)">
                        <i class="fas fa-download me-1"></i>Grab
                    </button>
                </div>
            </div>`;
    }).join('');
    window._interactiveReleaseResults = sorted;
    container.style.display = 'block';
}

function loadInteractiveSearchResults(mediaType, internalId, button) {
    const container = document.getElementById('interactiveSearchContainer');
    const resultsEl = document.getElementById('interactiveSearchResults');
    if (!container || !resultsEl) return;

    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
    container.style.display = 'block';
    resultsEl.innerHTML = '<div class="text-center text-muted py-3">Loading releases...</div>';

    fetch(`/api/${mediaType}/${internalId}/interactive-search`)
        .then(parseApiResponse)
        .then(({ ok, data }) => {
            if (!ok) throw new Error(data.error || 'Failed to load releases');
            renderInteractiveSearchResults(mediaType, internalId, data.results || []);
        })
        .catch(error => {
            console.error(error);
            resultsEl.innerHTML = `<div class="alert alert-danger mb-0">Failed to load releases: ${error.message}</div>`;
        })
        .finally(() => {
            button.disabled = false;
            button.innerHTML = originalHtml;
        });
}

function grabInteractiveRelease(mediaType, internalId, idx, button) {
    const releases = window._interactiveReleaseResults || [];
    const release = releases[idx];
    if (!release) return;

    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';

    fetch(`/api/${mediaType}/${internalId}/grab-release`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ release })
    })
    .then(parseApiResponse)
    .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || 'Failed to grab release');
        button.classList.remove('btn-primary');
        button.classList.add('btn-success');
        button.innerHTML = '<i class="fas fa-check me-1"></i>Queued';
        showNotification('Release queued successfully', 'success');
    })
    .catch(error => {
        console.error(error);
        button.classList.remove('btn-primary');
        button.classList.add('btn-danger');
        button.innerHTML = '<i class="fas fa-times me-1"></i>Failed';
        showNotification(`Failed to queue release: ${error.message}`, 'error');
        setTimeout(() => {
            button.classList.remove('btn-danger');
            button.classList.add('btn-primary');
            button.innerHTML = originalHtml;
            button.disabled = false;
        }, 1800);
    });
}

// Function to render season cards with episodes
function renderSeasonCards(seasonsWithEpisodes) {
    const container = document.getElementById('seasonsList');

    if (!container) {
        console.error('seasonsList container not found');
        return;
    }

    if (!seasonsWithEpisodes || seasonsWithEpisodes.length === 0) {
        container.innerHTML = '<div class="alert alert-warning">No episodes data available</div>';
        return;
    }

    // Sort seasons by season number
    seasonsWithEpisodes.sort((a, b) => a.seasonNumber - b.seasonNumber);

    const seasonsHtml = seasonsWithEpisodes.map((season, idx) => {
        const eps      = season.episodes || [];
        const total    = eps.length;
        const gotFiles = eps.filter(e => e.hasFile).length;
        const collapseId = `season-collapse-${season.seasonNumber}`;
        const headingId  = `season-heading-${season.seasonNumber}`;
        const label = season.seasonNumber === 0 ? 'Specials' : `Season ${season.seasonNumber}`;

        // Badge colour: green = complete, yellow = partial, secondary = 0
        const badgeCls = gotFiles === total && total > 0 ? 'bg-success'
                       : gotFiles > 0               ? 'bg-warning text-dark'
                       : 'bg-secondary';

        return `
            <div class="card season-card mb-2">
                <div class="card-header d-flex justify-content-between align-items-center season-card-toggle"
                     id="${headingId}"
                     data-bs-toggle="collapse"
                     data-bs-target="#${collapseId}"
                     aria-expanded="false"
                     aria-controls="${collapseId}">
                    <h6 class="mb-0">${label}</h6>
                    <span class="badge ${badgeCls} ms-auto">[${gotFiles}/${total}]</span>
                </div>
                <div id="${collapseId}" class="collapse" aria-labelledby="${headingId}">
                    <div class="card-body p-0">
                        <div class="episode-list">
                            ${total > 0 ?
                                eps.map(episode => {
                                    const epTitle = (episode.title && episode.title !== `Episode ${episode.episodeNumber}`)
                                        ? `<small class="text-muted d-block">${episode.title}</small>` : '';
                                    const actionBtn = episode.hasFile
                                        ? `<button class="btn btn-sm btn-danger delete-episode-btn"
                                               data-episode-id="${episode.id}"
                                               title="Delete episode file">
                                               <i class="fas fa-trash"></i>
                                           </button>`
                                        : `<button class="btn btn-sm btn-primary search-episode-btn"
                                               data-episode-id="${episode.id}"
                                               title="Search for episode">
                                               <i class="fas fa-search"></i>
                                           </button>`;
                                    return `
                                        <div class="episode-item d-flex justify-content-between align-items-center ${episode.hasFile ? 'downloaded' : 'missing'}">
                                            <div class="flex-grow-1">
                                                <div class="d-flex justify-content-between align-items-start">
                                                    <div>
                                                        <span class="episode-number">${episode.episodeNumber}</span>
                                                        <span class="episode-title">Episode ${episode.episodeNumber}</span>
                                                        ${epTitle}
                                                    </div>
                                                    <div class="episode-date">${formatEpisodeDate(episode.airDate)}</div>
                                                </div>
                                            </div>
                                            <div class="episode-actions ms-2">${actionBtn}</div>
                                        </div>`;
                                }).join('')
                                : '<div class="episode-item text-center p-2 text-muted">No episodes available</div>'
                            }
                        </div>
                    </div>
                </div>
            </div>`;
    }).join('');

    container.innerHTML = seasonsHtml;

    // Attach event listeners to the new buttons
    attachEpisodeEventListeners();
}

// Function to attach event listeners to episode action buttons
function attachEpisodeEventListeners() {
    // Search episode buttons
    document.querySelectorAll('.search-episode-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation(); // Prevent triggering parent click events
            const episodeId = this.getAttribute('data-episode-id');
            searchEpisode(episodeId, this);
        });
    });
    
    // Delete episode buttons
    document.querySelectorAll('.delete-episode-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation(); // Prevent triggering parent click events
            const episodeId = this.getAttribute('data-episode-id');
            deleteEpisode(episodeId, this);
        });
    });
}

// Function to search for an episode
function searchEpisode(episodeId, button) {
    const originalHtml = button.innerHTML;
    
    // Show loading state
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
    
    fetch(`/api/episode/${episodeId}/search`, {
        method: 'POST'
    })
    .then(response => {
        if (response.ok) {
            button.innerHTML = '<i class="fas fa-check text-success"></i>';
            setTimeout(() => {
                button.innerHTML = originalHtml;
                button.disabled = false;
            }, 2000);
        } else {
            throw new Error('Search failed');
        }
    })
    .catch(error => {
        console.error('Error searching episode:', error);
        button.innerHTML = '<i class="fas fa-times text-danger"></i>';
        setTimeout(() => {
            button.innerHTML = originalHtml;
            button.disabled = false;
        }, 2000);
    });
}

// Function to delete an episode file
function deleteEpisode(episodeId, button) {
    if (!confirm('Are you sure you want to delete this episode file?')) {
        return;
    }
    
    const originalHtml = button.innerHTML;
    
    // Show loading state
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
    
    fetch(`/api/episode/${episodeId}`, {
        method: 'DELETE'
    })
    .then(response => {
        if (response.ok) {
            button.innerHTML = '<i class="fas fa-check text-success"></i>';
            
            // Update the episode item to show it's now missing
            const episodeItem = button.closest('.episode-item');
            episodeItem.classList.remove('downloaded');
            episodeItem.classList.add('missing');
            
            // Replace delete button with search button
            setTimeout(() => {
                button.outerHTML = `
                    <button class="btn btn-sm btn-primary search-episode-btn" 
                        data-episode-id="${episodeId}"
                        title="Search for episode">
                        <i class="fas fa-search"></i>
                    </button>
                `;
                
                // Re-attach event listener to the new button
                attachEpisodeEventListeners();
            }, 1000);
        } else {
            throw new Error('Delete failed');
        }
    })
    .catch(error => {
        console.error('Error deleting episode:', error);
        button.innerHTML = '<i class="fas fa-times text-danger"></i>';
        setTimeout(() => {
            button.innerHTML = originalHtml;
            button.disabled = false;
        }, 2000);
    });
}

// Helper function to format episode dates
function formatEpisodeDate(dateString) {
    if (!dateString) return 'TBA';
    
    try {
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return 'Invalid Date';
        
        // Format as "Mon Day Year" (e.g., "Nov 5 2025")
        return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
    } catch (e) {
        return dateString; // Return original if formatting fails
    }
}

// Helper function to format file size
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// --- Show actions ---
document.getElementById('deleteShowBtn')?.addEventListener('click', () => {
  if (!currentShowId) return;
  if (confirm('Delete the entire show?')) {
    fetch(`/api/tv/${currentShowId}`, { method: 'DELETE' })
      .then(r => r.ok ? location.reload() : alert('Failed'));
  }
});

document.getElementById('deleteAllFilesBtn')?.addEventListener('click', () => {
  if (!currentShowId) return;
  if (confirm('Delete all files for this show?')) {
    fetch(`/api/tv/${currentShowId}/files`, { method: 'DELETE' })
      .then(r => r.ok ? alert('All files deleted') : alert('Failed'));
  }
});

document.getElementById('searchAllMissingBtn')?.addEventListener('click', () => {
  if (!currentShowId) return;
  fetch(`/api/tv/${currentShowId}/search_missing`, { method: 'POST' })
    .then(r => r.ok ? alert('Search started') : alert('Failed'));
});
function redirectToSearch(name, year) {
    let query = name;
    if (year) {
        query += ` (${year})`;
    }
    window.location.href = `/search?q=${encodeURIComponent(query)}`;
}

function renderSearchMovieAddDetails(mediaId, movieData, internalDataObj = null, addTargetAvailable = true) {
    const title = movieData.title || 'No Title';
    const overview = movieData.overview || 'No overview available';
    const year = movieData.year || 'N/A';
    const rating = movieData.rating && movieData.rating !== 'N/A' ? movieData.rating : null;
    const certification = movieData.certification || 'NR';
    const posterUrl = movieData.posterUrl || '/static/images/logo.png';
    const tmdbData = movieData.tmdbData || null;
    const backdropUrl = tmdbData?.backdrop_path
        ? imgProxy(`https://image.tmdb.org/t/p/original${tmdbData.backdrop_path}`, 1280, 720, title)
        : posterUrl;
    const trailerKey = tmdbData?.trailer?.key || null;
    const collectionName = tmdbData?.belongs_to_collection?.name || '';
    const monitoredDefault = true;
    getDefaultMovieAddPrefs(mediaId).monitored = monitoredDefault;

    return `
        <section class="movie-detail movie-detail--add">
            <div class="movie-detail__hero">
                <img src="${backdropUrl}" class="movie-detail__hero-bg" alt="${title}">
                <div class="movie-detail__hero-overlay"></div>
                <button type="button" class="movie-detail__back" data-bs-dismiss="modal" aria-label="Close">
                    <i class="fas fa-arrow-left"></i>
                </button>
            </div>

            <div class="movie-detail__sheet movie-detail__sheet--add">
                <div class="movie-detail__summary movie-detail__summary--compact">
                    <div class="movie-detail__poster-wrap">
                        <img src="${posterUrl}" class="movie-detail__poster" alt="${title}">
                    </div>
                    <div class="movie-detail__headline">
                        <span class="movie-detail__cert">${certification}</span>
                        <h2 class="movie-detail__title">${title}</h2>
                        <div class="movie-detail__meta-row">
                            <span>${year}</span>
                            ${rating ? `<span>${rating}</span>` : ''}
                        </div>
                    </div>
                </div>

                <div class="movie-add-panel">
                    <div class="movie-add-panel__grip" aria-hidden="true"></div>

                    <div class="movie-add-panel__header">
                        <div class="movie-add-panel__poster-wrap">
                            <img src="${posterUrl}" class="movie-add-panel__poster" alt="${title}">
                        </div>
                        <div class="movie-add-panel__headline">
                            <h3 class="movie-add-panel__title">${title}</h3>
                            <div class="movie-add-panel__meta">
                                <span>${year}</span>
                                ${rating ? `<span>&bull;</span><span>${rating}</span>` : ''}
                            </div>
                        </div>
                    </div>

                    <div class="movie-detail__divider"></div>

                    <div class="movie-add-panel__controls">
                        <button type="button"
                                id="movieAddMonitored_${mediaId}"
                                class="movie-add-control movie-add-control--icon is-active"
                                onclick="toggleMovieAddMonitor('${mediaId}', this)"
                                aria-label="Toggle monitoring">
                            <i class="fas fa-bookmark"></i>
                        </button>

                        <div class="movie-add-control movie-add-control--select">
                            <select id="movieAddQuality_${mediaId}" class="movie-add-control__select" onchange="syncMovieAddPrefsFromUI('${mediaId}')">
                                <option>Loading...</option>
                            </select>
                        </div>

                        <div class="movie-add-control movie-add-control--select">
                            <select id="movieAddAvailability_${mediaId}" class="movie-add-control__select" onchange="syncMovieAddPrefsFromUI('${mediaId}')">
                                <option value="announced">When announced</option>
                                <option value="inCinemas">In cinemas</option>
                                <option value="released">Released</option>
                                <option value="preDB">PreDB</option>
                            </select>
                        </div>

                        <div class="movie-add-control movie-add-control--icon movie-add-control--static">
                            <i class="fas fa-chevron-down"></i>
                        </div>
                    </div>

                    <label class="movie-add-panel__checkbox-row ${collectionName ? '' : 'is-disabled'}">
                        <span id="movieAddCollectionLabel_${mediaId}">${collectionName ? `Add the rest of the ${collectionName}?` : 'Collection support coming soon'}</span>
                        <input type="checkbox"
                               id="movieAddCollection_${mediaId}"
                               class="movie-add-panel__checkbox"
                               ${collectionName ? '' : 'disabled'}
                               onchange="syncMovieAddPrefsFromUI('${mediaId}')">
                    </label>

                    <div class="movie-add-panel__rootfolder">
                        <select id="movieAddRootFolder_${mediaId}" class="movie-add-panel__rootfolder-select" onchange="syncMovieAddPrefsFromUI('${mediaId}')">
                            <option>Loading folders...</option>
                        </select>
                    </div>

                    <div class="movie-add-panel__actions">
                        ${addTargetAvailable ? `
                        <button type="button"
                                class="btn movie-add-panel__button movie-add-panel__button--primary"
                                id="modalAddButton"
                                onclick="performConfiguredMovieAdd('${mediaId}', false)">
                            Add to Radarr
                        </button>
                        <button type="button"
                                class="btn movie-add-panel__button movie-add-panel__button--primary"
                                id="modalSearchAddButton"
                                onclick="performConfiguredMovieAdd('${mediaId}', true)">
                            Add + Search
                        </button>` : `
                        <div class="alert alert-warning mb-0 w-100">Radarr is not available.</div>`}
                    </div>
                </div>

                ${buildDetailTrailerSection(trailerKey, title)}
            </div>
        </section>`;
}

function showDetails(mediaType, mediaId, tmdb=false) {
    _pauseBackgroundFetches();
    const modules = window.appModuleAvailability || {};
    const modalEl = document.getElementById('detailsModal');
    const modal = new bootstrap.Modal(modalEl);
    const modalTitle = document.getElementById('detailsModalLabel');

    const overlay = document.getElementById('overlay-backdrop');
    overlay.style.display = 'block';

    // Clear any existing player
    if (player) {
        player.destroy();
        player = null;
    }
    currentTrailerKey = null;
    
    // Add modal hide event listener
    modalEl.addEventListener('hidden.bs.modal', function() {
        overlay.style.display = 'none';
        if (player) {
            player.stopVideo();
            player.destroy();
            player = null;
        }
        currentTrailerKey = null;
    }, { once: true });
            
    modalEl.removeAttribute('aria-hidden');
    setDetailsModalVariant(mediaType);
    modalTitle.textContent = `${mediaType === 'tv' ? 'TV Show' : mediaType === 'book' ? 'Book' : 'Movie'} Details`;
    
    document.getElementById('detailsContent').innerHTML = renderDetailLoadingSkeleton(mediaType);
    
    modal.show();
    
    // Only fetch internal data if NOT in TMDB-only mode
    const internalPromise = (tmdb === false || (tmdb === true && mediaType === 'tv'))
        ? fetch(`/get_media_details?type=${mediaType}&id=${mediaId}${tmdb === true && mediaType === 'tv' ? '&source=tmdb' : ''}`)
            .then(response => response.json())
            .catch(error => {
                console.error('Internal API error:', error);
                return { error: 'Failed to load internal details' };
            })
        : Promise.resolve(null); // Skip entirely when tmdb=true
    
    // Books are handled above and return early; this only runs for movies and TV.
    // For TV shows fetch TMDB enrichment; movies rely on internal Radarr data.
    const tmdbPromise = (mediaType === 'tv' || mediaType === 'movie')
        ? fetch(`/get_tmdb_details?type=${mediaType}&id=${mediaId}`)
            .then(response => response.json())
            .catch(error => {
                console.error('TMDB API error:', error);
                return null; // TMDB data is optional
            })
        : Promise.resolve(null);
    
    Promise.all([internalPromise, tmdbPromise])
        .then(([internalData, tmdbData]) => {
            console.log('Internal data:', internalData);
            console.log('TMDB data:', tmdbData);
            
            const hasTmdbData = tmdbData && !tmdbData.error;
            const hasInternalData = internalData && !internalData.error;

            // Books: render dedicated view using Readarr data only
            if (mediaType === 'book') {
                let bookData = null;
                let bookFullData = null;

                if (internalData && !internalData.error) {
                    // Fresh data from Readarr API — use it directly
                    bookData = internalData.data || internalData;
                    bookFullData = internalData;
                } else {
                    // API failed — fall back to the search-result cache populated by the template
                    const cached = (window.bookCache || new Map()).get(String(mediaId));
                    if (cached) {
                        console.warn('[showDetails] Readarr API failed; rendering from search cache for', mediaId);
                        bookData = cached;
                        bookFullData = { on_disk: false, monitored: false, status: 'not_added' };
                    }
                }

                if (bookData) {
                    renderBookDetails(bookData, bookFullData, mediaType, null);
                    // Append Add button if not in library
                    if (!bookFullData || bookFullData.status !== 'existing') {
                        const addDiv = document.createElement('div');
                        addDiv.className = 'movie-detail__section';
                        addDiv.innerHTML = `<button class="btn btn-primary w-100" onclick="addItemFromModal('book', ${mediaId})">
                            <i class="fas fa-book me-1"></i>Add to Readarr
                        </button>`;
                        const target = document.querySelector('#detailsContent .movie-detail__sheet');
                        (target || document.getElementById('detailsContent')).appendChild(addDiv);
                    }
                } else {
                    document.getElementById('detailsContent').innerHTML = '<div class="alert alert-warning">Book details not available. Check Readarr connection.</div>';
                }
                return;
            }

            // If in TMDB-only mode, use ONLY TMDB data
            if (tmdb === true && !hasInternalData) {
                // TMDB-ONLY MODE: Use only TMDB data
                const title = hasTmdbData ? tmdbData.title : 'No Title';
                const overview = hasTmdbData ? tmdbData.overview : 'No overview available';
                const year = hasTmdbData && tmdbData.first_air_date 
                    ? new Date(tmdbData.first_air_date).getFullYear() 
                    : 'N/A';
                const genres = hasTmdbData ? tmdbData.genres : [];
                const rating = hasTmdbData ? tmdbData.vote_average?.toFixed(1) : 'N/A';
                const status = hasTmdbData 
                    ? (tmdbData.status === 'Ended' ? 'Ended' : 'Current')
                    : 'Unknown';
                const certification = 'NR'; // Default for TMDB-only
                
                // POSTER: TMDB only
                let posterUrl = hasTmdbData && tmdbData.poster_path
                    ? imgProxy(`https://image.tmdb.org/t/p/original${tmdbData.poster_path}`, 300, 450, title)
                    : '/static/images/logo.png';

                const posterHtml = `
                    <img src="${posterUrl}"
                        class="img-fluid h-100 object-fit-cover tmdb-fallback-poster"
                        alt="${title} poster"
                        onerror="this.onerror=null; this.src='/static/images/logo.png'">`;

                // TRAILER: TMDB only
                let trailerHtml = '';
                let trailerKey = null;

                if (hasTmdbData) {
                    const trailer = tmdbData.trailer || 
                        (tmdbData.videos && tmdbData.videos.find(v => 
                            v.site === 'YouTube' && 
                            v.type === 'Trailer' &&
                            (v.official === true || tmdbData.trailer === null)
                        ));

                    if (trailer) {
                        trailerKey = trailer.key;
                        const isOfficial = trailer.official === true;
                        const trailerText = isOfficial ? 'Official trailer' : 'Trailer';
                        
                        trailerHtml = `
                            <div class="mt-4">
                                <h5>Trailer</h5>
                                <div class="ratio ratio-16x9">
                                    <iframe src="https://www.youtube.com/embed/${trailerKey}?rel=0&modestbranding=1" 
                                            frameborder="0" 
                                            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                                            allowfullscreen>
                                    </iframe>
                                </div>
                                <p class="small text-muted mt-2">${trailerText}</p>
                            </div>`;
                    }
                }

                // IMAGES: TMDB only
                let imagesHtml = '';
                const allImages = [];

                if (hasTmdbData && tmdbData.images) {
                    if (tmdbData.images.posters) {
                        tmdbData.images.posters.slice(0, 10).forEach(poster => {
                            allImages.push({
                                url: imgProxy(`https://image.tmdb.org/t/p/w342${poster.file_path}`, 150, 225),
                                fullUrl: `https://image.tmdb.org/t/p/original${poster.file_path}`,
                                type: 'poster'
                            });
                        });
                    }
                    if (tmdbData.images.backdrops) {
                        tmdbData.images.backdrops.slice(0, 10).forEach(backdrop => {
                            allImages.push({
                                url: imgProxy(`https://image.tmdb.org/t/p/w342${backdrop.file_path}`, 225, 127),
                                fullUrl: `https://image.tmdb.org/t/p/original${backdrop.file_path}`,
                                type: 'backdrop'
                            });
                        });
                    }
                }

                if (allImages.length > 0) {
                    imagesHtml = `
                    <div class="mt-4">
                        <h5>Gallery</h5>
                        <div class="row g-2 image-gallery">
                            ${allImages.slice(0, 20).map(image => `
                                <div class="col-4 col-md-3">
                                    <img src="${image.url}" 
                                        class="img-thumbnail cursor-pointer"
                                        onclick="showFullImage('${image.fullUrl || image.url}')"
                                        alt="${image.type} image"
                                        title="${image.type}">
                                </div>
                            `).join('')}
                        </div>
                    </div>`;
                }

                const addTargetAvailable = mediaType === 'tv' ? !!modules.sonarr : mediaType === 'book' ? !!modules.readarr : !!modules.radarr;
                const addTargetLabel = mediaType === 'tv' ? 'Sonarr' : mediaType === 'book' ? 'Readarr' : 'Radarr';

                if (mediaType === 'movie') {
                    const movieTmdbOnlyData = {
                        title,
                        year,
                        overview,
                        rating,
                        certification,
                        posterUrl,
                        tmdbData
                    };
                    document.getElementById('detailsContent').innerHTML = renderSearchMovieAddDetails(mediaId, movieTmdbOnlyData, null, addTargetAvailable);
                    initializeMovieAddOptions(mediaId, tmdbData?.belongs_to_collection?.name || '');
                    attachButtonEventListeners();
                    modal.show();
                    return;
                }

                // TMDB-ONLY HTML (no library status)
                const html = `
                    <div class="g-0">
                        <!-- Row 1: Poster and Basic Info -->
                        <div class="row details g-0 mb-4">
                            <!-- Column 1: Poster -->
                            <div class="px-2">
                                <img src="${posterUrl}" 
                                    class="poster img-fluid w-100 rounded" 
                                    alt="${title} poster"
                                    onerror="this.src='/static/images/placeholder.png'">
                            </div>
                            
                            <!-- Column 2: Title, Info, and Add Button -->
                            <div class="px-3">
                                <h1 class="display-6 mb-2 fw-bold">${title}</h1>
                                
                                <div class="d-flex align-items-center flex-wrap gap-3 mb-3">
                                    ${year ? `<span class="text-light">${year}</span>` : ''}
                                    <span class="certification-badge bg-dark text-white px-2 rounded">
                                        ${certification}
                                    </span>
                                    ${mediaType === 'tv' ? `
                                    <span class="certification-badge bg-dark text-white px-2 rounded">
                                        ${status}
                                    </span>` : ''}
                                    ${rating !== 'N/A' ? `
                                    <span class="text-light">⭐ ${rating}/10</span>` : ''}
                                </div>
                                
                                <div class="d-flex flex-wrap gap-2 mb-3">
                                    ${genres.slice(0, 4).map(genre => `
                                        <span class="badge bg-secondary">${genre}</span>
                                    `).join('')}
                                </div>
                                
                                <p class="mb-3 detail-overview-text">${overview}</p>

                                <div class="mt-3">
                                    ${addTargetAvailable ? `<button class="btn btn-primary w-100" 
                                            id="modalAddButton"
                                            onclick="addItemFromModal('${mediaType}', ${mediaId})">
                                        Add to ${addTargetLabel}
                                    </button>` : ''}
                                </div>
                            </div>
                        </div>
                        
                        <!-- Row 2: Trailer and Images (span both columns) -->
                        <div class=" g-0">
                                ${trailerHtml}
                                ${imagesHtml}
                        </div>
                    </div>`;
                
                document.getElementById('detailsContent').innerHTML = html;
                modal.show();
                
            } else {
                // NORMAL MODE: Use both TMDB and internal data with TMDB prioritized
                const internalDataObj = internalData.data || internalData;
                
                // Content: TMDB first, internal fallback
                const title = hasTmdbData ? tmdbData.title : internalDataObj.title || 'No Title';
                const overview = hasTmdbData ? tmdbData.overview : internalDataObj.overview || 'No overview available';
                const year = hasTmdbData && tmdbData.first_air_date 
                    ? new Date(tmdbData.first_air_date).getFullYear() 
                    : internalDataObj.year || 'N/A';
                const genres = hasTmdbData ? tmdbData.genres : (internalDataObj.genres || []);
                const rating = hasTmdbData 
                    ? tmdbData.vote_average?.toFixed(1) 
                    : (internalDataObj.ratings?.imdb?.value || internalDataObj.ratings?.tmdb?.value || 'N/A');
                const status = hasTmdbData 
                    ? (tmdbData.status === 'Ended' ? 'Ended' : 'Current')
                    : (internalDataObj.ended ? 'Ended' : 'Current');
                const certification = internalDataObj.certification || internalDataObj.mpaaRating || 'NR';
                
                // POSTER: TMDB first, then internal
                let posterUrl;
                if (hasTmdbData && tmdbData.poster_path && tmdb!==false) {
                    posterUrl = imgProxy(`https://image.tmdb.org/t/p/original${tmdbData.poster_path}`, 300, 450, title);
                } else if (internalDataObj.images) {
                    const posterImage = internalDataObj.images.find(img => img.coverType === 'poster');
                    posterUrl = imgProxy(posterImage?.remoteUrl || posterImage?.url, 300, 450, title);
                } else {
                    posterUrl = '/static/images/logo.png';
                }

                const posterHtml = `
                    <img src="${posterUrl}"
                        class="img-fluid h-100 object-fit-cover tmdb-fallback-poster"
                        alt="${title} poster"
                        onerror="this.onerror=null; this.src='/static/images/logo.png'">`;
                
                // TRAILER: TMDB first, then internal
                let trailerHtml = '';
                let trailerKey = null;

                if (hasTmdbData) {
                    const trailer = tmdbData.trailer || 
                        (tmdbData.videos && tmdbData.videos.find(v => 
                            v.site === 'YouTube' && 
                            v.type === 'Trailer' &&
                            (v.official === true || tmdbData.trailer === null)
                        ));

                    if (trailer) {
                        trailerKey = trailer.key;
                    }
                } else if (internalDataObj.youTubeTrailerId) {
                    trailerKey = internalDataObj.youTubeTrailerId;
                }
                        
                if (trailerKey) {
                    currentTrailerKey = trailerKey;
                    const isOfficial = hasTmdbData && trailerKey === (tmdbData.trailer?.key);
                    const trailerText = isOfficial ? 'Official trailer' : 'Trailer';
                    
                    trailerHtml = `
                        <div class="mt-4">
                            <h5>Trailer</h5>
                            <div class="ratio ratio-16x9">
                                <iframe src="https://www.youtube.com/embed/${trailerKey}?rel=0&modestbranding=1" 
                                        frameborder="0" 
                                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                                        allowfullscreen>
                                </iframe>
                            </div>
                            <p class="small text-muted mt-2">${trailerText}</p>
                        </div>`;
                }

                // IMAGES: Combine both sources
                let imagesHtml = '';
                const allImages = [];

                if (hasTmdbData && tmdbData.images) {
                    if (tmdbData.images.posters) {
                        tmdbData.images.posters.slice(0, 10).forEach(poster => {
                            allImages.push({
                                url: imgProxy(`https://image.tmdb.org/t/p/w342${poster.file_path}`, 150, 225),
                                fullUrl: `https://image.tmdb.org/t/p/original${poster.file_path}`,
                                type: 'poster'
                            });
                        });
                    }
                    if (tmdbData.images.backdrops) {
                        tmdbData.images.backdrops.slice(0, 10).forEach(backdrop => {
                            allImages.push({
                                url: imgProxy(`https://image.tmdb.org/t/p/w342${backdrop.file_path}`, 225, 127),
                                fullUrl: `https://image.tmdb.org/t/p/original${backdrop.file_path}`,
                                type: 'backdrop'
                            });
                        });
                    }
                }

                if (internalDataObj.images && internalDataObj.images.length > 0) {
                    internalDataObj.images.forEach(image => {
                        if (image.remoteUrl && !allImages.some(img => img.url === image.remoteUrl)) {
                            allImages.push({
                                url: image.remoteUrl,
                                fullUrl: image.remoteUrl,
                                type: image.coverType || 'unknown'
                            });
                        }
                    });
                }

                if (allImages.length > 0) {
                    imagesHtml = `
                    <div class="mt-4">
                        <h5>Gallery</h5>
                        <div class="row g-2 image-gallery">
                            ${allImages.slice(0, 20).map(image => `
                                <div class="col-4 col-md-3">
                                    <img src="${image.url}" 
                                        class="img-thumbnail cursor-pointer"
                                        onclick="showFullImage('${image.fullUrl || image.url}')"
                                        alt="${image.type} image"
                                        title="${image.type}">
                                </div>
                            `).join('')}
                        </div>
                    </div>`;
                }

                // LIBRARY STATUS: From internal data
                const alreadyAdded = internalData.status === 'existing';
                const onDisk = internalData.on_disk;
                const monitored = internalData.monitored;
                const seasonCount = internalDataObj.statistics?.seasonCount;
                const addTargetAvailable = mediaType === 'tv' ? !!modules.sonarr : mediaType === 'book' ? !!modules.readarr : !!modules.radarr;
                const addTargetLabel = mediaType === 'tv' ? 'Sonarr' : mediaType === 'book' ? 'Readarr' : 'Radarr';

                if (mediaType === 'movie' && alreadyAdded) {
                    renderMovieDetails(internalDataObj, internalData, mediaType, internalDataObj.id || internalData.internal_id, tmdbData);
                    modal.show();
                    return;
                }

                if (mediaType === 'tv' && alreadyAdded) {
                    renderTVDetails(internalDataObj, internalData, mediaType, internalDataObj.id || internalData.internal_id, tmdbData);
                    modal.show();
                    return;
                }

                if (mediaType === 'movie' && !alreadyAdded) {
                    const movieData = {
                        title,
                        year,
                        overview,
                        rating,
                        certification,
                        posterUrl,
                        tmdbData
                    };
                    document.getElementById('detailsContent').innerHTML = renderSearchMovieAddDetails(mediaId, movieData, internalDataObj, addTargetAvailable);
                    initializeMovieAddOptions(mediaId, tmdbData?.belongs_to_collection?.name || '');
                    attachButtonEventListeners();
                    modal.show();
                    return;
                }

                // NORMAL MODE HTML (with library status)
                const html = `
                    <div class="g-0">
                        <!-- Row 1: Poster and Basic Info -->
                        <div class="row details g-0 mb-4">
                            <!-- Column 1: Poster -->
                            <div class="px-2">
                                <img src="${posterUrl}" 
                                    class="poster img-fluid w-100 rounded" 
                                    alt="${title} poster"
                                    onerror="this.src='/static/images/placeholder.png'">
                            </div>
                            
                            <!-- Column 2: Title, Info, and Add Button -->
                            <div class="px-3">
                                <h1 class="display-6 mb-2 fw-bold">${title}</h1>
                                
                                <div class="d-flex align-items-center flex-wrap gap-3 mb-3">
                                    ${year ? `<span class="text-light">${year}</span>` : ''}
                                    <span class="certification-badge bg-dark text-white px-2 rounded">
                                        ${certification}
                                    </span>
                                    ${mediaType === 'tv' ? `
                                    <span class="certification-badge bg-dark text-white px-2 rounded">
                                        ${status}
                                    </span>` : ''}
                                    ${rating !== 'N/A' ? `
                                    <span class="text-light">⭐ ${rating}/10</span>` : ''}
                                </div>
                                
                                <div class="d-flex flex-wrap gap-2 mb-3">
                                    ${genres.slice(0, 4).map(genre => `
                                        <span class="badge bg-secondary">${genre}</span>
                                    `).join('')}
                                </div>
                                
                                <p class="mb-3 detail-overview-text">${overview}</p>
                                
                                <div class="d-flex flex-wrap gap-2 mb-3">
                                    ${seasonCount ? `
                                        <span class="badge bg-success">
                                            Seasons: ${seasonCount}
                                        </span>` : ''}
                                    <span class="badge ${alreadyAdded ? 'bg-success' : 'bg-warning'}">
                                        ${alreadyAdded ? 'In Library' : 'Not Added'}
                                    </span>
                                    ${onDisk !== undefined ? `
                                    <span class="badge ${onDisk ? 'bg-success' : 'bg-secondary'}">
                                        ${onDisk ? 'Downloaded' : 'Not Downloaded'}
                                    </span>` : ''}
                                </div>

                                <div class="mt-3">
                                    ${alreadyAdded
                                        ? `<a class="btn btn-success w-100" id="modalAddButton"
                                                href="/manage?open=${encodeURIComponent(internalData.internal_id || internalData.id || mediaId)}&type=${mediaType}">
                                               <i class="fas fa-external-link-alt me-1"></i>View in Library
                                           </a>`
                                        : addTargetAvailable ? `<button class="btn btn-primary w-100" id="modalAddButton"
                                                onclick="addItemFromModal('${mediaType}', ${mediaId})">
                                               Add to ${addTargetLabel}
                                           </button>` : ''
                                    }
                                </div>
                            </div>
                        </div>
                        
                        <!-- Row 2: Trailer and Images (span both columns) -->
                        <div class=" g-0">
                                ${trailerHtml}
                                ${imagesHtml}
                        </div>
                    </div>`;
                
                document.getElementById('detailsContent').innerHTML = html;
                modal.show();
            }
        })
        .catch(error => {
            console.error('Error:', error);
            document.getElementById('detailsContent').innerHTML = `
                <div class="alert alert-danger">
                    Error loading details: ${error.message}
                </div>`;
        });
}

function onYouTubeIframeAPIReady() {
    // This will be called when the API is ready
}

function renderEpisodes(episodes) {
    const container = document.getElementById('seasonsContainer');
    container.innerHTML = '';

    // Group episodes by season
    const grouped = {};
    episodes.forEach(ep => {
        if (!grouped[ep.seasonNumber]) grouped[ep.seasonNumber] = [];
        grouped[ep.seasonNumber].push(ep);
    });

    Object.keys(grouped).sort((a,b) => a-b).forEach(seasonNum => {
        const seasonDiv = document.createElement('div');
        seasonDiv.classList.add('mb-3');

        let seasonHtml = `<h5>Season ${seasonNum}</h5><ul class="list-group">`;

        grouped[seasonNum].forEach(ep => {
            let icon;
            if (ep.hasFile) {
                icon = '<i class="fas fa-check text-success"></i>';
            } else if (!ep.hasAired) {
                icon = '<i class="fas fa-clock text-warning"></i>';
            } else {
                icon = '<i class="fas fa-times text-danger"></i>';
            }

            seasonHtml += `
                <li class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        ${icon} S${ep.seasonNumber}E${ep.episodeNumber} - ${ep.title}
                    </div>
                    <div>
                        <button class="btn btn-sm btn-danger me-2" onclick="deleteEpisode(${ep.id})">
                            <i class="fas fa-trash"></i>
                        </button>
                        <button class="btn btn-sm btn-primary" onclick="searchEpisode(${ep.id})">
                            <i class="fas fa-search"></i>
                        </button>
                    </div>
                </li>`;
        });

        seasonHtml += '</ul>';
        seasonDiv.innerHTML = seasonHtml;
        container.appendChild(seasonDiv);
    });
}

function deleteEpisode(episodeId, button) {
    if (!confirm('Delete this episode file?')) return;
    const originalHtml = button ? button.innerHTML : null;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
    }
    fetch(`/api/episode/${episodeId}`, { method: 'DELETE' })
        .then(res => {
            if (!res.ok) throw new Error('Failed to delete episode');
            if (button) {
                const episodeItem = button.closest('.episode-item');
                if (episodeItem) {
                    episodeItem.classList.remove('downloaded');
                    episodeItem.classList.add('missing');
                }
                button.outerHTML = `
                    <button class="btn btn-sm btn-primary search-episode-btn"
                            data-episode-id="${episodeId}"
                            title="Search for episode">
                        <i class="fas fa-search"></i>
                    </button>`;
                attachEpisodeEventListeners();
            } else {
                location.reload();
            }
            showNotification('Episode deleted', 'success');
        })
        .catch(err => {
            console.error(err);
            if (button) {
                button.disabled = false;
                button.innerHTML = originalHtml;
            }
            showNotification('Failed to delete episode', 'error');
        });
}

function searchEpisode(episodeId, button) {
    const originalHtml = button ? button.innerHTML : null;
    if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
    }
    fetch(`/api/episode/${episodeId}/search`, { method: 'POST' })
        .then(res => {
            if (!res.ok) throw new Error('Search failed');
            showNotification('Episode search started', 'success');
            if (button) {
                button.innerHTML = '<i class="fas fa-check text-success"></i>';
                setTimeout(() => {
                    button.disabled = false;
                    button.innerHTML = originalHtml;
                }, 1600);
            }
        })
        .catch(err => {
            console.error(err);
            if (button) {
                button.disabled = false;
                button.innerHTML = originalHtml;
            }
            showNotification('Search failed', 'error');
        });
}

document.getElementById('deleteShowBtn')?.addEventListener('click', () => {
    if (confirm('Delete the entire show?')) {
        fetch(`/api/tv/${currentShowId}`, { method: 'DELETE' })
            .then(res => res.ok ? location.reload() : alert('Failed to delete show'));
    }
});

document.getElementById('deleteAllFilesBtn')?.addEventListener('click', () => {
    if (confirm('Delete all files for this show?')) {
        fetch(`/api/tv/${currentShowId}/files`, { method: 'DELETE' })
            .then(res => res.ok ? alert('All files deleted') : alert('Failed'));
    }
});

document.getElementById('searchAllMissingBtn')?.addEventListener('click', () => {
    fetch(`/api/tv/${currentShowId}/search_missing`, { method: 'POST' })
        .then(res => res.ok ? alert('Search started') : alert('Failed to search'));
});

function attachButtonEventListeners() {
  const modules = window.appModuleAvailability || {};
  document.querySelectorAll('.monitor-toggle').forEach(btn => {
    btn.onclick = function(e) {
      e.stopPropagation();
      const mediaType = this.dataset.type;
      const internalId = this.dataset.id;
      const monitored = !(this.dataset.monitored === 'true');
      const originalHtml = this.innerHTML;
      this.disabled = true;
      fetch(`/api/${mediaType}/${internalId}/monitor`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ monitored })
      })
      .then(response => response.json().then(data => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || 'Failed to update monitor status');
        this.dataset.monitored = monitored ? 'true' : 'false';
        this.className = `btn ${monitored ? 'btn-warning' : 'btn-success'} flex-fill monitor-toggle`;
        this.innerHTML = monitored ? 'Unmonitor' : 'Monitor';
        showNotification('Monitoring status updated', 'success');

        // Show or hide Auto Search / Choose Source based on new monitored state
        const hasMissing = this.dataset.hasMissing === 'true';
        const btnRow = this.closest('.d-flex.flex-wrap');
        if (btnRow) {
          // Remove existing search buttons
          btnRow.querySelectorAll('.search-btn, .interactive-search-btn').forEach(b => b.remove());
          // Inject if now monitored and content is missing
          const mType = this.dataset.type;
          const serviceAvailable = (mType === 'movie' && modules.radarr) || (mType === 'tv' && modules.sonarr);
          if (monitored && hasMissing && serviceAvailable) {
            const mId   = this.dataset.id;
            const deleteBtn = btnRow.querySelector('.delete-btn');
            const searchHtml =
              `<button class="btn btn-primary flex-fill search-btn" data-type="${mType}" data-id="${mId}">` +
                `<i class="fas fa-bolt me-1"></i> Auto Search` +
              `</button>` +
              `<button class="btn btn-outline-info flex-fill interactive-search-btn" data-type="${mType}" data-id="${mId}">` +
                `<i class="fas fa-list me-1"></i> Choose Source` +
              `</button>`;
            if (deleteBtn) {
              deleteBtn.insertAdjacentHTML('beforebegin', searchHtml);
            } else {
              btnRow.insertAdjacentHTML('beforeend', searchHtml);
            }
            attachButtonEventListeners();
          }
        }
      })
      .catch(error => {
        console.error(error);
        this.innerHTML = originalHtml;
        showNotification(error.message || 'Failed to update monitoring status', 'error');
      })
      .finally(() => {
        this.disabled = false;
      });
    };
  });

  document.querySelectorAll('.search-btn').forEach(btn => {
    btn.onclick = function(e) {
      e.stopPropagation();
      const mediaType = this.dataset.type;
      const internalId = this.dataset.id;
      const originalHtml = this.innerHTML;
      this.disabled = true;
      this.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
      fetch(`/api/${mediaType}/${internalId}/search`, { method: 'POST' })
        .then(parseApiResponse)
        .then(({ ok, data }) => {
          if (!ok) throw new Error(data.error || 'Failed to initiate search');
          showNotification('Automatic search started', 'success');
        })
        .catch(error => {
          console.error(error);
          showNotification(error.message || 'Failed to initiate search', 'error');
        })
        .finally(() => {
          this.disabled = false;
          this.innerHTML = originalHtml;
        });
    };
  });

  document.querySelectorAll('.interactive-search-btn').forEach(btn => {
    btn.onclick = function(e) {
      e.stopPropagation();
      loadInteractiveSearchResults(this.dataset.type, this.dataset.id, this);
    };
  });

  document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.onclick = function(e) {
      e.stopPropagation();
      if (!confirm('Are you sure you want to delete this from your library?')) return;
      const mediaType = this.dataset.type;
      const internalId = this.dataset.id;
      fetch(`/api/${mediaType}/${internalId}`, { method: 'DELETE' })
        .then(response => {
          if (!response.ok) throw new Error('Failed to delete item');
          showNotification('Item deleted successfully', 'success');
          window.location.reload();
        })
        .catch(error => {
          console.error(error);
          showNotification(error.message || 'Failed to delete item', 'error');
        });
    };
  });
}

    function addItemFromModal(mediaType, mediaId) {
        console.log(`[addItemFromModal] Adding ${mediaType} ID: ${mediaId}`);

        // For movies, show quality selection modal
        if (mediaType === 'movie') {
            showQualitySelectionModalFromDetails(mediaType, mediaId);
            return;
        }

        // For TV shows, show season selection modal
        if (mediaType === 'tv') {
            showSeasonSelectionModalFromDetails(mediaType, mediaId);
            return;
        }

        // For books, add directly
        performAddFromModal(mediaType, mediaId);
    }

    function showQualitySelectionModalFromDetails(mediaType, mediaId) {
        console.log('[showQualitySelectionModalFromDetails] Fetching quality profiles...');

        // Create quality selection modal if it doesn't exist
        let modal = document.getElementById('qualitySelectionDetailsModal');
        if (!modal) {
            const modalHtml = `
            <div class="modal fade" id="qualitySelectionDetailsModal" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content bg-dark border-secondary">
                        <div class="modal-header border-secondary">
                            <h5 class="modal-title">Select Quality Profile</h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div id="qualityProfilesDetailsContent" class="text-center">
                                <div class="spinner-border text-primary" role="status">
                                    <span class="visually-hidden">Loading...</span>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer border-secondary">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" onclick="performAddFromModalWithQuality()">Add</button>
                        </div>
                    </div>
                </div>
            </div>`;
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            modal = document.getElementById('qualitySelectionDetailsModal');
        }

        modal.dataset.mediaId = mediaId;

        // Fetch quality profiles if not cached
        if (!_addItemCache.qualityProfiles) {
            fetch('/api/radarr/qualityprofile')
                .then(res => res.json())
                .then(profiles => {
                    console.log('[showQualitySelectionModalFromDetails] Profiles:', profiles);
                    _addItemCache.qualityProfiles = profiles;
                    renderQualitySelectionForDetails(profiles, mediaId);
                })
                .catch(error => {
                    console.error('[showQualitySelectionModalFromDetails] Error:', error);
                    document.getElementById('qualityProfilesDetailsContent').innerHTML =
                        '<div class="alert alert-danger">Failed to load quality profiles</div>';
                });
        } else {
            renderQualitySelectionForDetails(_addItemCache.qualityProfiles, mediaId);
        }

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    function renderQualitySelectionForDetails(profiles, mediaId) {
        const content = document.getElementById('qualityProfilesDetailsContent');
        const defaultProfile = profiles.find(p => p.name === 'Default') || profiles[0];
        const defaultId = defaultProfile?.id || null;

        _addItemCache.selectedQuality[mediaId] = defaultId;

        const html = `
            <div class="mb-3">
                <label class="form-label">Quality Profile</label>
                <select id="qualityProfileDetailsSelect" class="form-select form-select-sm bg-secondary text-white" onchange="updateSelectedQualityDetails('${mediaId}')">
                    ${profiles.map(profile => `
                        <option value="${profile.id}" ${profile.id === defaultId ? 'selected' : ''}>
                            ${profile.name}
                        </option>
                    `).join('')}
                </select>
            </div>
            <small class="text-muted">
                Selected: <strong id="qualityNameDetails">${defaultProfile?.name || 'Default'}</strong>
            </small>
        `;
        content.innerHTML = html;
    }

    function updateSelectedQualityDetails(mediaId) {
        const select = document.getElementById('qualityProfileDetailsSelect');
        _addItemCache.selectedQuality[mediaId] = parseInt(select.value);
        const profile = _addItemCache.qualityProfiles.find(p => p.id === _addItemCache.selectedQuality[mediaId]);
        document.getElementById('qualityNameDetails').textContent = profile?.name || 'Unknown';
    }

    function showSeasonSelectionModalFromDetails(mediaType, mediaId) {
        console.log('[showSeasonSelectionModalFromDetails] Showing season selection...');

        // Create season selection modal if it doesn't exist
        let modal = document.getElementById('seasonSelectionDetailsModal');
        if (!modal) {
            const modalHtml = `
            <div class="modal fade" id="seasonSelectionDetailsModal" tabindex="-1" aria-hidden="true">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content bg-dark border-secondary">
                        <div class="modal-header border-secondary">
                            <h5 class="modal-title">Select Season(s) to Monitor</h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div id="seasonOptionsDetailsContent"></div>
                        </div>
                        <div class="modal-footer border-secondary">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" onclick="performAddFromModalWithSeason()">Add</button>
                        </div>
                    </div>
                </div>
            </div>`;
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            modal = document.getElementById('seasonSelectionDetailsModal');
        }

        modal.dataset.mediaId = mediaId;
        _addItemCache.selectedSeason[String(mediaId)] = 'latest'; // Default

        const html = `
            <div class="season-selection">
                <div class="form-check mb-2">
                    <input class="form-check-input" type="radio" name="seasonFilterDetails" value="latest" id="seasonLatestDetails" checked onchange="updateSelectedSeasonDetails('${mediaId}')">
                    <label class="form-check-label" for="seasonLatestDetails">
                        <strong>Latest Season</strong>
                        <small class="text-muted d-block">Monitor only the most recent season</small>
                    </label>
                </div>
                <div class="form-check mb-2">
                    <input class="form-check-input" type="radio" name="seasonFilterDetails" value="all" id="seasonAllDetails" onchange="updateSelectedSeasonDetails('${mediaId}')">
                    <label class="form-check-label" for="seasonAllDetails">
                        <strong>All Seasons</strong>
                        <small class="text-muted d-block">Monitor all seasons including past ones</small>
                    </label>
                </div>
                <div class="form-check">
                    <input class="form-check-input" type="radio" name="seasonFilterDetails" value="future" id="seasonFutureDetails" onchange="updateSelectedSeasonDetails('${mediaId}')">
                    <label class="form-check-label" for="seasonFutureDetails">
                        <strong>Future Seasons</strong>
                        <small class="text-muted d-block">Monitor only upcoming/unaired seasons</small>
                    </label>
                </div>
            </div>
        `;
        document.getElementById('seasonOptionsDetailsContent').innerHTML = html;

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    function updateSelectedSeasonDetails(mediaId) {
        const selected = document.querySelector('input[name="seasonFilterDetails"]:checked');
        _addItemCache.selectedSeason[String(mediaId)] = selected?.value || 'latest';
    }

    function performAddFromModalWithQuality() {
        const modal = document.getElementById('qualitySelectionDetailsModal');
        const mediaId = modal.dataset.mediaId;
        const qualityId = _addItemCache.selectedQuality[mediaId];
        performAddFromModal('movie', mediaId, qualityId);
        bootstrap.Modal.getInstance(modal).hide();
    }

    function performAddFromModalWithSeason() {
        const modal = document.getElementById('seasonSelectionDetailsModal');
        const mediaId = String(modal.dataset.mediaId);
        const seasonFilter = _addItemCache.selectedSeason[mediaId] || 'latest';
        performAddFromModal('tv', mediaId, null, seasonFilter);
        bootstrap.Modal.getInstance(modal).hide();
    }

    function performAddFromModal(mediaType, mediaId, qualityProfileId=null, seasonFilter='latest', extraOptions={}) {
        const btn = document.getElementById(extraOptions.buttonId || 'modalAddButton');
        if (!btn) {
            console.error('[performAddFromModal] target button not found');
            return;
        }
        const originalText = btn.innerHTML;

        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Adding...`;

        const payload = { media_type: mediaType, media_id: mediaId };
        if (qualityProfileId !== null && qualityProfileId !== undefined) {
            payload.quality_profile_id = qualityProfileId;
        }
        if (seasonFilter && mediaType === 'tv') {
            payload.season_filter = seasonFilter;
        }
        if (mediaType === 'movie') {
            payload.root_folder_path = extraOptions.rootFolderPath;
            payload.minimum_availability = extraOptions.minimumAvailability || 'announced';
            payload.monitored = extraOptions.monitored !== undefined ? extraOptions.monitored : true;
            payload.search_for_movie = extraOptions.searchForMovie !== undefined ? extraOptions.searchForMovie : false;
        }

        fetch('/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                btn.className = 'btn btn-success w-100';
                btn.innerHTML = '✓ Added Successfully';
                btn.disabled = true;
                updateStatusInCard(mediaType, mediaId);

                if (mediaType === 'movie') {
                    updateMovieAddButtonsAfterSuccess(mediaType, mediaId);
                }

                // Update button to "View in Library" after successful add
                setTimeout(() => {
                    updateModalButtonToViewInLibrary(btn, mediaType, mediaId);
                }, 1500);
            } else {
                btn.className = 'btn btn-danger w-100';
                btn.innerHTML = 'Error Adding';
                setTimeout(() => {
                    btn.className = 'btn btn-primary w-100';
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }, 3000);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            btn.className = 'btn btn-danger w-100';
            btn.innerHTML = 'Network Error';
            setTimeout(() => {
                btn.className = 'btn btn-primary w-100';
                btn.innerHTML = originalText;
                btn.disabled = false;
            }, 3000);
        });
    }

    function updateModalButtonToViewInLibrary(btn, mediaType, mediaId) {
        // Fetch the internal ID to link to the library entry
        fetch(`/get_media_details?type=${mediaType}&id=${mediaId}`)
            .then(response => response.json())
            .then(data => {
                const itemData = data.data || data;
                const internalId = itemData.id;

                // Update button to "View in Library" with link
                btn.className = 'btn btn-success w-100';
                btn.innerHTML = '<i class="fas fa-external-link-alt me-2"></i>View in Library';
                btn.disabled = false;
                btn.onclick = null;

                // Convert to a link that navigates to the library
                btn.href = `/manage?open=${encodeURIComponent(internalId)}&type=${mediaType}`;

                // If it's still a button element, we might want to wrap it or change behavior
                // For now, add event listener for click navigation
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    window.location.href = `/manage?open=${encodeURIComponent(internalId)}&type=${mediaType}`;
                });
            })
            .catch(error => {
                console.error('Error fetching media details:', error);
                // Fallback: just show a generic "View in Library" link
                btn.className = 'btn btn-success w-100';
                btn.innerHTML = '<i class="fas fa-external-link-alt me-2"></i>View in Library';
                btn.disabled = false;
                btn.href = `/manage?type=${mediaType}`;
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    window.location.href = `/manage?type=${mediaType}`;
                });
            });
    }

    function updateMovieAddButtonsAfterSuccess(mediaType, mediaId) {
        const secondaryBtn = document.getElementById('modalSearchAddButton');
        if (secondaryBtn) {
            secondaryBtn.disabled = true;
            secondaryBtn.textContent = 'Added';
            secondaryBtn.classList.add('movie-add-panel__button--secondary');
        }
    }

    function updateStatusInCard(mediaType, mediaId) {
    // Find the corresponding card and update its status
    document.querySelectorAll('.search-result-card').forEach(card => {
        if (card.dataset.mediaId == mediaId && card.dataset.mediaType == mediaType) {
            const badge = card.querySelector('.library-status-badge');
            if (badge) {
                badge.textContent = 'In Library';
                badge.className = 'library-status-badge badge bg-success';
            }
        }
    });
}

// Update functionality
function checkForUpdates() {
    const btn = document.getElementById('checkUpdateBtn');
    const originalHtml = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Checking...';
    
    fetch('/api/update/check')
        .then(response => response.json())
        .then(data => {
            if (data.update_available) {
                btn.innerHTML = '<i class="fas fa-exclamation-triangle text-warning me-2"></i>Update Available';
                document.getElementById('downloadUpdateBtn').style.display = 'block';
                showUpdateAvailableNotification(data);
            } else {
                btn.innerHTML = '<i class="fas fa-check text-success me-2"></i>Up to Date';
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                    btn.disabled = false;
                }, 3000);
            }
        })
        .catch(error => {
            console.error('Error checking for updates:', error);
            btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Check Failed';
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 3000);
        });
}

function downloadUpdate() {
    const btn = document.getElementById('downloadUpdateBtn');
    const originalHtml = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Downloading...';
    
    fetch('/api/update/download', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                btn.innerHTML = '<i class="fas fa-check text-success me-2"></i>Downloaded';
                showUpdateDownloadedNotification(data);
                
                // Auto-cleanup old updates after successful download
                cleanupUpdates();
                
                // Optionally auto-apply the update
                setTimeout(() => {
                    if (confirm('Update downloaded successfully! Would you like to apply it now?')) {
                        applyUpdate(data.version);
                    }
                }, 1000);
            } else {
                btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Download Failed';
                showToast('error', `Download failed: ${data.error}`);
            }
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 5000);
        })
        .catch(error => {
            console.error('Error downloading update:', error);
            btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Download Failed';
            showToast('error', 'Download failed');
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 3000);
        });
}

function applyUpdateSimple(version) {
    if (!confirm(`Apply update to version ${version}? The application will need to restart.`)) {
        return;
    }
    
    const btn = document.querySelector(`[data-version="${version}"]`) || document.getElementById('applyLatestUpdateBtn');
    const originalHtml = btn ? btn.innerHTML : 'Apply Update';
    
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Applying...';
    }
    
    fetch(`/api/update/apply-simple/${version}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('success', data.message);
                
                // Update the UI to reflect new version
                setTimeout(() => {
                    if (confirm('Update applied successfully! Restart the application now?')) {
                        location.reload();
                    }
                }, 1000);
            } else {
                showToast('error', `Apply failed: ${data.error}`);
            }
        })
        .catch(error => {
            console.error('Error applying update:', error);
            showToast('error', 'Apply failed');
        })
        .finally(() => {
            if (btn) {
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                    btn.disabled = false;
                }, 3000);
            }
        });
}

function showUpdateAvailableNotification(updateInfo) {
    // Create or update toast notification
    let toast = document.getElementById('updateAvailableToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'updateAvailableToast';
        toast.className = 'toast align-items-center text-white bg-warning border-0 position-fixed top-0 end-0 m-3';
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    <strong>Update Available!</strong> Version ${updateInfo.latest_version} is ready to download.
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        document.body.appendChild(toast);
    }
    
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
}

function showUpdateDownloadedNotification(downloadResult) {
    // Show success notification
    const toast = document.createElement('div');
    toast.className = 'toast align-items-center text-white bg-success border-0 position-fixed top-0 end-0 m-3';
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="fas fa-check-circle me-2"></i>
                <strong>Update Downloaded!</strong> Version ${downloadResult.version} has been downloaded. The update will be applied on next restart.
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    document.body.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Remove toast after it's hidden
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

// Check for update notification on page load
function checkUpdateNotification() {
    fetch('/api/update/status')
        .then(response => response.json())
        .then(data => {
            if (data.update_notification) {
                showUpdateAppliedNotification(data);
            }
        })
        .catch(error => console.error('Error checking update status:', error));
}

function showUpdateAppliedNotification(updateData) {
    // Check if Bootstrap is available
    if (typeof bootstrap === 'undefined') {
        console.warn('Bootstrap not available for update notification');
        alert(`arrdash has been updated to version ${updateData.latest_version}! Some changes may require a page refresh.`);
        
        // Dismiss the notification
        fetch('/api/update/dismiss', { method: 'POST' })
            .catch(error => console.error('Error dismissing update notification:', error));
        return;
    }

    const modalHtml = `
        <div class="modal fade" id="updateAppliedModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content bg-dark text-light">
                    <div class="modal-header border-secondary">
                        <h5 class="modal-title">
                            <i class="fas fa-check-circle me-2 text-success"></i>
                            Update Applied Successfully
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-success">
                            <h6 class="alert-heading">arrdash has been updated!</h6>
                            <p class="mb-0">The application has been updated to version <strong>${updateData.latest_version}</strong>.</p>
                        </div>
                        <p class="mb-0">Some changes may require a page refresh to take effect.</p>
                    </div>
                    <div class="modal-footer border-secondary">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        <button type="button" class="btn btn-primary" onclick="location.reload()">
                            <i class="fas fa-sync-alt me-1"></i> Refresh Page
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = new bootstrap.Modal(document.getElementById('updateAppliedModal'));
    
    // Auto-close after 8 seconds if user doesn't interact
    const autoCloseTimer = setTimeout(() => {
        const modalInstance = bootstrap.Modal.getInstance(document.getElementById('updateAppliedModal'));
        if (modalInstance) {
            modalInstance.hide();
        }
    }, 8000);
    
    modal.show();
    
    // Dismiss the notification so it doesn't show again
    fetch('/api/update/dismiss', { method: 'POST' })
        .catch(error => console.error('Error dismissing update notification:', error));
    
    // Remove modal from DOM when hidden and clear timer
    document.getElementById('updateAppliedModal').addEventListener('hidden.bs.modal', function() {
        clearTimeout(autoCloseTimer);
        this.remove();
    });
}

// Add event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Check for update notification
    checkUpdateNotification();
    
    // Add update button event listeners
    const checkUpdateBtn = document.getElementById('checkUpdateBtn');
    const downloadUpdateBtn = document.getElementById('downloadUpdateBtn');
    
    if (checkUpdateBtn) {
        checkUpdateBtn.addEventListener('click', checkForUpdates);
    }
    
    if (downloadUpdateBtn) {
        downloadUpdateBtn.addEventListener('click', downloadUpdate);
    }
});

function listDownloadedUpdates() {
    fetch('/api/update/list')
        .then(response => response.json())
        .then(data => {
            if (typeof closeConfigDrawer === 'function') {
                closeConfigDrawer();
            } else {
                const configPanel = document.getElementById('configModal');
                if (configPanel) {
                    configPanel.dataset.open = 'false';
                    configPanel.setAttribute('aria-hidden', 'true');
                }
                document.body.classList.remove('settings-drawer-open');
            }
            showDownloadedUpdatesList(data.updates);
        })
        .catch(error => {
            console.error('Error listing updates:', error);
        });
}

function cleanupUpdates() {
    fetch('/api/update/cleanup', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showToast('error', `Cleanup failed: ${data.error}`);
            } else {
                showToast('success', `Cleaned up ${data.deleted} old updates, kept ${data.kept}`);
                // Close the modal after successful cleanup
                const modal = bootstrap.Modal.getInstance(document.getElementById('updatesListModal'));
                if (modal) {
                    modal.hide();
                }
                // Refresh the updates list if needed
                setTimeout(() => {
                    listDownloadedUpdates();
                }, 1000);
            }
        })
        .catch(error => {
            console.error('Error cleaning up updates:', error);
            showToast('error', 'Cleanup failed');
        });
}

function showDownloadedUpdatesList(updates) {
    const modalHtml = `
        <div class="modal fade" id="updatesListModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-download me-2"></i>
                            Downloaded Updates
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        ${updates.length === 0 ? 
                            '<div class="text-center text-muted p-4"><i class="fas fa-inbox fa-3x mb-3"></i><p>No updates downloaded yet</p></div>' :
                            `
                            <div class="table-responsive">
                                <table class="table table-dark table-hover">
                                    <thead>
                                        <tr>
                                            <th>Version</th>
                                            <th>Size</th>
                                            <th>Downloaded</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${updates.map(update => `
                                            <tr>
                                                <td><strong>${update.version}</strong></td>
                                                <td>${update.formatted_size}</td>
                                                <td>${update.formatted_date}</td>
                                                <td>
                                                    <div class="btn-group btn-group-sm">
                                                        <button class="btn btn-outline-success" 
                                                                onclick="applyUpdateSimple('${update.version}')" 
                                                                data-version="${update.version}"
                                                                title="Apply Update">
                                                            <i class="fas fa-play"></i> Apply
                                                        </button>
                                                        <button class="btn btn-outline-danger" 
                                                                onclick="deleteUpdate('${update.version}')" 
                                                                title="Delete Update">
                                                            <i class="fas fa-trash"></i>
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                            <div class="mt-3">
                                <button class="btn btn-success me-2" id="applyLatestUpdateBtn" 
                                        onclick="applyUpdateSimple('${updates[0].version}')">
                                    <i class="fas fa-bolt me-1"></i>Apply Latest Update (${updates[0].version})
                                </button>
                                <button class="btn btn-outline-warning" onclick="cleanupUpdates()">
                                    <i class="fas fa-broom me-1"></i>Clean Up Old Updates (Keep 3)
                                </button>
                            </div>
                            `
                        }
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = new bootstrap.Modal(document.getElementById('updatesListModal'));
    modal.show();
    
    // Remove modal from DOM when hidden
    document.getElementById('updatesListModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}

function deleteUpdate(version) {
    if (!confirm(`Are you sure you want to delete update ${version}?`)) {
        return;
    }
    
    fetch(`/api/update/delete/${version}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('success', `Deleted update ${version}`);
                // Refresh the updates list
                setTimeout(() => {
                    const modal = bootstrap.Modal.getInstance(document.getElementById('updatesListModal'));
                    if (modal) {
                        modal.hide();
                    }
                    listDownloadedUpdates();
                }, 1000);
            } else {
                showToast('error', `Failed to delete: ${data.error}`);
            }
        })
        .catch(error => {
            console.error('Error deleting update:', error);
            showToast('error', 'Failed to delete update');
        });
}

function cleanupUpdates() {
    fetch('/api/update/cleanup', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showToast('error', `Cleanup failed: ${data.error}`);
            } else {
                showToast('success', `Cleaned up ${data.deleted} old updates, kept ${data.kept}`);
                // Refresh the updates list
                setTimeout(() => {
                    const modal = bootstrap.Modal.getInstance(document.getElementById('updatesListModal'));
                    if (modal) {
                        modal.hide();
                    }
                    listDownloadedUpdates();
                }, 1000);
            }
        })
        .catch(error => {
            console.error('Error cleaning up updates:', error);
            showToast('error', 'Cleanup failed');
        });
}

function showToast(type, message) {
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type === 'success' ? 'success' : 'danger'} border-0 position-fixed top-0 end-0 m-3`;
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                <i class="fas fa-${type === 'success' ? 'check' : 'exclamation-triangle'} me-2"></i>
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    document.body.appendChild(toast);
    
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Remove toast after it's hidden
    toast.addEventListener('hidden.bs.toast', () => {
        toast.remove();
    });
}

// Update the existing downloadUpdate function to show file info
function downloadUpdate() {
    const btn = document.getElementById('downloadUpdateBtn');
    const originalHtml = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Downloading...';
    
    fetch('/api/update/download', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                btn.innerHTML = '<i class="fas fa-check text-success me-2"></i>Downloaded';
                showUpdateDownloadedNotification(data);
                // Auto-cleanup old updates after successful download
                cleanupUpdates();
            } else {
                btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Download Failed';
                showToast('error', `Download failed: ${data.error}`);
            }
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 5000);
        })
        .catch(error => {
            console.error('Error downloading update:', error);
            btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Download Failed';
            showToast('error', 'Download failed');
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 3000);
        });
}

// Update the existing checkForUpdates function to include list button
function checkForUpdates() {
    const btn = document.getElementById('checkUpdateBtn');
    const originalHtml = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Checking...';
    
    fetch('/api/update/check')
        .then(response => response.json())
        .then(data => {
            if (data.update_available) {
                btn.innerHTML = '<i class="fas fa-exclamation-triangle text-warning me-2"></i>Update Available';
                document.getElementById('downloadUpdateBtn').style.display = 'block';
                showUpdateAvailableNotification(data);
            } else {
                btn.innerHTML = '<i class="fas fa-check text-success me-2"></i>Up to Date';
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                    btn.disabled = false;
                }, 3000);
            }
        })
        .catch(error => {
            console.error('Error checking for updates:', error);
            btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Check Failed';
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 3000);
        });
}

// Add event listeners when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Check for update notification
    checkUpdateNotification();
    
    const backToTopBtn = document.getElementById('backToTop');
    
    // Show/hide back to top button based on scroll position
    window.addEventListener('scroll', function() {
        if (window.pageYOffset > 300) {
            backToTopBtn.classList.add('show');
        } else {
            backToTopBtn.classList.remove('show');
        }
    });
    
    // Smooth scroll to top when clicked
    backToTopBtn.addEventListener('click', function() {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });
    
    // Add update button event listeners
    const checkUpdateBtn = document.getElementById('checkUpdateBtn');
    const downloadUpdateBtn = document.getElementById('downloadUpdateBtn');
    const listUpdatesBtn = document.getElementById('listUpdatesBtn');
    
    if (checkUpdateBtn) {
        checkUpdateBtn.addEventListener('click', checkForUpdates);
    }
    
    if (downloadUpdateBtn) {
        downloadUpdateBtn.addEventListener('click', downloadUpdate);
    }
    
    if (listUpdatesBtn) {
        listUpdatesBtn.addEventListener('click', listDownloadedUpdates);
    }
});
function applyUpdate(version) {
  const btn = document.querySelector(`[data-version="${version}"]`) || 
              document.getElementById('applyUpdateBtn');
  
  let originalHtml = 'Apply';
  if (btn) {
    originalHtml = btn.innerHTML;
    btn.innerHTML = 'Applying...';
    btn.disabled = true;
  }

  fetch(`/api/update/apply/${version}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    }
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      showNotification(data.message, 'success');
      // Auto-refresh after delay to see updated version
      setTimeout(() => {
        window.location.reload();
      }, 5000);
    } else {
      showNotification(`Update failed: ${data.error}`, 'error');
      if (btn) {
        btn.innerHTML = 'Apply Failed';
        setTimeout(() => {
          btn.innerHTML = originalHtml;
          btn.disabled = false;
        }, 3000);
      }
    }
  })
  .catch(error => {
    console.error('Error applying update:', error);
    showNotification(`Update failed: ${error.message}`, 'error');
    if (btn) {
      btn.innerHTML = 'Apply Failed';
      setTimeout(() => {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
      }, 3000);
    }
  });
}

function applyLatestUpdate() {
    const btn = document.getElementById('applyLatestUpdateBtn');
    const originalHtml = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Applying...';
    
    fetch('/api/update/apply-latest', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                btn.innerHTML = '<i class="fas fa-check text-success me-2"></i>Applied Successfully';
                showUpdateAppliedNotification(data);
                
                // Offer to restart the application
                setTimeout(() => {
                    if (confirm('Update applied successfully! Restart the application to complete the update?')) {
                        restartApplication();
                    }
                }, 2000);
            } else {
                btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Apply Failed';
                showToast('error', `Apply failed: ${data.error}`);
            }
        })
        .catch(error => {
            console.error('Error applying update:', error);
            btn.innerHTML = '<i class="fas fa-times text-danger me-2"></i>Apply Failed';
            showToast('error', 'Apply failed');
        })
        .finally(() => {
            setTimeout(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            }, 5000);
        });
}

function restartApplication() {
    if (!confirm('Are you sure you want to restart the application? This will interrupt any ongoing operations.')) {
        return;
    }
    
    fetch('/api/update/restart', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('success', 'Application is restarting...');
                // The page will reload when the app restarts
                setTimeout(() => {
                    window.location.reload();
                }, 3000);
            } else {
                showToast('error', `Restart failed: ${data.error}`);
            }
        })
        .catch(error => {
            console.error('Error restarting application:', error);
            showToast('error', 'Restart failed');
        });
}

function extractUpdate(version) {
    fetch(`/api/update/extract/${version}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('success', `Update ${version} extracted successfully`);
            } else {
                showToast('error', `Extraction failed: ${data.error}`);
            }
        })
        .catch(error => {
            console.error('Error extracting update:', error);
            showToast('error', 'Extraction failed');
        });
}

function showDownloadedUpdatesList(updates) {
    const modalHtml = `
        <div class="modal fade" id="updatesListModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-download me-2"></i>
                            Downloaded Updates
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        ${updates.length === 0 ? 
                            '<div class="text-center text-muted p-4"><i class="fas fa-inbox fa-3x mb-3"></i><p>No updates downloaded yet</p></div>' :
                            `
                            <div class="table-responsive">
                                <table class="table table-dark table-hover">
                                    <thead>
                                        <tr>
                                            <th>Version</th>
                                            <th>Size</th>
                                            <th>Downloaded</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${updates.map(update => `
                                            <tr>
                                                <td><strong>${update.version}</strong></td>
                                                <td>${update.formatted_size}</td>
                                                <td>${update.formatted_date}</td>
                                                <td>
                                                    <div class="btn-group btn-group-sm">
                                                        <button class="btn btn-outline-success" onclick="applyUpdate('${update.version}')" title="Apply Update">
                                                            <i class="fas fa-play"></i>
                                                        </button>
                                                        <button class="btn btn-outline-danger" onclick="deleteUpdate('${update.version}')" title="Delete Update">
                                                            <i class="fas fa-trash"></i>
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                            <div class="mt-3">
                                <button class="btn btn-success me-2" id="applyLatestUpdateBtn" onclick="applyLatestUpdate()">
                                    <i class="fas fa-bolt me-1"></i>Apply Latest Update
                                </button>
                                <button class="btn btn-outline-warning" onclick="cleanupUpdates()">
                                    <i class="fas fa-broom me-1"></i>Clean Up Old Updates (Keep 3)
                                </button>
                            </div>
                            `
                        }
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = new bootstrap.Modal(document.getElementById('updatesListModal'));
    modal.show();
    
    // Remove modal from DOM when hidden
    document.getElementById('updatesListModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}
// Info Panel functionality
function loadInfoPanel() {
    // Load last updated time
    fetch('/api/info/last-updated')
        .then(response => response.json())
        .then(data => {
            if (data.last_updated) {
                document.getElementById('infoLastUpdated').textContent = data.last_updated;
            }
        })
        .catch(error => {
            console.error('Error loading last updated time:', error);
            document.getElementById('infoLastUpdated').textContent = 'Error loading';
        });
    
    // Load network info
    fetch('/api/info/network')
        .then(response => response.json())
        .then(data => {
            if (data.local_ip) {
                document.getElementById('networkAddress').textContent = 
                    `http://${data.local_ip}:${data.port}`;
            }
            if (data.tunnel_url) {
                document.getElementById('tunnelAddress').textContent = data.tunnel_url;
            }
        })
        .catch(error => {
            console.error('Error loading network info:', error);
            document.getElementById('networkAddress').textContent = 'Error loading';
        });
    
    // Load changelog
    fetch('/api/info/changelog')
        .then(response => response.json())
        .then(data => {
            const changelogContent = document.getElementById('changelogContent');
            if (data.recent_changes) {
                // Convert markdown to simple HTML
                const htmlContent = convertMarkdownToHtml(data.recent_changes);
                changelogContent.innerHTML = htmlContent;
                
                // Update last updated if available from changelog
                if (data.last_updated && data.last_updated !== 'Unknown') {
                    document.getElementById('infoLastUpdated').textContent = data.last_updated;
                }
            } else {
                changelogContent.innerHTML = '<p class="text-muted">No changelog available.</p>';
            }
        })
        .catch(error => {
            console.error('Error loading changelog:', error);
            document.getElementById('changelogContent').innerHTML = 
                '<p class="text-muted">Error loading changelog.</p>';
        });
}

// Simple markdown to HTML converter
function convertMarkdownToHtml(markdown) {
    return markdown
        // Headers
        .replace(/^### (.*$)/gim, '<h4>$1</h4>')
        .replace(/^## (.*$)/gim, '<h3>$1</h3>')
        .replace(/^# (.*$)/gim, '<h2>$1</h2>')
        // Bold and Italic
        .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/gim, '<em>$1</em>')
        // Links
        .replace(/\[([^\[]+)\]\(([^\)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
        // Lists
        .replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
        // Line breaks
        .replace(/\n/g, '<br>')
        // Code
        .replace(/`([^`]+)`/g, '<code>$1</code>');
}

// Add event listener for info modal
document.addEventListener('DOMContentLoaded', function() {
    const infoModal = document.getElementById('infoModal');
    if (infoModal) {
        infoModal.addEventListener('show.bs.modal', function() {
            loadInfoPanel();
        });
    }
});

// Loading spinner utility
window._pendingGlobalLoadingTasks = window._pendingGlobalLoadingTasks || [];
window.trackGlobalLoading = window.trackGlobalLoading || function(promise, message = '') {
    if (window.spinner) {
        return window.spinner.trackPromise(promise, message);
    }
    if (promise && typeof promise.finally === 'function') {
        window._pendingGlobalLoadingTasks.push({ promise, message });
    }
    return Promise.resolve(promise);
};

class LoadingSpinner {
    constructor() {
        this.spinner = document.getElementById('globalLoadingSpinner');
        this.pendingTokens = new Set();
        this.navigationLock = false;
        this.tokenCounter = 0;
        this.init();
    }

    init() {
        // Always create/update spinner with new SVG version
        this.createSpinner();

        // Set up event listeners for PWA compatibility
        this.setupEventListeners();
    }

    createSpinner() {
        const spinnerSVG = `
            <svg class="loading-spinner__canvas" viewBox="0 0 600 600" xmlns="http://www.w3.org/2000/svg">
                    <defs>
                        <g id="sideShape">
                            <mask id="sideMask" maskUnits="userSpaceOnUse" x="0" y="0" width="700" height="500">
                                <rect width="700" height="500" fill="white" />
                                <circle cx="119" cy="219" r="158" fill="black" />
                                <rect x="132" y="265" width="517" height="111" transform="rotate(-30 132 269)" fill="black" />
                            </mask>
                            <g mask="url(#sideMask)" fill="white">
                                <circle cx="161" cy="343" r="113" />
                                <circle cx="572" cy="165" r="60" />
                                <rect x="146" y="243" width="464" height="96" transform="rotate(-30 149 373)" />
                            </g>
                        </g>
                    </defs>
                    <circle cx="300" cy="300" r="3" fill="black" />
                    <g id="triangleGroup">
                        <polygon id="triangleShape" fill="none" stroke="#0066ff00" stroke-width="2" points="300,300 300,300 300,300" />
                    </g>
                    <g id="shapesGroup">
                        <g id="side1Group">
                            <rect id="side1" x="0" y="0" width="40" height="80" fill="#45b649" opacity="0" />
                            <use href="#sideShape" />
                        </g>
                        <g id="side2Group">
                            <rect id="side2" x="0" y="0" width="40" height="80" fill="#45b649" opacity="0" />
                            <use href="#sideShape" />
                        </g>
                        <g id="side3Group">
                            <rect id="side3" x="0" y="0" width="40" height="80" fill="#45b649" opacity="0" />
                            <use href="#sideShape" />
                        </g>
                    </g>
                    <g id="centerPlus" style="pointer-events: none;">
                        <rect x="225" y="282.5" width="150" height="35" fill="#45b649" rx="10"/>
                        <rect x="282.5" y="225" width="35" height="150" fill="#45b649" rx="10"/>
                    </g>
                </svg>
        `;

        // Find or create the spinner container
        this.spinner = document.getElementById('globalLoadingSpinner');
        if (this.spinner) {
            // Replace the old content with the new SVG
            this.spinner.innerHTML = spinnerSVG;
        } else {
            // If it doesn't exist, create the container and add SVG
            const spinnerHTML = `<div id="globalLoadingSpinner" class="loading-spinner show">${spinnerSVG}</div>`;
            document.body.insertAdjacentHTML('beforeend', spinnerHTML);
            this.spinner = document.getElementById('globalLoadingSpinner');
        }

        this.startAnimation();
    }

    startAnimation() {
        if (!this.spinner) {
            console.warn('Spinner element not found, cannot start animation');
            return;
        }

        const CENTER = { x: 300, y: 300 };
        const RECT_WIDTH = 40;

        let shapeConfig = {
            maskCx: 119, maskCy: 219, maskCr: 158,
            maskRx: 132, maskRy: 265, maskRw: 517, maskRh: 111, maskRrot: -30,
            shapeC1x: 161, shapeC1y: 343, shapeC1r: 113,
            shapeC2x: 572, shapeC2y: 165, shapeC2r: 60,
            shapeRx: 146, shapeRy: 243, shapeRw: 464, shapeRh: 96, shapeRrot: -30,
            shapeFillColor: '#ffffff', shapeOpacity: 1
        };

        let keyframes = [
            { triangleSize: 115, triangleRotation: 60, rectLength: 200, shapeScale: 7.8, shapeRotation: -60, shapeOffsetX: -8, shapeOffsetY: 27, plusWidth: 40, plusLength: 40, time: 0.0 },
            { triangleSize: 180, triangleRotation: 60, rectLength: 200, shapeScale: 7.8, shapeRotation: -60, shapeOffsetX: -8, shapeOffsetY: 27, plusWidth: 40, plusLength: 40, time: 0.3 },
            { triangleSize: 180, triangleRotation: 180, rectLength: 200, shapeScale: 7.8, shapeRotation: -60, shapeOffsetX: -8, shapeOffsetY: 27, plusWidth: 40, plusLength: 40, time: 0.8 },
            { triangleSize: 180, triangleRotation: 180, rectLength: 200, shapeScale: 7.8, shapeRotation: -60, shapeOffsetX: -8, shapeOffsetY: 27, plusWidth: 40, plusLength: 40, time: 1.0 },
            { triangleSize: 115, triangleRotation: 180, rectLength: 200, shapeScale: 7.8, shapeRotation: -60, shapeOffsetX: -8, shapeOffsetY: 27, plusWidth: 40, plusLength: 40, time: 1.5 }
        ];

        const updateSideShapeSVG = () => {
            const maskCircles = this.spinner.querySelectorAll('#sideMask circle');
            maskCircles.forEach(el => {
                el.setAttribute('cx', shapeConfig.maskCx);
                el.setAttribute('cy', shapeConfig.maskCy);
                el.setAttribute('r', shapeConfig.maskCr);
            });

            const maskRects = this.spinner.querySelectorAll('#sideMask rect:last-of-type');
            maskRects.forEach(el => {
                el.setAttribute('x', shapeConfig.maskRx);
                el.setAttribute('y', shapeConfig.maskRy);
                el.setAttribute('width', shapeConfig.maskRw);
                el.setAttribute('height', shapeConfig.maskRh);
                el.setAttribute('transform', `rotate(${shapeConfig.maskRrot} ${shapeConfig.maskRx} ${shapeConfig.maskRy})`);
            });

            const c1s = this.spinner.querySelectorAll('#sideShape > g[mask] circle:first-of-type');
            c1s.forEach(el => {
                el.setAttribute('cx', shapeConfig.shapeC1x);
                el.setAttribute('cy', shapeConfig.shapeC1y);
                el.setAttribute('r', shapeConfig.shapeC1r);
            });

            const c2s = this.spinner.querySelectorAll('#sideShape > g[mask] circle:last-of-type');
            c2s.forEach(el => {
                el.setAttribute('cx', shapeConfig.shapeC2x);
                el.setAttribute('cy', shapeConfig.shapeC2y);
                el.setAttribute('r', shapeConfig.shapeC2r);
            });

            const rects = this.spinner.querySelectorAll('#sideShape > g[mask] rect');
            rects.forEach(el => {
                el.setAttribute('x', shapeConfig.shapeRx);
                el.setAttribute('y', shapeConfig.shapeRy);
                el.setAttribute('width', shapeConfig.shapeRw);
                el.setAttribute('height', shapeConfig.shapeRh);
                el.setAttribute('transform', `rotate(${shapeConfig.shapeRrot} ${shapeConfig.shapeRx + shapeConfig.shapeRw/2} ${shapeConfig.shapeRy + shapeConfig.shapeRh/2})`);
            });

            const gs = this.spinner.querySelectorAll('#sideShape > g[mask]');
            gs.forEach(el => {
                el.setAttribute('fill', shapeConfig.shapeFillColor);
                el.setAttribute('opacity', shapeConfig.shapeOpacity);
            });
        };

        const updateVisualization = (state) => {
            const centerPlus = this.spinner.querySelector('#centerPlus');
            if (centerPlus) {
                const halfWidth = state.plusWidth / 2;
                const halfLength = state.plusLength / 2;
                const vertLine = centerPlus.querySelector('rect:first-child');
                const horizLine = centerPlus.querySelector('rect:last-child');
                if (vertLine) {
                    vertLine.setAttribute('y', 300 - halfLength);
                    vertLine.setAttribute('height', state.plusLength);
                }
                if (horizLine) {
                    horizLine.setAttribute('x', 300 - halfWidth);
                    horizLine.setAttribute('width', state.plusWidth);
                }
            }

            const corners = [];
            for (let i = 0; i < 3; i++) {
                const angle = (i * 120 + state.triangleRotation) * Math.PI / 180;
                const x = CENTER.x + state.triangleSize * Math.cos(angle);
                const y = CENTER.y + state.triangleSize * Math.sin(angle);
                corners.push({ x, y, angle: (i * 120 + state.triangleRotation) % 360 });
            }

            const triangleShape = this.spinner.querySelector('#triangleShape');
            if (triangleShape) {
                triangleShape.setAttribute('points', corners.map(c => `${c.x},${c.y}`).join(' '));
            }

            corners.forEach((corner, i) => {
                const edgeX = CENTER.x + (corner.x - CENTER.x) * 0.7;
                const edgeY = CENTER.y + (corner.y - CENTER.y) * 0.7;
                const rectRotation = corner.angle;
                const groupId = `side${i + 1}Group`;
                const group = this.spinner.querySelector(`#${groupId}`);
                if (group) {
                    const transformStr = `translate(${edgeX - RECT_WIDTH/2}, ${edgeY - state.rectLength/2}) rotate(${rectRotation} ${RECT_WIDTH/2} ${state.rectLength/2})`;
                    group.setAttribute('transform', transformStr);
                    const sideRect = this.spinner.querySelector(`#side${i + 1}`);
                    if (sideRect) sideRect.setAttribute('height', state.rectLength);

                    const useElement = group.querySelector('use');
                    if (useElement) {
                        const baseScale = 40 / 650;
                        const totalScale = baseScale * state.shapeScale;
                        const centerX = RECT_WIDTH / 2 + state.shapeOffsetX;
                        const centerY = state.rectLength / 2 + state.shapeOffsetY;
                        const shapeTransform = `translate(${centerX}, ${centerY}) rotate(${state.shapeRotation}) scale(${totalScale}) translate(-325, -250)`;
                        useElement.setAttribute('transform', shapeTransform);
                    }
                }
            });
        };

        const interpolateState = (t) => {
            if (keyframes.length === 0) return keyframes[0];
            if (keyframes.length === 1) return { ...keyframes[0] };

            let kf1 = keyframes[0];
            let kf2 = keyframes[keyframes.length - 1];

            for (let i = 0; i < keyframes.length - 1; i++) {
                if (t >= keyframes[i].time && t <= keyframes[i + 1].time) {
                    kf1 = keyframes[i];
                    kf2 = keyframes[i + 1];
                    break;
                }
            }

            const totalTime = kf2.time - kf1.time;
            const elapsed = t - kf1.time;
            const progress = totalTime === 0 ? 0 : Math.max(0, Math.min(1, elapsed / totalTime));

            return {
                triangleSize: kf1.triangleSize + (kf2.triangleSize - kf1.triangleSize) * progress,
                triangleRotation: kf1.triangleRotation + (kf2.triangleRotation - kf1.triangleRotation) * progress,
                rectLength: kf1.rectLength + (kf2.rectLength - kf1.rectLength) * progress,
                shapeScale: kf1.shapeScale + (kf2.shapeScale - kf1.shapeScale) * progress,
                shapeRotation: kf1.shapeRotation + (kf2.shapeRotation - kf1.shapeRotation) * progress,
                shapeOffsetX: kf1.shapeOffsetX + (kf2.shapeOffsetX - kf1.shapeOffsetX) * progress,
                shapeOffsetY: kf1.shapeOffsetY + (kf2.shapeOffsetY - kf1.shapeOffsetY) * progress,
                plusWidth: kf1.plusWidth + (kf2.plusWidth - kf1.plusWidth) * progress,
                plusLength: kf1.plusLength + (kf2.plusLength - kf1.plusLength) * progress,
                time: t
            };
        };

        // Apply initial configuration
        updateSideShapeSVG();
        updateVisualization(keyframes[0]);

        this.animationStartTime = Date.now();

        // Store the animation loop so we can restart it
        const animationLoop = () => {
            const elapsed = (Date.now() - this.animationStartTime) / 1000;
            const totalDuration = keyframes[keyframes.length - 1].time;
            const loopedTime = elapsed % totalDuration;

            const state = interpolateState(loopedTime);
            updateVisualization(state);
            requestAnimationFrame(animationLoop);
        };

        animationLoop();
    }

    setupEventListeners() {
        if (document.readyState === 'complete') {
            this.markPageReady();
        } else {
            window.addEventListener('load', () => this.markPageReady(), { once: true });
        }

        window.addEventListener('pageshow', (event) => {
            if (event.persisted) {
                this.navigationLock = false;
                this.markPageReady();
            }
        });
    }

    show(message = '') {
        if (this.spinner) {
            this.spinner.classList.add('show');
            document.body.style.overflow = 'hidden';
            this.animationStartTime = Date.now();
        }
    }

    hide() {
        if (this.spinner && this.spinner.classList.contains('show')) {
            // Add hiding class for fade-out transition
            this.spinner.classList.add('hiding');

            // Wait for fade-out animation to complete before fully hiding
            setTimeout(() => {
                if (this.spinner) {
                    this.spinner.classList.remove('show');
                    this.spinner.classList.remove('hiding');
                    document.body.style.overflow = '';
                }
            }, 600); // Match the CSS transition duration
        }
    }

    beginTask(message = '') {
        const token = `spinner-task-${++this.tokenCounter}`;
        this.pendingTokens.add(token);
        this.show(message);
        return token;
    }

    endTask(token) {
        if (!token) return;
        this.pendingTokens.delete(token);
        this.syncVisibility();
    }

    trackPromise(promise, message = '') {
        if (!promise || typeof promise.finally !== 'function') {
            return Promise.resolve(promise);
        }
        const token = this.beginTask(message);
        return promise.finally(() => this.endTask(token));
    }

    markPageReady() {
        this.endTask('page-load');
    }

    lockForNavigation(message = '') {
        this.navigationLock = true;
        this.show(message);
    }

    unlockNavigation() {
        this.navigationLock = false;
        this.syncVisibility();
    }

    syncVisibility() {
        if (this.navigationLock || this.pendingTokens.size > 0) {
            this.show();
            return;
        }
        this.hide();
    }
}

// Form submission handlers
document.addEventListener('DOMContentLoaded', function() {

    window.spinner = new LoadingSpinner();
    window.trackGlobalLoading = function(promise, message = '') {
        return window.spinner.trackPromise(promise, message);
    };

    window.spinner.pendingTokens.add('page-load');
    window.spinner.show();

    if (window._pendingGlobalLoadingTasks.length) {
        window._pendingGlobalLoadingTasks.forEach(({ promise, message }) => {
            window.spinner.trackPromise(promise, message);
        });
        window._pendingGlobalLoadingTasks = [];
    }

    // Set up navigation and form handlers
    setupNavigationHandlers();
});

function setupNavigationHandlers() {
    const spinner = window.spinner;
    const startNavigationTransition = (message) => {
        _stopBackgroundWorkForNavigation();
        spinner.lockForNavigation(message);
    };
    
    // Handle form submissions
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const action = this.getAttribute('action') || '';
            const target = this.getAttribute('target') || '';

            if (target === '_blank' || this.dataset.noSpinner === 'true') {
                return;
            }

            let message = 'Processing...';
            if (action.includes('search')) {
                message = 'Searching...';
            }

            setTimeout(() => {
                if (!e.defaultPrevented) {
                    startNavigationTransition(message);
                }
            }, 0);
        });
    });

    const shouldTriggerNavigationSpinner = (event, link) => {
        if (!link) return false;
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) return false;
        if (link.hasAttribute('download') || link.target === '_blank') return false;
        if (link.dataset.bsToggle || link.getAttribute('role') === 'button') return false;
        if (event.defaultPrevented || event.button !== 0) return false;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;

        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin) return false;
        if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return false;

        return true;
    };

    const links = document.querySelectorAll('a[href]:not([target="_blank"])');
    links.forEach(link => {
        link.addEventListener('click', function(event) {
            if (!shouldTriggerNavigationSpinner(event, this)) return;

            startNavigationTransition('Loading page...');

            // Safety release if custom JS cancels navigation after the click.
            setTimeout(() => {
                if (document.visibilityState === 'visible' && !_bg.navigating) {
                    spinner.unlockNavigation();
                }
            }, 8000);
        });
    });

    document.addEventListener('pointerdown', function(event) {
        const link = event.target.closest('a[href]:not([target="_blank"])');
        if (!link) return;
        if (!shouldTriggerNavigationSpinner(event, link)) return;
        _stopBackgroundWorkForNavigation();
    }, true);

    document.addEventListener('touchstart', function(event) {
        const link = event.target.closest('a[href]:not([target="_blank"])');
        if (!link) return;
        if (link.dataset.bsToggle || link.getAttribute('role') === 'button') return;
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
        if (link.hasAttribute('download') || link.target === '_blank') return;
        const url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin) return;
        _stopBackgroundWorkForNavigation();
    }, { capture: true, passive: true });
}

// Make spinner available globally
window.LoadingSpinner = LoadingSpinner;

class PWALoadingHelper {
    constructor() {
        this.setupPWAEvents();
    }

    setupPWAEvents() {
        // Listen for service worker messages
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                if (event.data && event.data.type === 'CONTENT_LOADED') {
                    window.spinner.markPageReady();
                }
            });
        }

        // Handle beforeunload for page transitions
        window.addEventListener('beforeunload', () => {
            _stopBackgroundWorkForNavigation();
            window.spinner.lockForNavigation('Loading...');
        });

        window.addEventListener('pagehide', () => {
            _stopBackgroundWorkForNavigation();
        });

        // Handle page restoration from cache (PWA behavior)
        window.addEventListener('pageshow', (event) => {
            _bg.navigating = false;
            if (event.persisted) {
                setTimeout(() => window.spinner.unlockNavigation(), 100);
            }
        });
    }
}

// Initialize PWA helper
document.addEventListener('DOMContentLoaded', function() {
    window.pwaHelper = new PWALoadingHelper();
});

// static/js/media_grid.js - Shared media grid functionality

// Handle media click - determines whether to show details or manage details
function handleMediaClick(mediaType, mediaId, internalId) {
    if (internalId && internalId !== 'null') {
        showManageDetails(mediaType, mediaId, internalId);
    } else {
        showDetails(mediaType, mediaId);
    }
}

// Check library status for all items on page load — uses batch endpoint
function initializeMediaGrid() {
    const cards = document.querySelectorAll('.search-result-card');
    if (!cards.length) return;

    const needsCheck = [];   // cards that don't already have an internal ID
    const movieIds = [];
    const tvIds    = [];

    cards.forEach(card => {
        const mediaType  = card.dataset.mediaType;
        const mediaId    = card.dataset.mediaId;
        const internalId = card.dataset.internalId;

        if (internalId && internalId !== 'null') {
            // Already known — fast path
            const statusBadge    = card.querySelector('.status-badge');
            const manageControls = card.querySelector('.manage-controls');
            if (statusBadge) {
                statusBadge.textContent = 'In Library';
                statusBadge.className   = 'status-badge text-xs badge bg-success';
            }
            showManageControls(mediaType, mediaId, internalId, manageControls, true);
        } else if (mediaType && mediaId) {
            needsCheck.push(card);
            if (mediaType === 'movie') movieIds.push(mediaId);
            else if (mediaType === 'tv') tvIds.push(mediaId);
        }
    });

    if (!needsCheck.length) return;

    // Single batch request for all unknown items
    const params = new URLSearchParams();
    if (movieIds.length) params.set('movie_ids', movieIds.join(','));
    if (tvIds.length)    params.set('tv_ids',    tvIds.join(','));

    fetch(`/api/library/batch-status?${params}`, { signal: _bg.signal })
        .then(r => r.json())
        .then(batch => {
            needsCheck.forEach(card => {
                const mediaType  = card.dataset.mediaType;
                const mediaId    = card.dataset.mediaId;
                const statusBadge   = card.querySelector('.status-badge');
                const extraBadges   = card.querySelector('.media-extra-badges');
                const manageControls = card.querySelector('.manage-controls');

                const info = (batch[mediaType] || {})[mediaId];
                if (info && info.in_library) {
                    if (statusBadge) {
                        statusBadge.textContent = 'In Library';
                        statusBadge.className   = 'status-badge text-xs badge bg-success';
                    }
                    const parentItem = card.closest('.media-item') || card.closest('.result-item');
                    if (parentItem) parentItem.dataset.internalId = info.internalId;

                    // Build a minimal itemData from batch response to avoid a second fetch
                    const itemData = {
                        id:         info.internalId,
                        hasFile:    info.hasFile,
                        statistics: info.statistics || {},
                        monitored:  info.monitored,
                        images:     info.images || [],
                        remotePoster: info.remotePoster || '',
                        title:      info.title || '',
                    };
                    if (extraBadges)    updateExtraBadges(mediaType, itemData, extraBadges);
                    if (manageControls) showManageControls(mediaType, mediaId, info.internalId, manageControls, true, itemData);
                } else {
                    // Not in library
                    if (statusBadge) {
                        statusBadge.textContent = 'Not Added';
                        statusBadge.className   = 'status-badge text-xs badge bg-secondary';
                    }
                    if (extraBadges)    { extraBadges.style.display = 'none'; extraBadges.innerHTML = ''; }
                    if (manageControls) { manageControls.style.display = 'none'; manageControls.innerHTML = ''; }
                }
            });
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                // Paused for a detail view — re-queue for when modal closes
                window._registerBgResume(() => initializeMediaGrid());
                return;
            }
            console.error('[initializeMediaGrid] batch status error:', err);
            // Fallback to individual checks
            needsCheck.forEach(card => checkLibraryStatus(card.dataset.mediaType, card.dataset.mediaId, card));
        });
}

// Initialize manage page grid — all items are already in the library so we skip
// the library-status round-trip and go straight to fetching details.
// Requests are sent in parallel batches of 8 so the server handles them
// concurrently rather than one-at-a-time (the old forEach issued them all
// at once but the browser's 6-connection limit serialised them anyway).
async function initializeManageGrid() {
    const mediaItems = Array.from(document.querySelectorAll('.media-item'));
    if (!mediaItems.length) return;

    // Pre-stamp all badges as "In Library" synchronously — no waiting
    mediaItems.forEach(item => {
        const card        = item.querySelector('.manage-result-card, .search-result-card');
        const statusBadge = card?.querySelector('.status-badge');
        if (statusBadge) {
            statusBadge.textContent = 'In Library';
            statusBadge.className   = 'status-badge text-xs badge bg-success';
        }
    });

    // Build work list
    const tasks = mediaItems.map(item => {
        const mediaType     = item.dataset.mediaType;
        const mediaId       = item.dataset.id;
        const card          = item.querySelector('.manage-result-card, .search-result-card');
        const extraBadges   = card?.querySelector('.media-extra-badges');
        const manageControls = card?.querySelector('.manage-controls');
        if (!card || !mediaType || !mediaId) return null;
        return { mediaType, mediaId, extraBadges, manageControls };
    }).filter(Boolean);

    // Process in parallel batches of 8
    const BATCH = 8;
    for (let i = 0; i < tasks.length; i += BATCH) {
        const slice = tasks.slice(i, i + BATCH);
        try {
            await Promise.all(slice.map(async ({ mediaType, mediaId, extraBadges, manageControls }) => {
                try {
                    const r = await fetch(
                        `/get_media_details?type=${mediaType}&id=${mediaId}`,
                        { signal: _bg.signal }
                    );
                    const details    = await r.json();
                    if (details.error) return;
                    const itemData   = details.data || details;
                    const internalId = itemData.id;
                    if (extraBadges)     updateExtraBadges(mediaType, itemData, extraBadges);
                    if (manageControls)  showManageControls(mediaType, mediaId, internalId, manageControls, true, itemData);
                } catch (err) {
                    if (err.name === 'AbortError') throw err; // propagate abort
                    console.error('[initializeManageGrid] detail error:', err);
                }
            }));
        } catch (err) {
            if (err.name === 'AbortError') {
                if (!initializeManageGrid._resumeQueued) {
                    initializeManageGrid._resumeQueued = true;
                    window._registerBgResume(() => {
                        initializeManageGrid._resumeQueued = false;
                        initializeManageGrid();
                    });
                }
                return;
            }
        }
    }
}

// Fetch library status and update UI
function checkLibraryStatus(mediaType, mediaId, card) {
    fetch(`/check_library_status?type=${mediaType}&id=${mediaId}`)
        .then(response => response.json())
        .then(data => {
            const statusBadge = card.querySelector('.status-badge');
            const extraBadges = card.querySelector('.media-extra-badges');
            const manageControls = card.querySelector('.manage-controls');
            
            if (data.in_library) {
                // Update the main "In Library" badge
                statusBadge.textContent = 'In Library';
                statusBadge.className = 'status-badge text-xs badge bg-success';
                
                // Get internal ID and update the card with extra badges and controls
                fetch(`/get_media_details?type=${mediaType}&id=${mediaId}`)
                    .then(response => response.json())
                    .then(details => {
                        const itemData = details.data || details;
                        const internalId = itemData.id;
                        
                        // Update card with internal ID if it has a parent
                        const parentItem = card.closest('.media-item') || card.closest('.result-item');
                        if (parentItem) {
                            parentItem.dataset.internalId = internalId;
                        }
                        
                        // Update the extra badges (On disk / Missing)
                        updateExtraBadges(mediaType, itemData, extraBadges);
                        
                        // Show manage controls with delete button
                        showManageControls(mediaType, mediaId, internalId, manageControls, true, itemData);
                    })
                    .catch(error => {
                        console.error('Error fetching internal ID:', error);
                    });
            } else {
                statusBadge.textContent = 'Not Added';
                statusBadge.className = 'status-badge text-xs badge bg-secondary';
                extraBadges.style.display = 'none';
                extraBadges.innerHTML = '';
                manageControls.style.display = 'none';
                manageControls.innerHTML = '';
            }
        })
        .catch(error => {
            console.error('Error checking library status:', error);
            const statusBadge = card.querySelector('.status-badge');
            statusBadge.textContent = 'Error';
            statusBadge.className = 'status-badge text-xs badge bg-danger';
        });
}

// Update extra badges for On disk / Missing status
function updateExtraBadges(mediaType, itemData, extraBadgesContainer) {
    let badgesHTML = '';
    
    if (mediaType === 'movie') {
        const hasFile = itemData ? itemData.hasFile : false;
        badgesHTML = `<span class="badge ${hasFile ? 'bg-success' : 'bg-warning'}">${hasFile ? 'On disk' : 'Missing'}</span>`;
    } else {
        const stats = itemData ? (itemData.statistics || {}) : {};
        const hasEpisodes = (stats.episodeFileCount || 0) > 0;
        const allDownloaded = stats.episodeFileCount === stats.episodeCount;
        
        if (allDownloaded) {
            badgesHTML = `<span class="badge bg-success">On disk</span>`;
        } else if (hasEpisodes) {
            badgesHTML = `<span class="badge bg-info">Partial (${stats.episodeFileCount}/${stats.episodeCount})</span>`;
        } else {
            badgesHTML = `<span class="badge bg-warning">Missing</span>`;
        }
    }
    
    extraBadgesContainer.innerHTML = badgesHTML;
    extraBadgesContainer.style.display = badgesHTML ? 'block' : 'none';
}

// Show manage controls for items in library
function showManageControls(mediaType, mediaId, internalId, manageControls, isManagePage = false, itemData = null) {
    // For manage page, we already have all the data
    if (isManagePage && itemData) {
        updateManageControlsHTML(mediaType, mediaId, internalId, manageControls, itemData);
    } else {
        // For other pages, fetch additional details
        fetch(`/get_media_details?type=${mediaType}&id=${mediaId}`)
            .then(response => response.json())
            .then(details => {
                const data = details.data || details;
                updateManageControlsHTML(mediaType, mediaId, internalId, manageControls, data);
            })
            .catch(error => {
                console.error('Error fetching manage details:', error);
            });
    }
}

// Update manage controls HTML - just show delete button for manage page
function updateManageControlsHTML(mediaType, mediaId, internalId, manageControls, itemData) {
    // For manage page, just show a compact delete button
    const deleteHTML = `
        <button class="btn btn-sm btn-outline-danger delete-btn" 
                title="Delete from library"
                data-media-type="${mediaType}"
                data-internal-id="${internalId}">
            <i class="fas fa-trash"></i>
        </button>
    `;
    
    manageControls.innerHTML = deleteHTML;
    manageControls.style.display = 'block';
    
    // Add event listeners to new buttons
    addManageEventListeners(manageControls);
}

// Add event listeners to manage controls
function addManageEventListeners(container) {
    // Monitor toggle
    const monitorToggle = container.querySelector('.monitor-toggle');
    if (monitorToggle) {
        monitorToggle.addEventListener('change', function(e) {
            e.stopPropagation();
            const mediaType = this.dataset.mediaType;
            const internalId = this.dataset.internalId;
            const monitored = this.checked;
            
            fetch(`/api/${mediaType}/${internalId}/monitor`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ monitored })
            })
            .then(response => {
                if (!response.ok) throw new Error('Failed to update monitoring status');
                showNotification('Monitoring status updated', 'success');
            })
            .catch(error => {
                console.error(error);
                this.checked = !monitored;
                showNotification('Failed to update monitoring status', 'error');
            });
        });
    }

    // Search button
    const searchBtn = container.querySelector('.search-btn');
    if (searchBtn) {
        searchBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            const mediaType = this.dataset.mediaType;
            const internalId = this.dataset.internalId;
            
            fetch(`/api/${mediaType}/${internalId}/search`, {
                method: 'POST'
            })
            .then(response => {
                if (response.ok) {
                    showNotification('Search initiated successfully', 'success');
                } else {
                    throw new Error('Failed to initiate search');
                }
            })
            .catch(error => {
                console.error(error);
                showNotification('Failed to initiate search', 'error');
            });
        });
    }

    // Delete button
    const deleteBtn = container.querySelector('.delete-btn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            if (confirm('Are you sure you want to delete this from your library?')) {
                const mediaType = this.dataset.mediaType;
                const internalId = this.dataset.internalId;
                
                fetch(`/api/${mediaType}/${internalId}`, {
                    method: 'DELETE'
                })
                .then(response => {
                    if (response.ok) {
                        showNotification('Item deleted successfully', 'success');
                        // Refresh the page or update the UI
                        window.location.reload();
                    } else {
                        throw new Error('Failed to delete item');
                    }
                })
                .catch(error => {
                    console.error(error);
                    showNotification('Failed to delete item', 'error');
                });
            }
        });
    }
}

// Simple notification function
function showNotification(message, type) {
    // Implement toast notification or use alert for now
    const alertClass = type === 'success' ? 'alert-success' : 'alert-danger';
    const notification = document.createElement('div');
    notification.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
    notification.classList.add('notification-toast');
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}
// Clear search functionality
function initializeClearSearchOLD() {
    const searchInput = document.getElementById('searchInput');
    if (!searchInput) {
        console.error('Search input not found');
        return;
    }
    const clearButton = document.getElementById('clearSearch');
    if (!clearButton) {
        console.error('Search input not found');
        return;
    }
    if (!searchInput || !clearButton) return;
    
    // Update clear button state based on input content
    function updateClearButton() {
        if (searchInput.value.trim() !== '') {
            clearButton.disabled = false;
        } else {
            clearButton.disabled = true;
        }
    }
    
    // Clear the search input
    function clearSearch() {
        if (!clearButton.disabled) {
            searchInput.value = '';
            searchInput.focus();
            updateClearButton();
        }
    }
    
    // Event listeners
    searchInput.addEventListener('input', updateClearButton);
    searchInput.addEventListener('keyup', updateClearButton);
    clearButton.addEventListener('click', clearSearch);
    
    // Initialize on page load
    updateClearButton();
}
// Filter and search functionality
function updateMediaDisplay() {
    const searchInput = document.getElementById('searchInput');
    if (!searchInput) {
        console.error('Search input not found');
        return;
    }
    
    const searchTerm = searchInput.value.toLowerCase();
    const mediaFilterElement = document.getElementById('mediaFilter');
    const currentFilter = mediaFilterElement ? mediaFilterElement.value : 'all';
    const availabilityFilter = document.getElementById('availabilityFilter');
    const availabilityValue = availabilityFilter ? availabilityFilter.value : 'all';
    const activeManageFilter = document.querySelector('[data-manage-filter].is-active');
    const manageFilterValue = activeManageFilter ? activeManageFilter.dataset.manageFilter : 'all';
    
    document.querySelectorAll('.media-item').forEach(item => {
        const title = item.dataset.title;
        const isMovie = item.classList.contains('movie-item');
        const isTV = item.classList.contains('tv-item');
        const isBook = item.classList.contains('book-item');
        const filterState = item.dataset.filterState || 'all';
        const isMonitored = item.dataset.monitored === 'true';

        const matchesSearch = searchTerm === '' || title.includes(searchTerm);
        const matchesFilter = currentFilter === 'all' ||
                            (currentFilter === 'movie' && isMovie) ||
                            (currentFilter === 'tv' && isTV) ||
                            (currentFilter === 'book' && isBook);
        const matchesAvailability = availabilityValue === 'all' ||
                            (availabilityValue === 'movie_missing_file' && isMovie && item.dataset.missingFiles === 'true') ||
                            (availabilityValue === 'tv_missing_episodes' && isTV && item.dataset.missingEpisodes === 'true');
        const matchesManageFilter = manageFilterValue === 'all' ||
                            (manageFilterValue === 'missing' && filterState === 'missing') ||
                            (manageFilterValue === 'available' && filterState === 'available') ||
                            (manageFilterValue === 'unmonitored' && !isMonitored);

        item.style.display = (matchesSearch && matchesFilter && matchesAvailability && matchesManageFilter) ? '' : 'none';
    });
}

// Clear search functionality for manage page
function initializeClearSearch() {
    const searchInput = document.getElementById('searchInput');
    const clearButton = document.getElementById('clearSearch');
    
    if (!searchInput || !clearButton) {
        console.log('Clear search elements not found');
        return;
    }
    
    // Update clear button state based on input content
    function updateClearButton() {
        if (searchInput.value.trim() !== '') {
            clearButton.disabled = false;
        } else {
            clearButton.disabled = true;
        }
    }
    
    // Clear the search input
    function clearSearch() {
        if (!clearButton.disabled) {
            searchInput.value = '';
            searchInput.focus();
            updateClearButton();
            updateMediaDisplay(); // Update display when cleared
        }
    }
    
    // Event listeners
    searchInput.addEventListener('input', function() {
        updateClearButton();
        updateMediaDisplay(); // Real-time filtering
    });
    
    searchInput.addEventListener('keyup', function(e) {
        if (e.key === 'Enter') {
            updateMediaDisplay();
        }
    });
    
    clearButton.addEventListener('click', clearSearch);

    // Initialize on page load
    updateClearButton();
}

// ── Keyboard detection and viewport management ──────────────────────────────
// Handles Android soft keyboard appearing/disappearing to keep buttons visible
// Fixed version: properly calculates scroll position to keep navbar visible and buttons centered above keyboard
document.addEventListener('DOMContentLoaded', function() {
    const mainSearchContainer = document.getElementById('mainSearchContainer');
    const mainSearchInput = document.getElementById('mainSearchInput');
    const navbar = document.querySelector('.container-fluid.bg-dark');

    if (!mainSearchContainer || !mainSearchInput) return;

    let lastVisualViewportHeight = window.visualViewport?.height || window.innerHeight;
    let keyboardVisible = false;
    let originalScrollPosition = 0;

    // Constants
    const NAVBAR_HEIGHT = 60; // Navbar is ~60px tall
    const KEYBOARD_TRIGGER_THRESHOLD = 80; // Threshold to detect keyboard (in pixels)
    const KEYBOARD_HEIGHT_ESTIMATE = 280; // Typical Android keyboard height
    const TOP_MARGIN = 15; // Space between navbar and search form
    const BOTTOM_MARGIN = 10; // Space between form and keyboard

    function performKeyboardScroll() {
        const searchFormWrapper = mainSearchContainer.querySelector('.search-form-wrapper');
        if (!searchFormWrapper) return;

        // Get the visual viewport height (height visible above keyboard)
        const visualViewportHeight = window.visualViewport?.height || window.innerHeight;

        // Get the form element's full height
        const formRect = searchFormWrapper.getBoundingClientRect();
        const formHeight = formRect.height;

        // Calculate how much space we have above the keyboard
        // visualViewportHeight is the actual visible space
        const availableSpace = visualViewportHeight;

        // Calculate the ideal scroll position:
        // We want: navbar visible + form centered in remaining space above keyboard
        // 1. Start with navbar height as minimum
        // 2. Add space to center the form in the remaining viewport
        const currentScrollY = window.scrollY;
        const formTopAbsolute = currentScrollY + formRect.top;

        // Target: navbar visible (60px) + some margin, then form positioned so buttons are above keyboard
        // We need to ensure the bottom of the form (buttons) is at least BOTTOM_MARGIN pixels above keyboard
        // Bottom of form would be at: scrollY + formRect.top + formHeight
        // Keyboard starts at: visualViewportHeight
        // So we need: scrollY + formRect.top + formHeight + BOTTOM_MARGIN <= visualViewportHeight
        // Rearranging: scrollY <= visualViewportHeight - formRect.top - formHeight - BOTTOM_MARGIN

        // But we also want to keep navbar visible, so:
        // scrollY >= -formRect.top + NAVBAR_HEIGHT (approximately, when form is below navbar)

        // The scroll position should place the top of the form at navbar height + margin
        const targetScrollY = Math.max(
            0, // Don't scroll above top
            formTopAbsolute - NAVBAR_HEIGHT - TOP_MARGIN
        );

        // However, we also need to ensure buttons don't get covered by keyboard
        // Check if the form fits in the remaining space
        const spaceNeeded = NAVBAR_HEIGHT + formHeight + BOTTOM_MARGIN;

        // If form doesn't fit with current scroll, push it up more
        let finalScrollY = targetScrollY;

        // Ensure the form bottom doesn't go below the visual viewport minus keyboard margin
        const formBottomWithScroll = targetScrollY + formRect.top + formHeight;
        const maxFormBottom = visualViewportHeight - BOTTOM_MARGIN;

        if (formBottomWithScroll > maxFormBottom) {
            // Form would be cut off, scroll more to compensate
            finalScrollY = Math.max(0, visualViewportHeight - formRect.top - formHeight - BOTTOM_MARGIN);
        }

        // Scroll to the calculated position
        window.scrollTo({
            top: finalScrollY,
            behavior: 'smooth',
            left: 0
        });
    }

    // Track visual viewport changes to detect keyboard appearance
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', function() {
            const currentHeight = window.visualViewport.height;
            const heightDifference = lastVisualViewportHeight - currentHeight;

            // Keyboard appeared (viewport got smaller by significant amount)
            if (heightDifference > KEYBOARD_TRIGGER_THRESHOLD && !keyboardVisible) {
                keyboardVisible = true;
                originalScrollPosition = window.scrollY;
                performKeyboardScroll();
            }
            // Keyboard closed (viewport got larger)
            else if (heightDifference < -KEYBOARD_TRIGGER_THRESHOLD && keyboardVisible) {
                keyboardVisible = false;
                // Optionally could restore original scroll, but let user keep current position
            }

            lastVisualViewportHeight = currentHeight;
        });
    }

    // Fallback for browsers without visualViewport API
    mainSearchInput.addEventListener('focus', function() {
        setTimeout(() => {
            // Trigger scroll after keyboard appears
            keyboardVisible = true;
            performKeyboardScroll();
        }, 300);
    });

    // Also handle blur to detect keyboard closing on older browsers
    mainSearchInput.addEventListener('blur', function() {
        setTimeout(() => {
            keyboardVisible = false;
        }, 100);
    });
});


