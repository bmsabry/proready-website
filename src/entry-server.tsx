import React from 'react';
import { PassThrough } from 'node:stream';
import { renderToPipeableStream } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import App from './App';
import { collectSsrSeo, type PageSeo } from './lib/meta';

export { PRERENDER_ROUTES } from './routes';

/** Render one route to a full HTML string (waits for lazy chunks). */
export function render(url: string): Promise<{ html: string; seo: PageSeo | null }> {
  return new Promise((resolve, reject) => {
    const stream = renderToPipeableStream(
      <StaticRouter location={url}>
        <App />
      </StaticRouter>,
      {
        onAllReady() {
          const out = new PassThrough();
          let html = '';
          out.on('data', (chunk) => { html += chunk; });
          out.on('end', () => resolve({ html, seo: collectSsrSeo() }));
          stream.pipe(out);
        },
        onError(err) {
          reject(err);
        },
      }
    );
  });
}
