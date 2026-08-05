export type Module = {
  code: string;
  title: string;
  hours: number;
  summary: string;
  objectives: string[];
  topics: string[];
  videoParts: number;
  hasQuiz: boolean;
  extras: string[];
};

/* Curriculum is embedded rather than fetched so the prerendered HTML
   carries the full outline for search engines. Live price and
   availability still come from the API at runtime. */
export const MODULES: Module[] = [
  {
    code: 'GT-03',
    title: 'Engine Architecture — Single-Shaft Layout & Material Philosophy',
    hours: 5.0,
    summary: 'Walks the complete gas path of a single-shaft turbojet station by station, from ambient through the inlet, centrifugal compressor, evaporative tube combustor, axial turbine and converging nozzle. Every component is covered for function, interface and failure mode alongside the material behind it: Ti-6Al-4V impellers, IN713 turbine parts, Hastelloy X liners and Si3N4 ceramic bearings. Closes with the manufacturing route for each part plus the shaft, casings, ECU and fuel system that tie the engine together.',
    objectives: [
      'Identify every component in a single-shaft turbojet',
      'Understand its function and interface',
      'Explain the material selection rationale for each',
    ],
    topics: [
      'Gas path station numbering convention (0-1-2-3-4-5-8)',
      'Inlet design considerations',
      'Centrifugal compressor — impeller, diffuser, volute',
      'Evaporative tube combustor — working principle',
      'Axial turbine — NGV and rotor',
      'Converging nozzle',
      'Main shaft, bearings, and casings',
      'ECU and fuel system overview',
      'Material selection: Ti-6Al-4V, IN713, Hastelloy X, Si3N4 ceramics',
      'Manufacturing process overview per component',
    ],
    videoParts: 0,
    hasQuiz: false,
    extras: ['Slide deck'],
  },
  {
    code: 'GT-05',
    title: 'Centrifugal Compressor — Aerodynamics, Design & Performance Map',
    hours: 4.5,
    summary: 'Builds centrifugal compressor aerodynamics from the inlet velocity triangle through the Euler work equation, tip speed and pressure ratio scaling, slip factor by the Wiesner correlation, and vaned versus vaneless diffuser pressure recovery. The second half moves onto the performance map: corrected axes, speed lines, surge and choke, and where the operating line and surge margin sit between them. Worked examples run on the reference 80 mm impeller at 80,000 RPM delivering a pressure ratio of 3.5.',
    objectives: [
      'Understand centrifugal compressor aerodynamics from inlet velocity triangles through to diffuser exit',
      'Read and interpret a compressor performance map',
    ],
    topics: [
      'Centrifugal compressor stage overview',
      'Inlet velocity triangle — absolute and relative velocities',
      'Euler turbomachinery equation — work input',
      'Impeller tip speed and pressure ratio relationship',
      'Slip factor — Wiesner correlation',
      'Vaneless and vaned diffuser comparison',
      'Pressure recovery and diffuser efficiency',
      'Compressor map — pressure ratio vs mass flow',
      'Surge line, choke line, and operating line',
      'Stall inception mechanisms',
      'Design point and off-design behaviour',
    ],
    videoParts: 11,
    hasQuiz: true,
    extras: ['Slide deck', 'Design calculator'],
  },
  {
    code: 'GT-06',
    title: 'Evaporative Tube Combustor — Design Principles & Fuel Delivery',
    hours: 3.5,
    summary: 'Covers the evaporative tube combustor: how fuel vaporises inside heated tubes, why that approach beats a pressure-jet atomiser at small engine scale, and how the primary, secondary and dilution zones split the incoming air. Participants calculate fuel-air ratio and equivalence ratio for the primary zone against the Jet-A1 stoichiometric FAR of 0.0667, and set the combustor pressure drop budget. Ends with fuel manifold and tube arrangement, spark and glow plug ignition, and hot start causes and diagnosis.',
    objectives: [
      'Understand the operating principle of an evaporative tube combustor',
      'Calculate air split, equivalence ratio, and fuel-air ratio for the primary zone',
    ],
    topics: [
      'Evaporative vs pressure-jet atomiser comparison',
      'Fuel vaporisation mechanism in heated tubes',
      'Primary zone stoichiometry — equivalence ratio calculation',
      'Secondary zone — CO burnout and dilution',
      'Dilution zone — pattern factor and TET shaping',
      'Stoichiometric FAR for Jet-A1 = 0.0667',
      'Primary zone FAR target: φ ≈ 1.0',
      'Fuel manifold and tube arrangement',
      'Combustor pressure drop — total and cold',
      'Ignition system — spark plug and glow plug types',
      'Hot start causes and diagnosis',
    ],
    videoParts: 14,
    hasQuiz: true,
    extras: ['Slide deck', 'Design calculator'],
  },
  {
    code: 'GT-07',
    title: 'Axial Turbine — Aerodynamics, Blade Loading & Structural Integrity',
    hours: 4.0,
    summary: 'Takes the single-stage axial turbine from NGV and rotor aerodynamics through velocity triangles, degree of reaction, stage loading and flow coefficient, and Euler work for zero exit swirl. The structural half covers disc centrifugal stress with the Lamé equations, the SF >= 1.5 requirement on rotating parts, LCF life by the Coffin-Manson approach and HCF screening on a Campbell diagram. Material limits are anchored to IN713 at 950 C turbine inlet temperature.',
    objectives: [
      'Understand axial turbine stage aerodynamics',
      'Draw NGV and rotor velocity triangles',
      'Calculate stage loading and identify structural failure modes',
    ],
    topics: [
      'NGV and rotor function — nozzle and blade row aerodynamics',
      'Velocity triangle at rotor inlet and exit',
      'Degree of reaction — 50% reaction design',
      'Stage loading coefficient ψ = ΔCw/U',
      'Flow coefficient φ = Ca/U',
      'Euler work for zero exit swirl: W = U × Cw1',
      'Blade profile types — impulse vs reaction',
      'Turbine disc centrifugal stress — Lamé equations',
      'Safety factor requirement: SF ≥ 1.5 for rotating parts',
      'LCF life — Coffin-Manson approach',
      'HCF — Campbell diagram for blades',
      'Material temperature limits: IN713 to 950°C TIT',
    ],
    videoParts: 23,
    hasQuiz: true,
    extras: ['Slide deck', 'Design calculator', 'Interactive lab'],
  },
  {
    code: 'GT-12',
    title: 'Compressor Map Generation & Surge Margin Analysis',
    hours: 3.0,
    summary: 'Explains how a compressor map is generated on a test rig and how to read it: corrected pressure ratio and mass flow axes, speed lines, the surge line, and the distinction between rotating stall and full surge. The working skill is surge margin, SM = (PR_surge - PR_op)/PR_op, and the >= 10% requirement for small turbojets. Also covers how a TET change and inlet distortion move the operating and surge lines, what casing treatment buys, and why margin collapses during a throttle transient.',
    objectives: [
      'Read and interpret a centrifugal compressor performance map',
      'Calculate surge margin',
      'Identify dangerous operating conditions',
    ],
    topics: [
      'How compressor maps are generated — test rig methodology',
      'Map axes: pressure ratio vs corrected mass flow',
      'Speed lines — corrected speed definition',
      'Surge line — physical mechanism',
      'Stall line — rotating stall vs surge distinction',
      'Operating line construction from cycle model',
      'Surge margin definition: SM = (PR_surge - PR_op)/PR_op × 100%',
      'Required surge margin: ≥10% for small turbojets',
      'Effect of TET change on operating line',
      'Effect of inlet distortion on surge line',
      'Casing treatment — slot and groove types',
      'Throttle transient — why surge margin reduces during acceleration',
    ],
    videoParts: 0,
    hasQuiz: false,
    extras: ['Slide deck'],
  },
  {
    code: 'GT-13',
    title: 'CFD Fundamentals & Application to Turbomachinery Components',
    hours: 5.0,
    summary: 'Runs the CFD workflow for turbomachinery end to end: geometry, mesh type, boundary conditions, solver and post-processing. Covers y+ and near-wall resolution, choosing between k-epsilon and k-omega SST for compressors, periodic boundaries for blade passages, and frozen rotor versus mixing plane interfaces, then applies them to a compressor case with inlet total conditions and exit static pressure. Ends on validation against 1D meanline and test data, the errors that produce converged but wrong answers, and where ANSYS CFX, StarCCM+ and OpenFOAM fit.',
    objectives: [
      'Understand the CFD process for turbomachinery flows',
      'Set up a RANS simulation correctly',
      'Interpret and validate results',
    ],
    topics: [
      'CFD workflow: geometry → mesh → BCs → solver → post-processing',
      'Mesh types for turbomachinery: structured, unstructured, hybrid',
      'y+ concept — wall distance and turbulence model requirements',
      'Turbulence models: k-ε vs k-ω SST — which to choose for compressors',
      'Periodic boundary conditions for blade passages',
      'Frozen rotor vs stage mixing plane interface',
      'Compressor simulation setup: inlet total conditions, exit static pressure',
      'Key outputs: total pressure ratio, isentropic efficiency, velocity vectors',
      'Validation: comparing CFD to 1D meanline and test data',
      'Common errors: poor mesh quality, wrong BCs, convergence without accuracy',
      'Introduction to ANSYS CFX, StarCCM+, and OpenFOAM for turbomachinery',
    ],
    videoParts: 17,
    hasQuiz: true,
    extras: ['Slide deck', 'Interactive simulator'],
  },
  {
    code: 'GT-15',
    title: 'Combustor Design Analysis — Heat Release, Liner Cooling & Fuel Scheduling',
    hours: 3.5,
    summary: 'The analytical follow-on to the combustor design session: heat release rate from FAR and mass flow, combustion efficiency, and pattern factor with its target below 0.15 and its direct effect on turbine blade life. Covers dilution hole sizing to shape the TET profile, liner cooling by film, convective and transpiration routes, material selection between Hastelloy X and Nimonic 75, and evaporative tube flow matching to 2%. Closes with start fuel scheduling from propane ignition to main fuel, and hot-start diagnosis from the EGT trace.',
    objectives: [
      'Analyse combustor performance',
      'Calculate heat release rate, pattern factor',
      'Design a fuel schedule for the start sequence',
    ],
    topics: [
      'Heat release rate calculation from FAR and mass flow',
      'Combustion efficiency definition and measurement',
      'Pattern factor: definition, measurement, target <0.15',
      'Effect of pattern factor on turbine blade life',
      'Dilution hole sizing to achieve target TET profile',
      'Liner cooling: film cooling, convective cooling, transpiration',
      'Liner material selection: Hastelloy X, Nimonic 75',
      'Evaporative tube flow matching — tolerance ≤ 2%',
      'Fuel scheduling during start: propane ignition → main fuel',
      'Fuel schedule design: flow vs time vs temperature',
      'Hot-start diagnosis: EGT spike causes and corrective action',
      'Combustor CFD for reacting flow — simplified overview',
    ],
    videoParts: 18,
    hasQuiz: true,
    extras: ['Slide deck'],
  },
];

export const TOTAL_HOURS = 28.5;
export const TOTAL_VIDEO_PARTS = 83;
export const COURSE_SUBTITLE = 'Design a 700 N single-shaft turbojet end to end, from gas path stations to CFD and combustor analysis.';
