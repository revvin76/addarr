let deferredPrompt;
const installButton = document.getElementById('install-button'); // Add this button to your HTML

window.addEventListener('beforeinstallprompt', (e) => {
  // Prevent the mini-infobar from appearing on mobile
  e.preventDefault();
  // Stash the event so it can be triggered later
  deferredPrompt = e;
  
  // Show your custom install promotion
  if (installButton) {
    installButton.style.display = 'block';
    installButton.addEventListener('click', async () => {
      // Hide our install promotion
      installButton.style.display = 'none';
      // Show the install prompt
      deferredPrompt.prompt();
      // Wait for the user to respond to the prompt
      const { outcome } = await deferredPrompt.userChoice;
      // Optionally, send analytics about user's choice
      console.log(`User response to the install prompt: ${outcome}`);
      // We've used the prompt, and can't use it again
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

