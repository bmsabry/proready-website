/* The facts on /about/bassam-abdelnabi.
 *
 * Every entry is taken from Dr. Abdelnabi's own curricula vitae; nothing here
 * is written from memory or from other pages of the site. Before changing or
 * adding a line, check it against the CV: this page is published under his
 * name.
 *
 * Left out on purpose: contact details, location of residence, personal
 * details, references, and anything about what he was paid.
 *
 * No consulting price appears here or anywhere on the page.
 */

export const NAME = 'Dr. Bassam Abdelnabi';
export const ROLE = 'Founder and President, ProReadyEngineer LLC';
export const EARLIER_NAME = 'Bassam S. Mohammad';

export const SUMMARY =
  'Thermo-fluids and gas turbine combustion engineer with 24 years of experience across advanced R&D, product programs, high-pressure testing, field mapping, emissions control and technical capability building. He holds a Ph.D. in Aerospace Engineering and worked at the GE Global Research Center and GE Aerospace before founding ProReadyEngineer LLC.';

export type Stat = { value: number; suffix?: string; label: string };

export const STATS: Stat[] = [
  { value: 24, label: 'Years across research, product and field execution' },
  { value: 9, label: 'U.S. patents or patent applications' },
  { value: 20, suffix: '+', label: 'Published technical papers, author or co-author' },
  { value: 100, label: 'Internal technical publications (approximate)' },
  { value: 6, label: 'Engine-platform releases or field resolutions' },
];

export type Role = {
  title: string;
  org: string;
  place?: string;
  dates: string;
  points: string[];
};

export const EXPERIENCE: Role[] = [
  {
    title: 'Founder and President',
    org: 'ProReadyEngineer LLC',
    dates: 'January 2026 to present',
    points: [
      'Built an engineering platform combining gas turbine combustion, thermal-fluid systems, industrial AI, test infrastructure, engineering software and professional education.',
      'Delivers consulting and capability development in combustor design, emissions mapping, test-cell specification and commissioning, fuel flexibility, digital twins and engineering analytics.',
      'Created a 28.5-hour micro gas turbine design program and a four-day emissions-mapping course.',
      'Productized technical workflows through Pro3DWorks, an offline-capable CAD inspection suite, and ProMechDirectory, an AI-assisted RFQ and supplier-discovery platform.',
    ],
  },
  {
    title: 'Staff Combustion Aerodynamics Engineer, Engineering Design & Integration',
    org: 'GE Aerospace',
    place: 'Cincinnati, Ohio',
    dates: 'October 2022 to January 2026',
    points: [
      'Led the LMS100 PB+ emissions-control strategy, defining pathways to regulatory compliance and future performance targets across design, test, controls and field stakeholders.',
      'Pioneered GE Aerospace’s first gas turbine digital twin, integrating test, engine and field data for predictive emissions modeling, virtual tuning and corner-point optimization.',
      'Resolved a high-visibility NOx exceedance that had resisted prior efforts: identified the root cause, delivered a compliant solution and earned the 2024 Outstanding Subsection Achievement Award.',
      'Served as technical focal point for Baker Hughes field mapping and trained external engineering teams on LMS100 operation, mapping logic, emissions tradeoffs and field decision-making.',
      'Advanced product capability and team efficiency through mixer and tunable acoustic-damping concepts, patent applications, lean automation tools, and mentoring of interns and junior engineers.',
    ],
  },
  {
    title: 'Senior Combustion Research Engineer',
    org: 'GE Global Research Center',
    place: 'Niskayuna, New York',
    dates: 'February 2017 to October 2022',
    points: [
      'Led cross-functional hydrogen and carbon-free-energy research, including early development supporting a 100% hydrogen aircraft-engine concept and high-pressure testing of hydrogen-enriched fuels above 30% H2.',
      'Established performance baselines and development roadmaps for propane, low-Wobbe gas, hydrogen blends and crude oil, linking combustion behavior to operability, emissions, durability and product decisions.',
      'Reduced physical test requirements by 40% by delivering automated test capability.',
      'Coordinated shared laboratory execution across GE Research and multiple business units: test resources, schedules, safety, instrumentation and technical deliverables.',
      'Contributed to six engine-platform releases or field resolutions across LM9000, LEAP, LMS100, LM6000PH, LM6000PF1 and LM6000PF2, and to the DLE2.4, DLE3.0 and DLE5.0 technology generations.',
    ],
  },
  {
    title: 'Combustion Research Engineer',
    org: 'GE Global Research Center',
    place: 'Niskayuna, New York',
    dates: 'October 2010 to February 2017',
    points: [
      'Managed an annual R&D portfolio of more than two million US dollars, covering test-cell upgrades, CFD, mechanical design, instrumentation and controls, Design of Experiments and high-pressure combustion campaigns.',
      'Directed multi-fuel rig and flame-tube campaigns with Jet-A, diesel, crude oil, hydrogen blends, propane and low-Wobbe gas, coordinating design, controls, instrumentation, operations and safety reviews.',
      'Increased experimental throughput by 30-45% through systematic improvements to hardware, sensors, controls, data workflows and laboratory standard work, while supporting zero-incident high-pressure testing.',
      'Created intellectual property in fuel nozzles, micromixers, flow control, emissions reduction and fuel-flexible combustion systems.',
    ],
  },
];

export const EARLIER: Role[] = [
  {
    title: 'Research and Teaching Assistant, Combustion & Propulsion Laboratory',
    org: 'University of Cincinnati',
    place: 'Cincinnati, Ohio',
    dates: 'January 2007 to March 2010',
    points: [
      'Investigated combustor aerodynamics, dynamics, emissions and mixing using PIV, LDV, high-speed imaging and combustion diagnostics; supported teaching in gas turbine combustion, combustion theory and propulsion.',
    ],
  },
  {
    title: 'Research and Teaching Assistant, Nuclear Engineering',
    org: 'University of Missouri-Rolla (Missouri S&T)',
    place: 'Rolla, Missouri',
    dates: 'August 2005 to January 2007',
    points: [
      'Developed and validated transient thermal models using equivalent-circuit methods, CFD and analytical modeling; created nuclear-fuel-cycle analysis and optimization software.',
    ],
  },
  {
    title: 'Research and Teaching Assistant, Mechanical Power Engineering',
    org: 'Cairo University',
    place: 'Cairo, Egypt',
    dates: 'February 2002 to August 2005',
    points: [
      'Designed and tested mixed-flow pumps and developed preliminary impeller-design software; taught fluid mechanics, turbomachinery and numerical analysis.',
    ],
  },
];

export type Degree = { degree: string; school: string; year: string; note?: string };

export const EDUCATION: Degree[] = [
  {
    degree: 'Ph.D., Aerospace Engineering',
    school: 'University of Cincinnati',
    year: '2010',
    note: 'Dissertation: Single Annular Combustor Sector: Aerodynamic, Dynamics and Emissions.',
  },
  {
    degree: 'M.S., Nuclear Engineering',
    school: 'University of Missouri-Rolla (Missouri S&T)',
    year: '2007',
    note: 'Thesis: Equivalent Circuit for Transient Conduction and Convection Systems.',
  },
  {
    degree: 'M.S., Mechanical Power Engineering',
    school: 'Cairo University',
    year: '2005',
    note: 'Turbomachinery specialization; distinction.',
  },
  {
    degree: 'B.S., Mechanical Power Engineering',
    school: 'Cairo University',
    year: '2001',
    note: 'Distinction with honors.',
  },
];

export const EXPERTISE: { area: string; items: string }[] = [
  {
    area: 'Combustion and power systems',
    items:
      'DLE/DLN combustion, low-NOx systems, combustion dynamics and control, emissions mapping, fuel flexibility, hydrogen, advanced mixing, turbomachinery, heat transfer and reacting flows.',
  },
  {
    area: 'Data, modeling and decision science',
    items:
      'Digital twins, Design of Experiments, physics-grounded and Bayesian hybrid models, reduced-order modeling, uncertainty-aware prediction, statistical analysis, Python, MATLAB, R, Cantera, NASA CEA and non-reacting FLUENT CFD.',
  },
  {
    area: 'Test and execution systems',
    items:
      'High-pressure combustion rigs, flame tubes, emissions measurement, instrumentation and controls, PIV, LDV, high-speed imaging, test-cell commissioning, safety systems, SOPs and lean workflow automation.',
  },
];

export const PATENT_SUMMARY =
  'Co-inventor on nine U.S. patents or patent applications covering combustion chambers, fuel nozzles, micromixers and acoustic control. They include:';

export type Patent = { title: string; id: string; year: string };

/* Eight of the nine. One fuel-nozzle patent is left off until its number and
   year are confirmed by the owner (they do not agree with each other in the
   CV). */
export const PATENTS: Patent[] = [
  { title: 'Swirler for combustion chambers', id: 'US20130255261A1', year: '2013' },
  { title: 'Jet micro-induced flow reversals combustor', id: 'US20130196270A1', year: '2013' },
  { title: 'Fuel nozzle (first design)', id: 'US20140144150A1', year: '2014' },
  { title: 'Micromixer system for a turbine system', id: 'US10101032B2', year: '2018' },
  { title: 'System and method having fuel nozzle', id: 'US10215414B2', year: '2019' },
  { title: 'Mini mixing fuel nozzle with mixing sleeve', id: 'US10465290B2', year: '2019' },
  { title: 'Furcating pilot pre-mixer for mini-mixer array', id: 'US11506388B1', year: '2022' },
  { title: 'Turbine combustor with tunable acoustic damper', id: 'US Application 18/653,215', year: '2024' },
];

export const PUBLICATION_SUMMARY =
  'Author or co-author of more than 20 externally published technical papers, and of close to 100 internal technical publications written inside industry. Earlier publications appear under the name Bassam S. Mohammad. Selected external publications:';

export type Publication = { authors: string; title: string; venue: string };

/* Authors as the CV lists them; where a paper has more than three, the first
   three are given, followed by "et al." */
export const PUBLICATIONS: Publication[] = [
  {
    authors: 'Mohammad, B. S., Cuppoletti, D., Elkady, A., et al.',
    title: 'Hydrogen Enrichment Impact on Gas Turbine Combustor Characteristics',
    venue: 'ASME Turbo Expo, 2020',
  },
  {
    authors: 'Mohammad, B. S., McManus, K., and Volk, B.',
    title: 'Impact of Secondary Air Flow on Combustor Emissions',
    venue: 'ASME Turbo Expo, 2020',
  },
  {
    authors: 'Goldmeer, J., Glaser, P., and Mohammad, B. S.',
    title:
      'Evaluation of Arabian Super Light and Arabian Extra Light Crude Oil for Use in Dry Low NOx Combustion Systems',
    venue: 'ASME Turbo Expo, 2019',
  },
  {
    authors: 'Goldmeer, J., Mohammad, B. S., Nagel, Z., et al.',
    title: 'Evaluation of Arabian Super Light Crude Oil for Use in DLN Combustion System',
    venue: 'ASME Turbo Expo, 2014',
  },
  {
    authors: 'Mohammad, B. S., McManus, K., Symonds, R., et al.',
    title: 'Effect of Mode of Operation on Gas Turbine Combustor Performance',
    venue: 'ASME Turbo Expo, GT2013-96023, 2013',
  },
  {
    authors: 'Mohammad, B. S., Elkady, A., Mueller, M., et al.',
    title: 'Combustion Dynamics Diagnostics and Mitigation on Prototype Gas Turbine Combustor',
    venue: 'ASME Turbo Expo, GT2012-68570, 2012',
  },
  {
    authors: 'Mohammad, B. S., Cai, J., Tambe, S., et al.',
    title:
      'Combustion Dynamics and Emissions Characterization for Gas Turbine Combustor Burning Methane and Propane',
    venue: 'AIAA Joint Propulsion Conference, AIAA 2011-5704, 2011',
  },
  {
    authors: 'Mohammad, B. S., and Jeng, S.',
    title: 'Gas Turbine Combustor Sector Flow Structure',
    venue: 'Journal of Propulsion and Power, 27(3), 710-717, 2011. doi:10.2514/1.53833',
  },
  {
    authors: 'Mohammad, B. S., Cai, J., and Jeng, S. M.',
    title: 'Gas Turbine Combustor Flow Structure Control Through Modification of Chamber Geometry',
    venue: 'Journal of Engineering for Gas Turbines and Power, 133(9), 2011. doi:10.1115/1.4002881',
  },
  {
    authors: 'Mohammad, B., Jeng, S., and Andac, G.',
    title: 'Influence of Fuel Injection and Primary Jets on Aerodynamics of Prototype Gas Turbine Combustor',
    venue: 'Journal of Engineering for Gas Turbines and Power, 133(1), 2011. doi:10.1115/1.4002004',
  },
];

export const RECOGNITION_SUMMARY =
  'Selected recognition includes the 2024 Outstanding Subsection Achievement Award and GE awards for LM9000 and LEAP durability, DLE3 development, test productivity, Fast Works, patents, technical excellence, mentorship and teamwork.';

export const AWARDS: { name: string; year: string }[] = [
  { name: 'Outstanding Subsection Achievement Award (RCA closure)', year: '2024' },
  { name: 'Thermal Sciences Award, “Don’t Take No for an Answer”, for LM9000 durability', year: '2020' },
  { name: 'DLE3 Development Silver Award', year: '2019' },
  { name: 'Thermal Sciences Award, “Don’t Take No for an Answer”, for LEAP durability', year: '2018' },
  { name: 'GE INSPIRE Volunteer Award, for mentorship excellence', year: '2017' },
  { name: 'Test Productivity Enhancement Award', year: '2016' },
  { name: 'ATMS Award for Fast Works', year: '2015' },
  { name: 'First Patent Medal at GE', year: '2012' },
];

export const CREDENTIALS =
  'GE Analytics Engineer; Lean Six Sigma Green Belt; Project Management Fundamentals; TRIZ; advanced Design of Experiments; intellectual-property methods; electrical safety and lock-out/tag-out.';

/* Public profiles named in the CV. */
export const PROFILE_LINKS = {
  scholar: 'https://scholar.google.com/citations?hl=en&user=KNvbDTcAAAAJ',
  linkedin: 'https://www.linkedin.com/in/bassam-abdelnabi-4a055a20/',
};
