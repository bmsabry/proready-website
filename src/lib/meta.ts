import { useEffect } from 'react';

const SITE = 'ProReadyEngineer LLC';

/** Per-page document title + meta description (SPA-friendly SEO). */
export function usePageMeta(title: string, description?: string) {
  useEffect(() => {
    document.title = title ? `${title} | ${SITE}` : `${SITE} | Gas Turbine Combustion, Thermal Fluid Sciences & Industrial AI`;
    if (description) {
      let tag = document.querySelector('meta[name="description"]');
      if (!tag) {
        tag = document.createElement('meta');
        tag.setAttribute('name', 'description');
        document.head.appendChild(tag);
      }
      tag.setAttribute('content', description);
    }
  }, [title, description]);
}
