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
    tagline: 'Precision 3D CAD Viewer, Waterjet PDF-to-DWG Studio & Native SolidWorks/NX Bridge',
    version: 'undefined',
    category: 'CAD · Waterjet CAM Prep · Tolerance Engineering',
    status: 'live',
    route: '/products/pro3dworks',
    downloadSlug: 'pro3dworks-installer',
    downloadLabel: 'Download Windows x64 Installer (.exe)',
    platform: 'Windows 10 / 11 x64 (~undefined MB installer)',
    badge: '15-Day Free Pro Trial · No Card Required',
    trialDays: 15,
    startingMonthlyPrice: 29,
    startingYearlyPrice: 249,
    regularMonthlyPrice: 39,
    perpetualPrice: 599,
    heroImage: '/Pro3DWorks_Hero_Assembly.png',
    heroAlt: 'Pro3DWorks v3.0 3D CAD viewer showing STEP AP242 model with PMI/GD&T inspection in Graphite theme',
    summary:
      'Built for fabrication shops, mechanical engineers, and quality teams. Inspect native SolidWorks, Siemens NX, STEP, IGES, and Parasolid assemblies offline on your desktop—and convert vector or scanned shop PDFs directly into shop-verified .DXF and .DWG cut files.',
    highlights: [
      'Waterjet PDF → .DXF/.DWG Studio with G1 biarc fitting, Topology Doctor DFM checks, and OMAX/SendCutSend presets',
      'Bundled SolidWorks (.SLDPRT/.SLDASM) & Siemens NX (.prt) local native setup wizard plus 4-GiB B-Rep OCCT engine',
      'AP242 PMI/GD&T review, 1D Worst-Case/RSS/Monte Carlo tolerance stack-up, 3-plane triad sectioning & 4K renders',
      'Starts with a full 15-day no-card Pro trial and gracefully falls back to Free Basic 3D Viewing if unpurchased',
    ],
  },
];

export function getProductBySlug(slug: string): SoftwareProduct | undefined {
  return PRODUCTS.find((item) => item.slug === slug);
}
