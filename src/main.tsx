import React from 'react';
import { createRoot, hydrateRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

const container = document.getElementById('root')!;
const app = (
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);

// Prerendered pages ship real HTML for their own route; hydrate it.
// If the fallback served another route's HTML (e.g. /admin gets the home
// shell from Pages' SPA fallback), discard it and render fresh.
const ssrPath = container.getAttribute('data-ssr');
const here = window.location.pathname.replace(/\/+$/, '') || '/';
if (container.hasChildNodes() && ssrPath === here) {
  hydrateRoot(container, app);
} else {
  container.replaceChildren();
  createRoot(container).render(app);
}
