/**
 * Central metadata for article-type pages (case studies + research insights).
 * Used by usePageMeta to emit TechArticle structured data and per-page
 * social images without touching each detail page.
 */
export type ArticleMeta = { image: string; datePublished: string };

export const ARTICLE_META: Record<string, ArticleMeta> = {
  // Case studies
  '/case-studies/recovery-reactor-feed-cooler-heat-exchanger': { image: '/Recovery_Reactor_Feed_Cooler_Heat_Exchanger.jpg', datePublished: '2026-03-17' },
  '/case-studies/reinstatement-of-polypropylene-plant-high-pressure-blow-down-vessel': { image: '/Reinstatement_of_Polypropylene_Plant_High_Pressure_Blow_Down_Vessel.png', datePublished: '2026-03-02' },
  '/case-studies/case-study-fuel-supply-capability-expansion-specification-procurement-and-commissioning': { image: '/CASE_STUDY_Fuel_Supply_Capability_Expansion__Specification_Procurement_and_Commissioning.jpg', datePublished: '2026-02-20' },
  '/case-studies/test-asset-protection-logic': { image: '/Test_Asset_Protection_Logic.jpg', datePublished: '2026-02-17' },
  '/case-studies/new-highperformance-data-acquisition-system': { image: '/New_HighPerformance_Data_Acquisition_System.jpg', datePublished: '2026-02-17' },
  '/case-studies/oil-filtration-and-particle-removal': { image: '/case-study-oil-filtration-and-particle-removal-in-sensitive-optics-cooling-air.jpg', datePublished: '2026-02-16' },
  '/case-studies/extending-emissions-probe-durability': { image: '/case-study-extending-emissions-rake-durability.jpg', datePublished: '2026-02-13' },
  '/case-studies/dual-mode-liquid-fuel-pumping-system': { image: '/case-study-specifying-procuring-and-installing-a-dualmode-liquidfuel-pumping-system.jpg', datePublished: '2026-02-13' },
  '/case-studies/improving-gaseous-fuel-supply-system-response': { image: '/case-study-improving-gaseous-fuel-supply-system-response.jpg', datePublished: '2026-02-13' },
  '/case-studies/multichannel-emissions-sampling': { image: '/case-study-enabling-multichannel-emissions-sampling.jpg', datePublished: '2026-02-11' },
  '/case-studies/enhancing-test-execution-cost-efficiency': { image: '/case2-study-enhancing-test-execution-cost-efficiency.jpg', datePublished: '2026-02-10' },
  '/case-studies/optimizing-test-cell-assembly': { image: '/optimizing-test-cell-assembly.png', datePublished: '2026-02-05' },
  // Research insights
  '/insights/operational-modes-impact': { image: '/Impact_of_Operational_Modes_on_Gas_Turbine_Combustor_Performance.jpg', datePublished: '2026-03-05' },
  '/insights/transitioning-dle-combustion-systems-to-100-hydrogen': { image: '/Hydrogen_Impact_on_Combustor_Performance_and_NOx_Emissions.jpg', datePublished: '2026-02-20' },
  '/insights/secondary-air-impact': { image: '/impact-secondary-air-emissions.jpg', datePublished: '2026-01-28' },
  '/insights/combustor-flow-evolution': { image: '/SAC_Flow_Evolution.jpg', datePublished: '2026-01-26' },
  '/insights/automated-combustor-design': { image: '/SAC_Design_Infographic.png', datePublished: '2026-01-26' },
  '/insights/sac-dynamics': { image: '/SAC_Dynamics.jpg', datePublished: '2026-01-26' },
  '/insights/sac-aerodynamics': { image: '/SAC_Aerodynamics.jpg', datePublished: '2026-01-26' },
  '/insights/vortex-breakdown': { image: '/Vortex_Break_Down_Image.png', datePublished: '2026-01-25' },
};
