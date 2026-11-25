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
    tagline: 'Single-Part RFQ Intake, Direct DXF Preflight, Waterjet PDF-to-DWG Studio & Native SolidWorks/NX',
    version: '3.1.0',
    category: 'RFQ Intake · DXF Preflight · CAD · Waterjet CAM Prep',
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
    heroAlt: 'Pro3DWorks v3.1 3D CAD viewer showing STEP AP242 model with PMI/GD&T inspection and RFQ intake in Graphite theme',
    summary:
      'Built for fabrication shops, mechanical engineers, and quality teams. Screen single-part STEP/IGES RFQs with OBB stock envelopes and honest withhold-never-zero mass, run unit-verified Direct DXF Preflight or convert shop PDFs to verified .DXF/.DWG cut files, and inspect SolidWorks, NX, and Parasolid assemblies offline on your desktop.',
    highlights: [
      'Single-Part RFQ Intake Screening with PCA OBB stock envelope, watertight mass (withheld if unverified), AP242 PMI summary, separate PDF tracking & free customer questions',
      'Direct DXF Preflight & Waterjet PDF → .DXF/.DWG Studio with unit-conflict gates, G1 biarc fitting, Topology Doctor DFM, and OMAX/SendCutSend presets',
      'Bundled SolidWorks (.SLDPRT/.SLDASM) & Siemens NX (.prt) local native setup wizard plus 4-GiB B-Rep OCCT engine',
      '15-day full Pro trial with Free Basic 3D Viewer & RFQ Screening forever; online activation + 14-day offline grace + air-gapped .p3dwlic for Shop/Perpetual',
    ],
  },
];

export function getProductBySlug(slug: string): SoftwareProduct | undefined {
  return PRODUCTS.find((item) => item.slug === slug);
}
