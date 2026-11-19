// main.js — shared vanilla JS for all pages.

// Render Lucide icons (<i data-lucide="...">). Guarded so pages still work
// if the CDN script fails to load.
document.addEventListener('DOMContentLoaded', function () {
    if (window.lucide) {
        window.lucide.createIcons();
    }
});
