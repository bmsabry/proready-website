export type SoftwareProduct = {
  slug: string;
  name: string;
  tagline: string;
  version: string;
  category: string;
  status: 'live' | 'coming-soon';
  route: string;
  downloadSlug: string;
  downloadLabel: string;
  platform: string;
  badge: string;
  trialDays: number;
  startingMonthlyPrice: number;
  startingYearlyPrice: number;
  regularMonthlyPrice: number;
  perpetualPrice: number;
  heroImage: string;
  heroAlt: string;
  summary: string;
  highlights: string[];
};

/**
 * Software catalog rendered on /products.
 * New applications released by ProReadyEngineer LLC can be added here alongside
 * their dedicated detail route (/products/<slug>).
 */
export const PRODUCTS: SoftwareProduct[] = [
  {
    slug: 'pro3dworks',
    name: 'Pro3DWorks',
    tagline: 'RFQ Intake + CNC DFM, Evidence-Linked Release Review, Direct DXF Preflight & Waterjet Studio',
    version: '3.2.3',
    category: 'RFQ Intake · CNC DFM · Release Review · Waterjet CAM · Native CAD',
    status: 'live',
    route: '/products/pro3dworks',
    downloadSlug: 'pro3dworks-installer',
    downloadLabel: 'Download Windows x64 Installer (.exe)',
    platform: 'Windows 10 / 11 x64 (~17 MB installer)',
    badge: '15-Day Free Pro Trial · No Card Required',
    trialDays: 15,
    startingMonthlyPrice: 29,
    startingYearlyPrice: 249,
    regularMonthlyPrice: 39,
    perpetualPrice: 599,
    heroImage: '/Pro3DWorks_Hero_Assembly.png',
    heroAlt: 'Pro3DWorks v3.2 3D CAD viewer showing STEP AP242 model with PMI/GD&T inspection, CNC DFM, and RFQ intake in Graphite theme',
    summary:
      'Built for fabrication shops, mechanical engineers, and quality teams. Screen single-part STEP/IGES RFQs with OBB stock envelopes and feature-level CNC DFM checks, reconcile STEP models, governing PDFs, AP242 PMI, and BOM CSVs in Release Review with explicit human sign-off, run unit-verified Direct DXF Preflight or convert shop PDFs to verified .DXF/.DWG cut files, and inspect SolidWorks, NX, and Parasolid assemblies offline under optional IT-managed no-external-network policies.',
    highlights: [
      'Feature-Level 3-Axis CNC DFM & Single-Part RFQ Intake with PCA OBB stock envelopes, withhold-never-zero mass, outside-profile vs. cost-driver rules, honest not_evaluated gates, and 3D locator focus',
      'Evidence-Linked Release Review across STEP, governing PDF drawing, AP242 PMI, and external BOM CSVs with snapshot stale detection, human-only sign-off, and claim-checked AI Engineer guidance',
      'Direct DXF Preflight & Waterjet PDF → .DXF/.DWG Studio with unit-conflict gates, G1 biarc fitting, Topology Doctor DFM, and OMAX/SendCutSend presets',
      'Managed Offline Desktop policy (HKLM Registry / %ProgramData% policy.json with fail-closed no_external_network enforcement, Outbound-Data Matrix & CycloneDX SBOM) alongside 15-day Pro trial & Free Basic 3D Viewer',
    ],
  },
];

export function getProductBySlug(slug: string): SoftwareProduct | undefined {
  return PRODUCTS.find((item) => item.slug === slug);
}
