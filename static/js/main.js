let deferredPrompt;
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
document.getElementById('auto-update-toggle').addEventListener('change', function() {
    fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({auto_update: this.checked})
    });
});

// Manual update
document.getElementById('update-now').addEventListener('click', async function() {
    const btn = this;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Updating...';
    
    try {
        const response = await fetch('/api/update', {method: 'POST'});
        if (response.ok) {
            alert('Update successful! The app will reload.');
            setTimeout(() => location.reload(), 2000);
        } else {
            throw new Error('Update failed');
        }
    } catch (error) {
        alert('Update failed: ' + error.message);
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-cloud-arrow-down-fill"></i> Update Now';
    }
});

// Load settings on panel open
document.getElementById('configPanel').addEventListener('show.bs.collapse', function() {
    // Load current auto-update setting
    fetch('/api/settings')
        .then(res => res.json())
        .then(settings => {
            document.getElementById('auto-update-toggle').checked = settings.auto_update;
        });
    
    // Load version info
    loadVersionInfo();
});