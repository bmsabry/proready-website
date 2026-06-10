import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { ARTICLE_META } from './articleMeta';

const SITE = 'ProReadyEngineer LLC';
const ORIGIN = 'https://proreadyengineer.com';
const DEFAULT_TITLE = `${SITE} | Gas Turbine Combustion, Thermal Fluid Sciences & Industrial AI`;
const DEFAULT_IMAGE = `${ORIGIN}/Banner.png`;

export type PageSeo = {
  title: string;
  description: string;
  canonical: string;
  image: string;
  type: 'website' | 'article';
  noindex: boolean;
  jsonLd: object[];
};

/* During prerendering (SSR) the rendered page deposits its SEO data here;
   the prerender script collects it and bakes it into the static HTML head. */
let ssrSeo: PageSeo | null = null;
export function collectSsrSeo(): PageSeo | null {
  const s = ssrSeo;
  ssrSeo = null;
  return s;
}

const SECTION_NAMES: Record<string, string> = {
  'case-studies': 'Case Studies',
  insights: 'Research Insights',
  services: 'Services',
  training: 'Training',
};

function breadcrumbLd(pathname: string, pageTitle: string): object | null {
  const parts = pathname.split('/').filter(Boolean);
  if (parts.length < 2) return null;
  const section = SECTION_NAMES[parts[0]];
  if (!section) return null;
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: `${ORIGIN}/` },
      { '@type': 'ListItem', position: 2, name: section, item: `${ORIGIN}/${parts[0]}` },
      { '@type': 'ListItem', position: 3, name: pageTitle, item: ORIGIN + pathname },
    ],
  };
}

export type PageMetaOptions = {
  image?: string;
  jsonLd?: object | object[];
  noindex?: boolean;
  type?: 'website' | 'article';
};

/** Per-page document head management: title, description, canonical,
 *  Open Graph / Twitter tags, and JSON-LD. Works client-side and during
 *  build-time prerendering. */
export function usePageMeta(title: string, description?: string, opts?: PageMetaOptions) {
  const { pathname } = useLocation();

  const article = ARTICLE_META[pathname];
  const jsonLd: object[] = [];
  const crumbs = breadcrumbLd(pathname, title);
  if (crumbs) jsonLd.push(crumbs);
  if (article) {
    jsonLd.push({
      '@context': 'https://schema.org',
      '@type': 'TechArticle',
      headline: title,
      description: description ?? '',
      image: ORIGIN + article.image,
      datePublished: article.datePublished,
      author: { '@type': 'Organization', name: SITE, url: ORIGIN },
      publisher: {
        '@type': 'Organization',
        name: SITE,
        logo: { '@type': 'ImageObject', url: `${ORIGIN}/Logo.jpg` },
      },
      mainEntityOfPage: ORIGIN + pathname,
    });
  }
  if (opts?.jsonLd) jsonLd.push(...(Array.isArray(opts.jsonLd) ? opts.jsonLd : [opts.jsonLd]));

  const seo: PageSeo = {
    title: title ? `${title} | ${SITE}` : DEFAULT_TITLE,
    description: description ?? '',
    canonical: ORIGIN + (pathname === '/' ? '/' : pathname.replace(/\/+$/, '')),
    image: opts?.image ?? (article ? ORIGIN + article.image : DEFAULT_IMAGE),
    type: opts?.type ?? (article ? 'article' : 'website'),
    noindex: opts?.noindex ?? false,
    jsonLd,
  };

  if (import.meta.env.SSR) {
    ssrSeo = seo;
  }

  const key = JSON.stringify(seo);
  useEffect(() => {
    applyToDocument(JSON.parse(key) as PageSeo);
  }, [key]);
}

function upsertMeta(attr: 'name' | 'property', name: string, content: string) {
  let tag = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${name}"]`);
  if (!tag) {
    tag = document.createElement('meta');
    tag.setAttribute(attr, name);
    document.head.appendChild(tag);
  }
  tag.setAttribute('content', content);
}

function applyToDocument(seo: PageSeo) {
  document.title = seo.title;
  upsertMeta('name', 'description', seo.description);
  upsertMeta('property', 'og:title', seo.title);
  upsertMeta('property', 'og:description', seo.description);
  upsertMeta('property', 'og:url', seo.canonical);
  upsertMeta('property', 'og:image', seo.image);
  upsertMeta('property', 'og:type', seo.type);
  upsertMeta('name', 'twitter:title', seo.title);
  upsertMeta('name', 'twitter:description', seo.description);
  upsertMeta('name', 'twitter:image', seo.image);

  if (seo.noindex) {
    upsertMeta('name', 'robots', 'noindex,nofollow');
  } else {
    document.head.querySelector('meta[name="robots"]')?.remove();
  }

  let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement('link');
    canonical.setAttribute('rel', 'canonical');
    document.head.appendChild(canonical);
  }
  canonical.setAttribute('href', seo.canonical);

  document.head.querySelectorAll('script[data-seo-jsonld]').forEach((el) => el.remove());
  for (const ld of seo.jsonLd) {
    const s = document.createElement('script');
    s.type = 'application/ld+json';
    s.setAttribute('data-seo-jsonld', '');
    s.textContent = JSON.stringify(ld);
    document.head.appendChild(s);
  }
}
