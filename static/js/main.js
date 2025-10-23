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
    
    // Get poster image
    const posterImage = mediaData.images?.find(img => img.coverType === 'poster');
    const posterUrl = posterImage?.remoteUrl || posterImage?.url || '/static/images/favicon.png';
    
    // Create HTML content based on the data
    let html = `
        <div class="row">
            <div class="col-md-4">
                <img src="${posterUrl}" 
                     class="img-fluid rounded mb-3" 
                     alt="${mediaData.title}"
                     onerror="this.src='/static/images/favicon.png'">
                
                <div class="d-grid gap-2">
                    <button class="btn ${data.monitored ? 'btn-warning' : 'btn-success'} monitor-toggle" 
                            data-type="${mediaType}" 
                            data-id="${internalId}"
                            data-monitored="${data.monitored}">
                        ${data.monitored ? 'Unmonitor' : 'Monitor'}
                    </button>
                    <button class="btn btn-primary search-btn" 
                            data-type="${mediaType}" 
                            data-id="${internalId}">
                        <i class="fas fa-search me-1"></i> Search
                    </button>
                    <button class="btn btn-danger delete-btn" 
                            data-type="${mediaType}" 
                            data-id="${internalId}">
                        <i class="fas fa-trash me-1"></i> Delete
                    </button>
                </div>
            </div>
            <div class="col-md-8">
                <h3>${mediaData.title || 'Unknown Title'}</h3>
                <p class="text-muted">${mediaData.year || ''} • ${mediaType === 'movie' ? 'Movie' : 'TV Show'}</p>
                
                <div class="mb-3">
                    <strong>Status:</strong> 
                    <span class="badge ${data.monitored ? 'bg-success' : 'bg-secondary'}">
                        ${data.monitored ? 'Monitored' : 'Not Monitored'}
                    </span>
                    <span class="badge ${data.on_disk ? 'bg-success' : 'bg-warning'} ms-1">
                        ${data.on_disk ? 'Downloaded' : 'Not Downloaded'}
                    </span>
                    ${mediaData.status ? `<span class="badge bg-info ms-1">${mediaData.status}</span>` : ''}
                </div>
                
                ${mediaData.overview ? `<p class="mb-3">${mediaData.overview}</p>` : ''}
                
                ${mediaData.genres && mediaData.genres.length > 0 ? `
                    <div class="mb-3">
                        <strong>Genres:</strong> 
                        ${mediaData.genres.map(genre => `<span class="badge bg-secondary me-1">${genre}</span>`).join('')}
                    </div>
                ` : ''}
                
                ${mediaData.certification ? `
                    <div class="mb-3">
                        <strong>Certification:</strong> 
                        <span class="badge bg-dark">${mediaData.certification}</span>
                    </div>
                ` : ''}
                
                ${mediaData.ratings?.value ? `
                    <div class="mb-3">
                        <strong>Rating:</strong> 
                        <span class="badge bg-primary">${mediaData.ratings.value}/10</span>
                        ${mediaData.ratings.votes ? `<small class="text-muted ms-1">(${mediaData.ratings.votes} votes)</small>` : ''}
                    </div>
                ` : ''}
                
                ${mediaData.runtime ? `
                    <div class="mb-3">
                        <strong>Runtime:</strong> ${mediaData.runtime} minutes
                    </div>
                ` : ''}
                
                ${mediaData.network ? `
                    <div class="mb-3">
                        <strong>Network:</strong> ${mediaData.network}
                    </div>
                ` : ''}
                
                ${mediaData.added ? `
                    <div class="mb-3">
                        <strong>Added:</strong> ${new Date(mediaData.added).toLocaleDateString()}
                    </div>
                ` : ''}
                
                ${mediaData.path ? `
                    <div class="mb-3">
                        <strong>Path:</strong> <code>${mediaData.path}</code>
                    </div>
                ` : ''}
                
                ${mediaType === 'tv' ? `
                    <div class="mb-3">
                        <strong>Seasons:</strong> ${mediaData.seasonCount || mediaData.statistics?.seasonCount || 0}
                    </div>
                    <div class="mb-3">
                        <strong>Episodes:</strong> ${mediaData.episode_count || mediaData.statistics?.episodeCount || 0} 
                        (${mediaData.download_status || mediaData.statistics?.percentOfEpisodes || 0}% complete)
                    </div>
                    
                    ${mediaData.seasons && mediaData.seasons.length > 0 ? `
                        <div class="mt-4">
                            <h5>Seasons</h5>
                            <div class="accordion" id="seasonsAccordion">
                                ${mediaData.seasons.map((season, index) => `
                                    <div class="accordion-item">
                                        <h2 class="accordion-header" id="heading${index}">
                                            <button class="accordion-button ${index > 0 ? 'collapsed' : ''}" type="button" 
                                                    data-bs-toggle="collapse" data-bs-target="#collapse${index}" 
                                                    aria-expanded="${index === 0 ? 'true' : 'false'}" 
                                                    aria-controls="collapse${index}">
                                                Season ${season.seasonNumber} 
                                                <span class="badge ${season.statistics.percentOfEpisodes === 100 ? 'bg-success' : 'bg-warning'} ms-2">
                                                    ${season.statistics.episodeFileCount}/${season.statistics.episodeCount} episodes
                                                </span>
                                            </button>
                                        </h2>
                                        <div id="collapse${index}" class="accordion-collapse collapse ${index === 0 ? 'show' : ''}" 
                                             aria-labelledby="heading${index}" data-bs-parent="#seasonsAccordion">
                                            <div class="accordion-body">
                                                ${season.statistics.episodeCount > 0 ? `
                                                    <p>Episodes: ${season.statistics.episodeFileCount}/${season.statistics.episodeCount} downloaded</p>
                                                    <div class="progress mb-3">
                                                        <div class="progress-bar" role="progressbar" 
                                                             style="width: ${season.statistics.percentOfEpisodes}%;" 
                                                             aria-valuenow="${season.statistics.percentOfEpisodes}" 
                                                             aria-valuemin="0" aria-valuemax="100">
                                                            ${season.statistics.percentOfEpisodes}%
                                                        </div>
                                                    </div>
                                                ` : '<p>No episodes in this season</p>'}
                                            </div>
                                        </div>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    ` : ''}
                ` : ''}
            </div>
        </div>`;
    
    detailsContent.innerHTML = html;
    
    // Add event listeners to the new buttons
    attachButtonEventListeners();
}

// --- Episode actions ---
function deleteEpisode(id) {
  if (!confirm('Delete this episode file?')) return;
  fetch(`/api/episode/${id}`, { method: 'DELETE' })
    .then(r => r.ok ? location.reload() : alert('Failed'))
    .catch(() => alert('Failed to delete episode'));
}

function searchEpisode(id) {
  fetch(`/api/episode/${id}/search`, { method: 'POST' })
    .then(r => r.ok ? alert('Search started') : alert('Failed'))
    .catch(() => alert('Search failed'));
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
// Version Control Functions
async function loadVersionInfo() {
    try {
        // Get current version
        const currentVer = await fetch('/api/version').then(res => res.json());
        document.getElementById('current-version').textContent = currentVer.hash || 'Unknown';
        
        // Get latest version
        const latestVer = await fetch('/api/version/latest').then(res => res.json());
        document.getElementById('latest-version').textContent = latestVer.tag_name || 'Unknown';
        
        // Update button state
        const updateBtn = document.getElementById('update-now');
        if (latestVer.tag_name && currentVer.hash) {
            updateBtn.disabled = latestVer.tag_name === currentVer.hash;
        }
    } catch (error) {
        console.error('Version check failed:', error);
    }
}

// Auto-update toggle
// document.getElementById('auto-update-toggle').addEventListener('change', function() {
//     fetch('/api/settings', {
//         method: 'POST',
//         headers: {'Content-Type': 'application/json'},
//         body: JSON.stringify({auto_update: this.checked})
//     });
// });

// // Manual update
// document.getElementById('update-now').addEventListener('click', async function() {
//     const btn = this;
//     btn.disabled = true;
//     btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Updating...';
    
//     try {
//         const response = await fetch('/api/update', {method: 'POST'});
//         if (response.ok) {
//             alert('Update successful! The app will reload.');
//             setTimeout(() => location.reload(), 2000);
//         } else {
//             throw new Error('Update failed');
//         }
//     } catch (error) {
//         alert('Update failed: ' + error.message);
//         btn.disabled = false;
//         btn.innerHTML = '<i class="bi bi-cloud-arrow-down-fill"></i> Update Now';
//     }
// });


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

