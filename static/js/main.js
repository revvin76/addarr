let currentShowId = null; // track show id for delete/search actions

/**
 * imgProxy(url, w, h, title)
 * Routes any remote image URL through the local caching proxy (/api/img).
 * The server normalises TMDB /original/ → /w342/ before fetching, so
 * downloads are ~10× smaller while still looking sharp at card sizes.
 * Local and relative URLs (starting with '/') are returned unchanged.
 * The optional title appears in addarr.log so cache events are readable.
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
    get signal() { return this.controller.signal; }
};
// Expose to inline page scripts (trending.html, manage-books.html)
window._bg = _bg;
window._registerBgResume = fn => _bg.resumeQueue.push(fn);

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
function _resumeBackgroundFetches() {
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
});

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
    selectedQuality: {},
    selectedSeason: {}
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
                    <img src="${src}" class="img-fluid mx-auto d-block" alt="Full size" style="max-height: 90vh;">
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

function showManageDetails(mediaType, externalId, internalId) {
    _pauseBackgroundFetches();
    console.log('Showing details for:', mediaType, externalId, internalId);
    
    const modalEl = document.getElementById('detailsModal');
    const modal = new bootstrap.Modal(modalEl);
    const modalTitle = document.getElementById('detailsModalLabel');
    const overlay = document.getElementById('overlay-backdrop');
    
    // Show overlay
    overlay.style.display = 'block';
    
    // Show loading spinner
    document.getElementById('detailsContent').innerHTML = `
        <div class="text-center my-4">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p>Loading details...</p>
        </div>`;
    
    // Set modal title based on media type
    const typeLabel = mediaType === 'tv' ? 'TV Show' : mediaType === 'book' ? 'Book' : 'Movie';
    modalTitle.textContent = `${typeLabel} Details`;
    
    // Add event listener to hide overlay when modal is closed
    const hideModalHandler = function() {
        overlay.style.display = 'none';
        modalEl.removeEventListener('hidden.bs.modal', hideModalHandler);
    };
    
    modalEl.addEventListener('hidden.bs.modal', hideModalHandler);
    
    // Show the modal
    modal.show();
    
    // Fetch details from your backend
    fetch(`/get_media_details?type=${mediaType}&id=${externalId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            // Populate the modal with the retrieved data
            populateManageModalDetails(data, mediaType, internalId);
        })
        .catch(error => {
            console.error('Error fetching details:', error);
            document.getElementById('detailsContent').innerHTML = `
                <div class="alert alert-danger">
                    Error loading details: ${error.message}
                </div>`;
        });
}

// Function to populate modal with details for manage page
function populateManageModalDetails(data, mediaType, internalId) {
    const detailsContent = document.getElementById('detailsContent');

    // Extract the actual media data
    const mediaData = data.data || data;

    if (mediaType === 'movie') {
        renderMovieDetails(mediaData, data, mediaType, internalId);
    } else if (mediaType === 'book') {
        renderBookDetails(mediaData, data, mediaType, internalId);
    } else {
        renderTVDetails(mediaData, data, mediaType, internalId);
    }
}

function renderBookDetails(mediaData, fullData, mediaType, internalId) {
    const detailsContent = document.getElementById('detailsContent');

    const posterImage = mediaData.images?.find(img => img.coverType === 'poster' || img.coverType === 'cover');
    const posterUrl = imgProxy(posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png', 300, 450, mediaData.title);

    const author = mediaData.author?.authorName || 'Unknown Author';
    const releaseYear = mediaData.releaseDate ? mediaData.releaseDate.substring(0, 4) : 'N/A';
    const pageCount = mediaData.pageCount ? `${mediaData.pageCount} pages` : '';
    const overview = mediaData.overview || 'No description available.';
    const sizeOnDisk = mediaData.statistics?.sizeOnDisk
        ? formatFileSize(mediaData.statistics.sizeOnDisk)
        : 'N/A';
    const onDisk = fullData.on_disk || false;
    const monitored = fullData.monitored || false;

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
            class="badge border-0 me-1"
            data-bm-id="${bmId}"
            style="background:#f39c12;color:#000;cursor:pointer;"
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
        <div class="row mb-3">
            <div class="col-4 pe-0">
                <img src="${posterUrl}"
                     class="img-fluid rounded w-100"
                     alt="${mediaData.title}"
                     onerror="this.src='/static/images/favicon.png'"
                     style="max-width: 120px;">
            </div>
            <div class="col-8 ps-2">
                <h4 class="mb-1">${mediaData.title || 'Unknown Title'}</h4>
                <div class="text-muted mb-1" style="font-size:0.9rem;">${author}</div>
                <div class="d-flex align-items-center flex-wrap mb-2">
                    <span class="me-2">${releaseYear}</span>
                    ${pageCount ? `<span>${pageCount}</span>` : ''}
                </div>
                <div class="d-flex flex-wrap gap-1 mb-2">
                    <span class="badge ${onDisk ? 'bg-success' : 'bg-warning'}">
                        ${onDisk ? 'Downloaded' : 'Missing'}
                    </span>
                    <span class="badge ${monitored ? 'bg-success' : 'bg-secondary'}">
                        ${monitored ? 'Monitored' : 'Not Monitored'}
                    </span>
                    ${bmBadge}
                </div>
            </div>
        </div>

        <div class="card bg-dark border-secondary mb-3">
            <div class="card-header"><h6 class="mb-0">BOOK DETAILS</h6></div>
            <div class="card-body p-2">
                <div class="row mb-2">
                    <div class="col-4"><strong>Author</strong></div>
                    <div class="col-8">${author}</div>
                </div>
                <div class="row mb-2">
                    <div class="col-4"><strong>Published</strong></div>
                    <div class="col-8">${mediaData.releaseDate ? mediaData.releaseDate.substring(0, 10) : 'N/A'}</div>
                </div>
                ${pageCount ? `
                <div class="row mb-2">
                    <div class="col-4"><strong>Pages</strong></div>
                    <div class="col-8">${mediaData.pageCount}</div>
                </div>` : ''}
                <div class="row mb-2">
                    <div class="col-4"><strong>Size on Disk</strong></div>
                    <div class="col-8">${sizeOnDisk}</div>
                </div>
                ${mediaData.path ? `
                <div class="row mb-2">
                    <div class="col-4"><strong>Path</strong></div>
                    <div class="col-8"><code class="text-wrap d-block" style="font-size:0.8rem;">${mediaData.path}</code></div>
                </div>` : ''}
            </div>
        </div>

        ${overview ? `
        <div class="card bg-dark border-secondary mb-3">
            <div class="card-header"><h6 class="mb-0">OVERVIEW</h6></div>
            <div class="card-body p-2">
                <p class="mb-0" style="font-size:0.9rem;">${overview}</p>
            </div>
        </div>` : ''}

        ${onDisk && mediaData.id ? `
        <a href="/read/${mediaData.id}" class="btn btn-success w-100 mb-2" target="_blank">
            <i class="fas fa-book-open me-2"></i>Read Now
        </a>` : ''}
    `;

    detailsContent.innerHTML = html;
}


function renderMovieDetails(mediaData, fullData, mediaType, internalId) {
    const detailsContent = document.getElementById('detailsContent');

    // Get poster image
    const posterImage = mediaData.images?.find(img => img.coverType === 'poster');
    const posterUrl = imgProxy(posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png', 300, 450, mediaData.title);

    // Format runtime
    const runtime = mediaData.runtime ? `${Math.floor(mediaData.runtime / 60)}h ${mediaData.runtime % 60}m` : 'N/A';
    
    // Format file size
    const fileSize = mediaData.sizeOnDisk ? formatFileSize(mediaData.sizeOnDisk) : 'N/A';
    
    // Get quality information
    const quality = mediaData.movieFile?.quality?.quality?.name || 'Unknown';
    
    // Get file information
    const movieFile = mediaData.movieFile;
    const relativePath = movieFile?.relativePath || 'No file downloaded';
    
    const html = `
        <!-- Poster and Basic Info Row -->
        <div class="row mb-3">
            <!-- Poster Column - Fixed Width -->
            <div class="col-4 pe-0">
                <img src="${posterUrl}" 
                     class="img-fluid rounded w-100" 
                     alt="${mediaData.title}"
                     onerror="this.src='/static/images/favicon.png'"
                     style="max-width: 120px;">
            </div>
            
            <!-- Title and Details Column -->
            <div class="col-8 ps-2">
                <h4 class="mb-1">${mediaData.title || 'Unknown Title'}</h4>
                <div class="d-flex align-items-center flex-wrap mb-2">
                    ${mediaData.certification ? `<span class="badge bg-dark me-1">${mediaData.certification}</span>` : ''}
                    <span class="me-1">${mediaData.year || ''}</span>
                    <span class="">${runtime}</span>
                </div>
                
                <!-- Status Badges -->
                <div class="d-flex flex-wrap gap-1 mb-2">
                    <span class="badge ${fullData.on_disk ? 'bg-success' : 'bg-warning'}">
                        ${fullData.on_disk ? 'Downloaded' : 'Missing'}
                    </span>
                    <span class="badge ${fullData.monitored ? 'bg-success' : 'bg-secondary'}">
                        ${fullData.monitored ? 'Monitored' : 'Not Monitored'}
                    </span>
                    ${mediaData.status ? `<span class="badge bg-info">${mediaData.status}</span>` : ''}
                </div>
            </div>
        </div>

        <!-- Action Buttons -->
        <div class="row mb-3">
            <div class="col-12">
                <div class="d-grid gap-2 d-flex flex-wrap">
                    <button class="btn ${fullData.monitored ? 'btn-warning' : 'btn-success'} flex-fill monitor-toggle"
                            data-type="${mediaType}"
                            data-id="${internalId}"
                            data-monitored="${fullData.monitored}"
                            data-has-missing="${!fullData.on_disk}">
                        ${fullData.monitored ? 'Unmonitor' : 'Monitor'}
                    </button>
                    ${fullData.monitored && !fullData.on_disk ? `
                    <button class="btn btn-primary flex-fill search-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-bolt me-1"></i> Auto Search
                    </button>
                    <button class="btn btn-outline-info flex-fill interactive-search-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-list me-1"></i> Choose Source
                    </button>` : ''}
                    <button class="btn btn-danger flex-fill delete-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-trash me-1"></i> Delete
                    </button>
                </div>
            </div>
        </div>

        <div id="interactiveSearchContainer" class="card bg-dark border-secondary mb-3" style="display:none;">
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

        <!-- Movie Details Card -->
        <div class="card bg-dark border-secondary mb-3">
            <div class="card-header">
                <h6 class="mb-0">MOVIE DETAILS</h6>
            </div>
            <div class="card-body p-2">
                <!-- Path -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Path</strong></div>
                    <div class="col-8">
                        <code class="text-wrap d-block" style="font-size: 0.8rem;">${mediaData.path || 'N/A'}</code>
                    </div>
                </div>
                
                <!-- Status -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Status</strong></div>
                    <div class="col-8">${fullData.on_disk ? 'Downloaded' : 'Missing'}</div>
                </div>
                
                <!-- Quality Profile -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Quality Profile</strong></div>
                    <div class="col-8">${quality}</div>
                </div>
                
                <!-- Size -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Size</strong></div>
                    <div class="col-8">${fileSize}</div>
                </div>
                
                <!-- Genres -->
                ${mediaData.genres && mediaData.genres.length > 0 ? `
                <div class="row mb-2">
                    <div class="col-4"><strong>Genres</strong></div>
                    <div class="col-8">
                        ${mediaData.genres.map(genre => `<span class="badge bg-secondary me-1 mb-1">${genre}</span>`).join('')}
                    </div>
                </div>
                ` : ''}
                
                <!-- Rating -->
                ${mediaData.ratings?.value ? `
                <div class="row mb-2">
                    <div class="col-4"><strong>Rating</strong></div>
                    <div class="col-8">
                        <span class="badge bg-primary">${mediaData.ratings.value}/10</span>
                        ${mediaData.ratings.votes ? `<small class="text-muted ms-1">(${mediaData.ratings.votes} votes)</small>` : ''}
                    </div>
                </div>
                ` : ''}
            </div>
        </div>

        <!-- Files Section -->
        <div class="card bg-dark border-secondary mb-3">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0">FILES</h6>
                <button class="btn btn-sm btn-outline-warning refresh-files-btn" 
                        data-type="${mediaType}" 
                        data-id="${internalId}">
                    <i class="fas fa-sync-alt"></i>
                </button>
            </div>
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-dark table-hover mb-0">
                        <thead>
                            <tr>
                                <th class="border-0 ps-2">Relative Path</th>
                                <th class="border-0 text-end pe-2">Size</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td class="text-wrap ps-2" style="font-size: 0.8rem;">
                                    <code>${relativePath}</code>
                                </td>
                                <td class="text-end pe-2">${fileSize}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Overview Section -->
        ${mediaData.overview ? `
        <div class="card bg-dark border-secondary">
            <div class="card-header">
                <h6 class="mb-0">OVERVIEW</h6>
            </div>
            <div class="card-body">
                <p class="mb-0" style="font-size: 0.9rem; line-height: 1.4;">${mediaData.overview}</p>
            </div>
        </div>
        ` : ''}
    `;
    
    detailsContent.innerHTML = html;
    
    // Add event listeners to the new buttons
    attachButtonEventListeners();
}

function renderTVDetails(mediaData, fullData, mediaType, internalId) {
    const detailsContent = document.getElementById('detailsContent');
    
    // Get poster image
    const posterImage = mediaData.images?.find(img => img.coverType === 'poster');
    const posterUrl = imgProxy(posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png', 300, 450, mediaData.title);

    // Format file size
    const fileSize = mediaData.sizeOnDisk ? formatFileSize(mediaData.sizeOnDisk) : 'N/A';
    
    // Get quality information
    const quality = mediaData.seriesType || 'Standard';
    
    // Get seasons data
    const seasons = mediaData.seasons || [];
    
    // Get statistics
    const stats = mediaData.statistics || {};
    const totalEpisodes = stats.episodeCount || 0;
    const downloadedEpisodes = stats.episodeFileCount || 0;
    const completionPercent = stats.percentOfEpisodes || 0;
    
    const html = `
        <!-- Poster and Basic Info Row -->
        <div class="row mb-3">
            <!-- Poster Column - Fixed Width -->
            <div class="col-4 pe-0">
                <img src="${posterUrl}" 
                     class="img-fluid rounded w-100" 
                     alt="${mediaData.title}"
                     onerror="this.src='/static/images/favicon.png'"
                     style="max-width: 120px;">
            </div>
            
            <!-- Title and Details Column -->
            <div class="col-8 ps-2">
                <h4 class="mb-1">${mediaData.title || 'Unknown Title'}</h4>
                <div class="d-flex align-items-center flex-wrap mb-2">
                    ${mediaData.certification ? `<span class="badge bg-dark me-1">${mediaData.certification}</span>` : ''}
                    <span class="me-1">${mediaData.year || ''}</span>
                    <span class="">${mediaData.network || ''}</span>
                </div>
                
                <!-- Status Badges -->
                <div class="d-flex flex-wrap gap-1 mb-2">
                    <span class="badge ${fullData.on_disk ? 'bg-success' : 'bg-warning'}">
                        ${fullData.on_disk ? 'Downloaded' : 'Missing'}
                    </span>
                    <span class="badge ${fullData.monitored ? 'bg-success' : 'bg-secondary'}">
                        ${fullData.monitored ? 'Monitored' : 'Not Monitored'}
                    </span>
                    ${mediaData.status ? `<span class="badge bg-info">${mediaData.status}</span>` : ''}
                </div>
            </div>
        </div>

        <!-- Action Buttons -->
        <div class="row mb-3">
            <div class="col-12">
                <div class="d-grid gap-2 d-flex flex-wrap">
                    <button class="btn ${fullData.monitored ? 'btn-warning' : 'btn-success'} flex-fill monitor-toggle"
                            data-type="${mediaType}"
                            data-id="${internalId}"
                            data-monitored="${fullData.monitored}"
                            data-has-missing="${downloadedEpisodes < totalEpisodes}">
                        ${fullData.monitored ? 'Unmonitor' : 'Monitor'}
                    </button>
                    ${fullData.monitored && downloadedEpisodes < totalEpisodes ? `
                    <button class="btn btn-primary flex-fill search-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-bolt me-1"></i> Auto Search
                    </button>
                    <button class="btn btn-outline-info flex-fill interactive-search-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-list me-1"></i> Choose Source
                    </button>` : ''}
                    <button class="btn btn-danger flex-fill delete-btn"
                            data-type="${mediaType}"
                            data-id="${internalId}">
                        <i class="fas fa-trash me-1"></i> Delete
                    </button>
                </div>
            </div>
        </div>

        <div id="interactiveSearchContainer" class="card bg-dark border-secondary mb-3" style="display:none;">
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

        <!-- TV Show Details Card -->
        <div class="card bg-dark border-secondary mb-3">
            <div class="card-header">
                <h6 class="mb-0">TV SHOW DETAILS</h6>
            </div>
            <div class="card-body p-2">
                <!-- Path -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Path</strong></div>
                    <div class="col-8">
                        <code class="text-wrap d-block" style="font-size: 0.8rem;">${mediaData.path || 'N/A'}</code>
                    </div>
                </div>
                
                <!-- Status -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Status</strong></div>
                    <div class="col-8">${fullData.on_disk ? 'Downloaded' : 'Missing'}</div>
                </div>
                
                <!-- Quality Profile -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Quality Profile</strong></div>
                    <div class="col-8">${quality}</div>
                </div>
                
                <!-- Size -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Size</strong></div>
                    <div class="col-8">${fileSize}</div>
                </div>
                
                <!-- Episodes Progress -->
                <div class="row mb-2">
                    <div class="col-4"><strong>Episodes</strong></div>
                    <div class="col-8">
                        ${downloadedEpisodes}/${totalEpisodes} (${completionPercent}% complete)
                        <div class="progress mt-1" style="height: 6px;">
                            <div class="progress-bar" role="progressbar" 
                                 style="width: ${completionPercent}%;" 
                                 aria-valuenow="${completionPercent}" 
                                 aria-valuemin="0" aria-valuemax="100">
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Genres -->
                ${mediaData.genres && mediaData.genres.length > 0 ? `
                <div class="row mb-2">
                    <div class="col-4"><strong>Genres</strong></div>
                    <div class="col-8">
                        ${mediaData.genres.map(genre => `<span class="badge bg-secondary me-1 mb-1">${genre}</span>`).join('')}
                    </div>
                </div>
                ` : ''}
                
                <!-- Rating -->
                ${mediaData.ratings?.value ? `
                <div class="row mb-2">
                    <div class="col-4"><strong>Rating</strong></div>
                    <div class="col-8">
                        <span class="badge bg-primary">${mediaData.ratings.value}/10</span>
                        ${mediaData.ratings.votes ? `<small class="text-muted ms-1">(${mediaData.ratings.votes} votes)</small>` : ''}
                    </div>
                </div>
                ` : ''}
            </div>
        </div>

        <!-- Seasons Section -->
        <div class="seasons-container mb-3">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6 class="mb-0">SEASONS</h6>
            </div>
            <div id="seasonsList">
                <div class="text-center text-muted p-4">
                    <div class="spinner-border spinner-border-sm mb-2" role="status"></div>
                    <p class="mb-0">Loading episodes...</p>
                </div>
            </div>
        </div>

        <!-- Overview Section -->
        ${mediaData.overview ? `
        <div class="card bg-dark border-secondary">
            <div class="card-header">
                <h6 class="mb-0">OVERVIEW</h6>
            </div>
            <div class="card-body">
                <p class="mb-0" style="font-size: 0.9rem; line-height: 1.4;">${mediaData.overview}</p>
            </div>
        </div>
        ` : ''}
    `;
    
    detailsContent.innerHTML = html;

    // Add event listeners to the new buttons
    attachButtonEventListeners();
    loadTVShowEpisodes(internalId);
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
                    <div class="flex-grow-1" style="min-width:0;">
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
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
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
    .then(response => response.json().then(data => ({ ok: response.ok, data })))
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
                <div class="card-header d-flex justify-content-between align-items-center"
                     id="${headingId}"
                     style="cursor:pointer;"
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
function showDetails(mediaType, mediaId, tmdb=false) {
    _pauseBackgroundFetches();
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
    modalTitle.textContent = `${mediaType === 'tv' ? 'TV Show' : mediaType === 'book' ? 'Book' : 'Movie'} Details`;
    
    document.getElementById('detailsContent').innerHTML = `
        <div class="text-center my-4">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;
    
    modal.show();
    
    // Only fetch internal data if NOT in TMDB-only mode
    const internalPromise = tmdb === false 
        ? fetch(`/get_media_details?type=${mediaType}&id=${mediaId}`)
            .then(response => response.json())
            .catch(error => {
                console.error('Internal API error:', error);
                return { error: 'Failed to load internal details' };
            })
        : Promise.resolve(null); // Skip entirely when tmdb=true
    
    // Books are handled above and return early; this only runs for movies and TV.
    // For TV shows fetch TMDB enrichment; movies rely on internal Radarr data.
    const tmdbPromise = mediaType === 'tv'
        ? fetch(`/get_tmdb_details?type=tv&id=${mediaId}`)
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
            const hasInternalData = tmdb === false && internalData && !internalData.error;

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
                        addDiv.className = 'mt-3';
                        addDiv.innerHTML = `<button class="btn btn-primary w-100" onclick="addItemFromModal('book', ${mediaId})">
                            <i class="fas fa-book me-1"></i>Add to Readarr
                        </button>`;
                        document.getElementById('detailsContent').appendChild(addDiv);
                    }
                } else {
                    document.getElementById('detailsContent').innerHTML = '<div class="alert alert-warning">Book details not available. Check Readarr connection.</div>';
                }
                return;
            }

            // If in TMDB-only mode, use ONLY TMDB data
            if (tmdb === true) {
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
                        class="img-fluid h-100 object-fit-cover"
                        alt="${title} poster"
                        onerror="this.onerror=null; this.src='/static/images/logo.png'"
                        style="background-color: #2c3e50; background-image: url('/static/images/logo.png'); background-size: 60%; background-position: center; background-repeat: no-repeat;">`;

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
                                
                                <p class="mb-3" style="line-height: 1.5;">${overview}</p>

                                <div class="mt-3">
                                    <button class="btn btn-primary w-100" 
                                            id="modalAddButton"
                                            onclick="addItemFromModal('${mediaType}', ${mediaId})">
                                        Add to ${mediaType === 'tv' ? 'Sonarr' : mediaType === 'book' ? 'Readarr' : 'Radarr'}
                                    </button>
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
                        class="img-fluid h-100 object-fit-cover"
                        alt="${title} poster"
                        onerror="this.onerror=null; this.src='/static/images/logo.png'"
                        style="background-color: #2c3e50; background-image: url('/static/images/logo.png'); background-size: 60%; background-position: center; background-repeat: no-repeat;">`;
                
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
                                
                                <p class="mb-3" style="line-height: 1.5;">${overview}</p>
                                
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
                                        : `<button class="btn btn-primary w-100" id="modalAddButton"
                                                onclick="addItemFromModal('${mediaType}', ${mediaId})">
                                               Add to ${mediaType === 'tv' ? 'Sonarr' : mediaType === 'book' ? 'Readarr' : 'Radarr'}
                                           </button>`
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
          if (monitored && hasMissing) {
            const mType = this.dataset.type;
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
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
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

    function performAddFromModal(mediaType, mediaId, qualityProfileId=null, seasonFilter='latest') {
        const btn = document.getElementById('modalAddButton');
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
        alert(`Addarr has been updated to version ${updateData.latest_version}! Some changes may require a page refresh.`);
        
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
                            <h6 class="alert-heading">Addarr has been updated!</h6>
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
    let configPanel = document.getElementById('configModal');
    fetch('/api/update/list')
        .then(response => response.json())
        .then(data => {
            configPanel.classList.remove('open');
            configOverlay.classList.remove('open');
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
class LoadingSpinner {
    constructor() {
        this.spinner = document.getElementById('globalLoadingSpinner');
        this.message = document.getElementById('loadingMessage');
        this.init();
    }

    init() {
        // Create spinner if it doesn't exist
        if (!this.spinner) {
            this.createSpinner();
        }
        
        // Set up event listeners for PWA compatibility
        this.setupEventListeners();
    }

    createSpinner() {
        const spinnerHTML = `
            <div id="globalLoadingSpinner" class="loading-spinner">
                <div class="spinner-container">
                    <div class="spinner-border spinner-radarr" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <p class="mt-2 mb-0" id="loadingMessage">Loading...</p>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', spinnerHTML);
        this.spinner = document.getElementById('globalLoadingSpinner');
        this.message = document.getElementById('loadingMessage');
    }

    setupEventListeners() {
        // Multiple ways to detect when page is ready in PWA
        document.addEventListener('DOMContentLoaded', () => this.hide());
        window.addEventListener('load', () => this.hide());
        
        // For single page app behavior in PWA
        window.addEventListener('pageshow', (event) => {
            if (event.persisted) {
                // Page was restored from cache (PWA behavior)
                this.hide();
            }
        });

        // Safety timeout - always hide after 15 seconds max
        setTimeout(() => this.hide(), 15000);
    }

    show(message = 'Loading...') {
        if (this.spinner && this.message) {
            this.message.textContent = message;
            this.spinner.classList.add('show');
            document.body.style.overflow = 'hidden';
            
            // Auto-hide safety for PWA (in case page doesn't trigger load events)
            setTimeout(() => {
                if (this.spinner.classList.contains('show')) {
                    console.warn('Loading spinner timeout - forcing hide');
                    this.hide();
                }
            }, 10000); // 10 second safety timeout
        }
    }

    hide() {
        if (this.spinner) {
            this.spinner.classList.remove('show');
            document.body.style.overflow = '';
        }
    }
}

// Form submission handlers
document.addEventListener('DOMContentLoaded', function() {

    window.spinner = new LoadingSpinner();
    
    // Set up navigation and form handlers
    setupNavigationHandlers();
    
    // Initial hide to ensure it's not stuck
    setTimeout(() => window.spinner.hide(), 1000);


    // Handle search form submissions
    const searchForms = document.querySelectorAll('form[action*="search"]');
    searchForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            spinner.show('Searching...');
        });
    });

    // Handle navigation clicks
    const navLinks = document.querySelectorAll('a[href]:not([target="_blank"])');
    navLinks.forEach(link => {
        if (link.getAttribute('href') && !link.getAttribute('href').startsWith('#')) {
            link.addEventListener('click', function(e) {
                // Don't show spinner for same-page anchors
                if (!this.getAttribute('href').startsWith('#')) {
                    spinner.show('Loading page...');
                }
            });
        }
    });

    // Handle manage page item clicks
    const manageItems = document.querySelectorAll('.media-item, .result-item');
    manageItems.forEach(item => {
        item.addEventListener('click', function() {
            spinner.show('Loading details...');
        });
    });

    // Hide spinner when page is fully loaded
    window.addEventListener('load', () => {
        setTimeout(() => spinner.hide(), 500);
    });

    // Also hide spinner if there's an error
    window.addEventListener('error', () => spinner.hide());
});

function setupNavigationHandlers() {
    const spinner = window.spinner;
    
    // Handle form submissions
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const action = this.getAttribute('action') || '';
            let message = 'Processing...';
            
            if (action.includes('search')) {
                message = 'Searching...';
            }
            
            spinner.show(message);
        });
    });

    // Handle navigation clicks - but only for same-origin links
    const links = document.querySelectorAll('a[href]:not([target="_blank"])');
    links.forEach(link => {
        const href = link.getAttribute('href');
        
        // Only handle links that navigate to new pages (not anchors or javascript)
        if (href && !href.startsWith('#') && !href.startsWith('javascript:')) {
            link.addEventListener('click', function(e) {
                // Don't intercept if it's the same page or has special handlers
                if (this.getAttribute('href') !== window.location.pathname) {
                    spinner.show('Loading...');
                    
                    // For PWA, also set up a timeout to hide if navigation doesn't happen
                    setTimeout(() => {
                        // If we're still on the same page after 2 seconds, hide spinner
                        if (window.location.pathname === new URL(this.href, window.location.origin).pathname) {
                            spinner.hide();
                        }
                    }, 2000);
                }
            });
        }
    });

    // Handle manage page item clicks
    const manageItems = document.querySelectorAll('.media-item, .result-item, .search-result-card');
    manageItems.forEach(item => {
        item.addEventListener('click', function() {
            spinner.show('Loading details...');
            
            // Safety timeout for modal loads
            setTimeout(() => spinner.hide(), 5000);
        });
    });

    // Listen for modal events to hide spinner when modals open
    document.addEventListener('show.bs.modal', () => {
        spinner.hide();
    });

    // Listen for AJAX completion (if using fetch/XHR)
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        const promise = originalFetch.apply(this, args);
        promise.finally(() => {
            setTimeout(() => spinner.hide(), 100);
        });
        return promise;
    };
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
                    window.spinner.hide();
                }
            });
        }

        // Handle beforeunload for page transitions
        window.addEventListener('beforeunload', () => {
            window.spinner.show('Loading...');
        });

        // Handle page restoration from cache (PWA behavior)
        window.addEventListener('pageshow', (event) => {
            if (event.persisted) {
                // Page was restored from bfcache
                setTimeout(() => window.spinner.hide(), 100);
            }
        });

        // Add manual close button as fallback
        const forceCloseBtn = document.getElementById('forceCloseSpinner');
        if (forceCloseBtn) {
            forceCloseBtn.addEventListener('click', () => {
                window.spinner.hide();
            });
            
            // Show close button after 8 seconds if spinner is still visible
            setInterval(() => {
                const spinner = document.getElementById('globalLoadingSpinner');
                if (spinner && spinner.classList.contains('show')) {
                    forceCloseBtn.style.display = 'block';
                }
            }, 8000);
        }
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
        showManageDetails(mediaType, internalId);
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
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
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
    const currentFilter = document.getElementById('mediaFilter').value;
    const availabilityFilter = document.getElementById('availabilityFilter');
    const availabilityValue = availabilityFilter ? availabilityFilter.value : 'all';
    
    document.querySelectorAll('.media-item').forEach(item => {
        const title = item.dataset.title;
        const isMovie = item.classList.contains('movie-item');
        const isTV = item.classList.contains('tv-item');
        const isBook = item.classList.contains('book-item');

        const matchesSearch = searchTerm === '' || title.includes(searchTerm);
        const matchesFilter = currentFilter === 'all' ||
                            (currentFilter === 'movie' && isMovie) ||
                            (currentFilter === 'tv' && isTV) ||
                            (currentFilter === 'book' && isBook);
        const matchesAvailability = availabilityValue === 'all' ||
                            (availabilityValue === 'movie_missing_file' && isMovie && item.dataset.missingFiles === 'true') ||
                            (availabilityValue === 'tv_missing_episodes' && isTV && item.dataset.missingEpisodes === 'true');

        item.style.display = (matchesSearch && matchesFilter && matchesAvailability) ? 'block' : 'none';
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


