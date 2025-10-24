let currentShowId = null; // track show id for delete/search actions
let deferredPrompt;
let player = null;
const installButton = document.getElementById('install-button'); // Add this button to your HTML

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

function addItem(mediaType, mediaId) {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Adding...';
    
    fetch('/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ media_type: mediaType, media_id: mediaId })
    })
    .then(response => response.json())
    .then(data => {
        alert(data.success ? 'Added successfully!' : 'Error adding item');
        btn.disabled = false;
        btn.textContent = `Add to ${mediaType === 'tv' ? 'Sonarr' : 'Radarr'}`;
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error adding item');
        btn.disabled = false;
        btn.textContent = `Add to ${mediaType === 'tv' ? 'Sonarr' : 'Radarr'}`;
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
    modalTitle.textContent = `${mediaType === 'tv' ? 'TV Show' : 'Movie'} Details`;
    
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
    } else {
        renderTVDetails(mediaData, data, mediaType, internalId);
    }
}

function renderMovieDetails(mediaData, fullData, mediaType, internalId) {
    const detailsContent = document.getElementById('detailsContent');
    
    // Get poster image
    const posterImage = mediaData.images?.find(img => img.coverType === 'poster');
    const posterUrl = posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png';
    
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
                <div class="d-grid gap-2 d-flex">
                    <button class="btn ${fullData.monitored ? 'btn-warning' : 'btn-success'} flex-fill monitor-toggle" 
                            data-type="${mediaType}" 
                            data-id="${internalId}"
                            data-monitored="${fullData.monitored}">
                        ${fullData.monitored ? 'Unmonitor' : 'Monitor'}
                    </button>
                    <button class="btn btn-primary flex-fill search-btn" 
                            data-type="${mediaType}" 
                            data-id="${internalId}">
                        <i class="fas fa-search me-1"></i> Search
                    </button>
                    <button class="btn btn-danger flex-fill delete-btn" 
                            data-type="${mediaType}" 
                            data-id="${internalId}">
                        <i class="fas fa-trash me-1"></i> Delete
                    </button>
                </div>
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
    const posterUrl = posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png';
    
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
                <div class="d-grid gap-2 d-flex">
                    <button class="btn ${fullData.monitored ? 'btn-warning' : 'btn-success'} flex-fill monitor-toggle" 
                            data-type="${mediaType}" 
                            data-id="${internalId}"
                            data-monitored="${fullData.monitored}">
                        ${fullData.monitored ? 'Unmonitor' : 'Monitor'}
                    </button>
                    <button class="btn btn-primary flex-fill search-btn" 
                            data-type="${mediaType}" 
                            data-id="${internalId}">
                        <i class="fas fa-search me-1"></i> Search
                    </button>
                    <button class="btn btn-danger flex-fill delete-btn" 
                            data-type="${mediaType}" 
                            data-id="${internalId}">
                        <i class="fas fa-trash me-1"></i> Delete
                    </button>
                </div>
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
                <button class="btn btn-sm btn-outline-primary" id="loadEpisodesBtn" data-series-id="${internalId}">
                    <i class="fas fa-sync-alt me-1"></i> Load Episodes
                </button>
            </div>
            <div id="seasonsList">
                <!-- Seasons will be loaded here when user clicks the button -->
                <div class="text-center text-muted p-4">
                    <i class="fas fa-tv fa-2x mb-2"></i>
                    <p>Click "Load Episodes" to view season details</p>
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
    
    // Add event listener for the load episodes button
    const loadEpisodesBtn = document.getElementById('loadEpisodesBtn');
    if (loadEpisodesBtn) {
        loadEpisodesBtn.addEventListener('click', function() {
            const seriesId = this.getAttribute('data-series-id');
            loadTVShowEpisodes(seriesId);
        });
    }
    
    // Add event listeners to the new buttons
    attachButtonEventListeners();
}

// New function to load episodes for TV shows
function loadTVShowEpisodes(seriesId) {
    const button = document.getElementById('loadEpisodesBtn');
    const seasonsList = document.getElementById('seasonsList');
    
    // Check if elements exist
    if (!button || !seasonsList) {
        console.error('Required elements not found');
        return;
    }
    
    // Show loading state
    button.disabled = true;
    button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Loading...';
    
    fetch(`/api/series/${seriesId}/seasons`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to fetch episodes');
            }
            return response.json();
        })
        .then(seasonsWithEpisodes => {
            renderSeasonCards(seasonsWithEpisodes);
            // Hide the button after successful load
            button.style.display = 'none';
        })
        .catch(error => {
            console.error('Error loading episodes:', error);
            seasonsList.innerHTML = `
                <div class="alert alert-danger">
                    Error loading episodes: ${error.message}
                    <button class="btn btn-sm btn-outline-danger ms-2" onclick="loadTVShowEpisodes(${seriesId})">Retry</button>
                </div>`;
            // Reset button
            button.disabled = false;
            button.innerHTML = '<i class="fas fa-sync-alt me-1"></i> Load Episodes';
        });
}

// Function to render season cards with episodes
function renderSeasonCards(seasonsWithEpisodes) {
    const container = document.getElementById('seasonsList');
    
    // Check if container exists
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
    
    const seasonsHtml = seasonsWithEpisodes.map(season => {
        return `
            <div class="card season-card mb-3">
                <div class="card-header">
                    <h6 class="mb-0">Season ${season.seasonNumber}</h6>
                </div>
                <div class="card-body p-0">
                    <div class="episode-list">
                        ${season.episodes && season.episodes.length > 0 ? 
                            season.episodes.map(episode => `
                                <div class="episode-item d-flex justify-content-between align-items-center ${episode.hasFile ? 'downloaded' : 'missing'}">
                                    <div class="flex-grow-1">
                                        <div class="d-flex justify-content-between align-items-start">
                                            <div>
                                                <span class="episode-number">${episode.episodeNumber}</span>
                                                <span class="episode-title">Episode ${episode.episodeNumber}</span>
                                                ${episode.title && episode.title !== `Episode ${episode.episodeNumber}` ? 
                                                    `<small class="text-muted d-block">${episode.title}</small>` : ''}
                                            </div>
                                            <div class="episode-date">${formatEpisodeDate(episode.airDate)}</div>
                                        </div>
                                    </div>
                                    <div class="episode-actions ms-2">
                                        ${episode.hasFile ? 
                                            `<button class="btn btn-sm btn-danger delete-episode-btn" 
                                                data-episode-id="${episode.id}"
                                                title="Delete episode file">
                                                <i class="fas fa-trash"></i>
                                            </button>` :
                                            `<button class="btn btn-sm btn-primary search-episode-btn" 
                                                data-episode-id="${episode.id}"
                                                title="Search for episode">
                                                <i class="fas fa-search"></i>
                                            </button>`
                                        }
                                    </div>
                                </div>
                            `).join('') : 
                            '<div class="episode-item text-center p-2">No episodes available</div>'
                        }
                    </div>
                </div>
            </div>
        `;
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

function showDetails(mediaType, mediaId) {
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
    });
            
    modalEl.removeAttribute('aria-hidden');
    modalTitle.textContent = `${mediaType === 'tv' ? 'TV Show' : 'Movie'} Details`;    
    
    document.getElementById('detailsContent').innerHTML = `
        <div class="text-center my-4">
            <div class="spinner-border" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
        </div>`;
    
    modal.show();
    
    // Fetch our internal details and TMDB details in parallel
    const internalPromise = fetch(`/get_media_details?type=${mediaType}&id=${mediaId}`)
        .then(response => response.json())
        .catch(error => {
            console.error('Internal API error:', error);
            return { error: 'Failed to load internal details' };
        });
    
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
            
            const data = internalData.data || internalData;
            const hasTmdbData = tmdbData && !tmdbData.error;
            
            // Determine poster URL
            let posterUrl;
            if (mediaType === 'movie') {
                const posterImage = data.images?.find(img => img.coverType === 'poster');
                posterUrl = posterImage?.remoteUrl || posterImage?.url;
            } else {
                const posterImage = data.images?.find(img => img.coverType === 'poster');
                posterUrl = posterImage?.remoteUrl || posterImage?.url ||
                        (tmdbData?.poster_path ? `https://image.tmdb.org/t/p/original${tmdbData.poster_path}` : null);
            }

            // Use logo as fallback if no poster available
            if (!posterUrl || posterUrl.includes('placeholder.com')) {
                posterUrl = '/static/images/logo.png';
            }

            // Then in your HTML generation for the modal:
            const title = data.title || (hasTmdbData ? tmdbData.title : 'No Title');            
            const posterHtml = `
                <img src="${posterUrl}" 
                    class="img-fluid h-100 object-fit-cover" 
                    alt="${title} poster"
                    onerror="this.onerror=null; this.src='/static/images/logo.png'"
                    style="background-color: #2c3e50; background-image: url('/static/images/logo.png'); background-size: 60%; background-position: center; background-repeat: no-repeat;">`;
            
            const year = data.year || (hasTmdbData && tmdbData.first_air_date 
                ? new Date(tmdbData.first_air_date).getFullYear() 
                : 'N/A');
            const overview = data.overview || (hasTmdbData ? tmdbData.overview : 'No overview available');
            const genres = (data.genres && data.genres.length) 
                ? data.genres 
                : (hasTmdbData ? tmdbData.genres : []);
            const rating = hasTmdbData 
                ? tmdbData.vote_average?.toFixed(1) 
                : (data.ratings?.imdb?.value || data.ratings?.tmdb?.value || 'N/A');
            const status = data.ended 
                ? 'Ended' 
                : (hasTmdbData && tmdbData.status === 'Ended' ? 'Ended' : 'Current');
            
            // Determine trailer
            let trailerHtml = '';
            let trailerKey = null;

            if (hasTmdbData) {
                // First try the direct trailer field
                const trailer = tmdbData.trailer || 
                    // Then look in videos array
                    (tmdbData.videos && tmdbData.videos.find(v => 
                        v.site === 'YouTube' && 
                        v.type === 'Trailer' &&
                        // Prefer official trailers but fallback to any
                        (v.official === true || tmdbData.trailer === null)
                    ));

                if (trailer) {
                    trailerKey = trailer.key;
                    trailerHtml = `
                        <div class="mt-4">
                            <h5>Trailer</h5>
                            <div id="trailerPlayer"></div>
                            ${trailer.official ? '' : '<p class="small">Official trailer</p>'}
                        </div>`;
                }
            } else if (data.youTubeTrailerId) {
                // Fallback to internal trailer ID if TMDB fails
                trailerKey = data.youTubeTrailerId;
                trailerHtml = `
                    <div class="mt-4">
                        <h5>Trailer</h5>
                        <div id="trailerPlayer"></div>
                        ${data.youTubeTrailerId ? '' : '<p class="small">Unofficial trailer</p>'}
                    </div>`;
            }
        
            if (trailerKey) {
                currentTrailerKey = trailerKey;
                setTimeout(() => {
                    player = new YT.Player('trailerPlayer', {
                        height: '315',
                        width: '100%',
                        videoId: trailerKey,
                        playerVars: {
                            'autoplay': 0,
                            'controls': 1,
                            'rel': 0
                        }
                    });
                }, 100);
            }

            // Determine available images from both TMDB and internal sources
            let imagesHtml = '';
            const allImages = [];

            // Add internal images first
            if (data.images && data.images.length > 0) {
                data.images.forEach(image => {
                    if (image.remoteUrl) {
                        allImages.push({
                            url: image.remoteUrl,
                            type: image.coverType || 'unknown'
                        });
                    }
                });
            }

            // Add TMDB images if available
            if (hasTmdbData && tmdbData.images && tmdbData.images.posters) {
                tmdbData.images.posters.slice(0, 10).forEach(poster => {
                    allImages.push({
                        url: `https://image.tmdb.org/t/p/w300${poster.file_path}`,
                        fullUrl: `https://image.tmdb.org/t/p/original${poster.file_path}`,
                        type: 'poster'
                    });
                });
            }

            if (hasTmdbData && tmdbData.images && tmdbData.images.backdrops) {
                tmdbData.images.backdrops.slice(0, 10).forEach(backdrop => {
                    allImages.push({
                        url: `https://image.tmdb.org/t/p/w300${backdrop.file_path}`,
                        fullUrl: `https://image.tmdb.org/t/p/original${backdrop.file_path}`,
                        type: 'backdrop'
                    });
                });
            }

            // Create HTML if we have images
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

            const alreadyAdded = internalData.status === 'existing';

            // Build the HTML
            const html = `
                <div class="row g-0 h-100">
                    <div class="col-md-5 px-2">
                        <img src="${posterUrl}" 
                            class="poster img-fluid h-100 object-fit-cover" 
                            alt="${title} poster"
                            onerror="this.src='https://via.placeholder.com/500x750?text=Poster+Not+Available'">
                    </div>
                    
                    <div class="col-md-7 px-3">
                        <h1 class="display-6 mb-2 fw-bold">${title}</h1>
                        
                        <div class="d-flex align-items-center flex-wrap gap-3 mb-3">
                            ${year ? `<span class="text-light">${year}</span>` : ''}
                            <span class="certification-badge bg-dark text-white px-2 rounded">
                                ${data.certification || data.mpaaRating || 'NR'}
                            </span>
                            ${mediaType === 'tv' ? `
                            <span class="certification-badge bg-dark text-white px-2 rounded">
                                ${status}
                            </span>` : ''}
                            ${rating !== 'N/A' ? `
                            <span class="text-light">⭐ ${rating}/10</span>` : ''}
                        </div>
                        
                        <div class="d-flex flex-wrap gap-2 mb-4">
                            ${genres.slice(0, 4).map(genre => `
                                <span class="badge bg-secondary">${genre}</span>
                            `).join('')}
                        </div>
                        
                        <p class="mb-4">${overview}</p>
                        
                        <div class="row g-2 mb-4">
                            ${data.statistics?.seasonCount ? `
                                <span class="badge bg-success">
                                    Seasons: ${data.statistics.seasonCount}
                                </span>` : ''}
                            <div class="col-auto">
                                <span class="badge ${internalData.status === 'existing' ? 'bg-success' : 'bg-warning'}">
                                    ${internalData.status === 'existing' ? 'In Library' : 'Not Added'}
                                </span>
                            </div>
                            ${internalData.on_disk !== undefined ? `
                            <div class="col-auto">
                                <span class="badge ${internalData.on_disk ? 'bg-success' : 'bg-secondary'}">
                                    ${internalData.on_disk ? 'Downloaded' : 'Not Downloaded'}
                                </span>
                            </div>
                            ` : ''}
                        </div>

                        <div class="mt-4">
                            <button class="btn ${alreadyAdded ? 'btn-success' : 'btn-primary'} w-100" 
                                    id="modalAddButton"
                                    onclick="${alreadyAdded ? '' : `addItemFromModal('${mediaType}', ${mediaId})`}"
                                    ${alreadyAdded ? 'disabled' : ''}>
                                ${alreadyAdded ? '✓ Already in Library' : `Add to ${mediaType === 'tv' ? 'Sonarr' : 'Radarr'}`}
                            </button>
                        </div>

                        ${trailerHtml}
                        ${imagesHtml}
                    </div>
                </div>`;
            
            document.getElementById('detailsContent').innerHTML = html;
            modal.show();
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

function deleteEpisode(episodeId) {
    if (!confirm('Delete this episode file?')) return;
    fetch(`/api/episode/${episodeId}`, { method: 'DELETE' })
        .then(res => {
            if (res.ok) {
                alert('Episode deleted');
                location.reload();
            } else throw new Error();
        })
        .catch(() => alert('Failed to delete episode'));
}

function searchEpisode(episodeId) {
    fetch(`/api/episode/${episodeId}/search`, { method: 'POST' })
        .then(res => {
            if (res.ok) alert('Search started');
            else throw new Error();
        })
        .catch(() => alert('Search failed'));
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
  // Delete Show button
  document.getElementById('deleteShowBtn')?.addEventListener('click', () => {
    if (!currentShowId) return;
    if (confirm('Delete the entire show?')) {
      fetch(`/api/tv/${currentShowId}`, { method: 'DELETE' })
        .then(r => r.ok ? location.reload() : alert('Failed to delete show'));
    }
  });

  // Delete All Files button
  document.getElementById('deleteAllFilesBtn')?.addEventListener('click', () => {
    if (!currentShowId) return;
    if (confirm('Delete all files for this show?')) {
      fetch(`/api/tv/${currentShowId}/files`, { method: 'DELETE' })
        .then(r => r.ok ? alert('All files deleted') : alert('Failed to delete files'));
    }
  });

  // Search All Missing button
  document.getElementById('searchAllMissingBtn')?.addEventListener('click', () => {
    if (!currentShowId) return;
    fetch(`/api/tv/${currentShowId}/search_missing`, { method: 'POST' })
      .then(r => r.ok ? alert('Search started') : alert('Failed to search'));
  });
}

    function addItemFromModal(mediaType, mediaId) {
        const btn = document.getElementById('modalAddButton');
        const originalText = btn.innerHTML;
        
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Adding...`;
        
        fetch('/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ media_type: mediaType, media_id: mediaId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                btn.className = 'btn btn-success w-100';
                btn.innerHTML = '✓ Added Successfully';
                btn.disabled = true; // Disable button after successful addition
                // Update status badge if visible
                updateStatusInCard(mediaType, mediaId);
            } else {
                btn.className = 'btn btn-danger w-100';
                btn.innerHTML = 'Error Adding';
            }
            setTimeout(() => {
                btn.className = 'btn btn-primary w-100';
                btn.innerHTML = originalText;
                btn.disabled = false;
            }, 3000);
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
        // Fallback: show a simple alert
        alert(`Addarr has been updated to version ${updateData.latest_version}! Some changes may require a page refresh.`);
        
        // Still dismiss the notification
        fetch('/api/update/dismiss', { method: 'POST' })
            .catch(error => console.error('Error dismissing update notification:', error));
        return;
    }

    const modalHtml = `
        <div class="modal fade" id="updateAppliedModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header bg-success text-white">
                        <h5 class="modal-title">
                            <i class="fas fa-check-circle me-2"></i>
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
                    <div class="modal-footer">
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
    modal.show();
    
    // Dismiss the notification so it doesn't show again
    fetch('/api/update/dismiss', { method: 'POST' })
        .catch(error => console.error('Error dismissing update notification:', error));
    
    // Remove modal from DOM when hidden
    document.getElementById('updateAppliedModal').addEventListener('hidden.bs.modal', function() {
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
    let configPanel = document.getElementById('configPanel');
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
