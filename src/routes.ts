/**
 * Public routes that get prerendered to static HTML at build time and
 * listed in sitemap.xml. Admin routes are intentionally excluded.
 * Bump `lastmod` when a page's content meaningfully changes.
 */
export type RouteEntry = {
  path: string;
  lastmod: string;
  priority?: number;
  changefreq?: 'weekly' | 'monthly' | 'yearly';
};

const M = '2026-06-10'; // site-wide template update

export const PRERENDER_ROUTES: RouteEntry[] = [
  { path: '/', lastmod: M, priority: 1.0 },
  { path: '/services', lastmod: M, priority: 0.9 },
  { path: '/products', lastmod: '2026-08-04', priority: 0.9, changefreq: 'weekly' },
  { path: '/services/gas-turbine-combustion', lastmod: M, priority: 0.9 },
  { path: '/services/industrial-ai', lastmod: M, priority: 0.9 },
  { path: '/services/test-cell-design', lastmod: M, priority: 0.9 },
  { path: '/training', lastmod: M, priority: 0.8, changefreq: 'weekly' },
  { path: '/training/gas-turbine-emissions-mapping', lastmod: M, priority: 0.8, changefreq: 'weekly' },
  { path: '/insights', lastmod: M, priority: 0.8 },
  { path: '/case-studies', lastmod: M, priority: 0.8 },
  { path: '/testimonials', lastmod: M, priority: 0.7 },
  { path: '/contact', lastmod: M, priority: 0.7 },
  { path: '/case-studies/optimizing-test-cell-assembly', lastmod: M },
  { path: '/case-studies/enhancing-test-execution-cost-efficiency', lastmod: M },
  { path: '/case-studies/multichannel-emissions-sampling', lastmod: M },
  { path: '/case-studies/extending-emissions-probe-durability', lastmod: M },
  { path: '/case-studies/dual-mode-liquid-fuel-pumping-system', lastmod: M },
  { path: '/case-studies/improving-gaseous-fuel-supply-system-response', lastmod: M },
  { path: '/case-studies/oil-filtration-and-particle-removal', lastmod: M },
  { path: '/case-studies/test-asset-protection-logic', lastmod: M },
  { path: '/case-studies/new-highperformance-data-acquisition-system', lastmod: M },
  { path: '/case-studies/reinstatement-of-polypropylene-plant-high-pressure-blow-down-vessel', lastmod: M },
  { path: '/case-studies/recovery-reactor-feed-cooler-heat-exchanger', lastmod: M },
  { path: '/case-studies/case-study-fuel-supply-capability-expansion-specification-procurement-and-commissioning', lastmod: M },
  { path: '/insights/secondary-air-impact', lastmod: M },
  { path: '/insights/transitioning-dle-combustion-systems-to-100-hydrogen', lastmod: M },
  { path: '/insights/operational-modes-impact', lastmod: M },
  { path: '/insights/vortex-breakdown', lastmod: M },
  { path: '/insights/combustor-flow-evolution', lastmod: M },
  { path: '/insights/automated-combustor-design', lastmod: M },
  { path: '/insights/sac-dynamics', lastmod: M },
  { path: '/insights/sac-aerodynamics', lastmod: M },
];
