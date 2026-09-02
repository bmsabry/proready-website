import React, { Suspense, lazy } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import ScrollToTop from './components/ScrollToTop';
import Home from './pages/Home';

const Services = lazy(() => import('./pages/Services'));
const Products = lazy(() => import('./pages/Products'));
const Training = lazy(() => import('./pages/Training'));
const Insights = lazy(() => import('./pages/Insights'));
const CaseStudies = lazy(() => import('./pages/CaseStudies'));
const Testimonials = lazy(() => import('./pages/Testimonials'));
const Contact = lazy(() => import('./pages/Contact'));
const AdminLogin = lazy(() => import('./pages/admin/AdminLogin'));
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard'));
const GasTurbineEmissionsMapping = lazy(() => import('./pages/training/GasTurbineEmissionsMapping'));
const MicroGasTurbineDesign = lazy(() => import('./pages/training/MicroGasTurbineDesign'));
const MicroGasTurbineDesignLive = lazy(() => import('./pages/training/MicroGasTurbineDesignLive'));
// Learner portal — auth-gated, deliberately NOT in routes.ts so the
// prerenderer never tries to build these.
const LearnSignIn = lazy(() => import('./pages/learn/SignIn'));
const LearnDashboard = lazy(() => import('./pages/learn/Dashboard'));
const LearnLesson = lazy(() => import('./pages/learn/Lesson'));
const LearnQuiz = lazy(() => import('./pages/learn/Quiz'));
const LearnAdvancedExam = lazy(() => import('./pages/learn/AdvancedExam'));
const VerifyCredential = lazy(() => import('./pages/Verify'));
const LearnWelcome = lazy(() => import('./pages/learn/Welcome'));

const GasTurbineCombustionConsulting = lazy(() => import('./pages/services/GasTurbineCombustionConsulting'));
const IndustrialAIConsulting = lazy(() => import('./pages/services/IndustrialAIConsulting'));
const TestCellDesign = lazy(() => import('./pages/services/TestCellDesign'));
const NotFound = lazy(() => import('./pages/NotFound'));

const OptimizingTestCellAssembly = lazy(() => import('./pages/case-studies/OptimizingTestCellAssembly'));
const EnhancingTestExecutionCostEfficiency = lazy(() => import('./pages/case-studies/EnhancingTestExecutionCostEfficiency'));
const MultichannelEmissionsSampling = lazy(() => import('./pages/case-studies/MultichannelEmissionsSampling'));
const ExtendingEmissionsProbeDurability = lazy(() => import('./pages/case-studies/ExtendingEmissionsProbeDurability'));
const DualModeLiquidFuelPumpingSystem = lazy(() => import('./pages/case-studies/DualModeLiquidFuelPumpingSystem'));
const ImprovingGaseousFuelSupplySystemResponse = lazy(() => import('./pages/case-studies/ImprovingGaseousFuelSupplySystemResponse'));
const OilFiltrationParticleRemoval = lazy(() => import('./pages/case-studies/OilFiltrationParticleRemoval'));
const TestAssetProtectionLogic = lazy(() => import('./pages/case-studies/TestAssetProtectionLogic'));
const CaseStudyFuelSupplyCapabilityExpansion = lazy(() => import('./pages/case-studies/CaseStudyFuelSupplyCapabilityExpansionSpecificationProcurementAndCommissioning'));
const NewHighperformanceDataAcquisitionSystem = lazy(() => import('./pages/case-studies/NewHighperformanceDataAcquisitionSystem'));
const ReinstatementOfPolypropylenePlant = lazy(() => import('./pages/case-studies/ReinstatementOfPolypropylenePlantHighPressureBlowDownVessel'));
const RecoveryReactorFeedCoolerHeatExchanger = lazy(() => import('./pages/case-studies/RecoveryReactorFeedCoolerHeatExchanger'));

const SecondaryAirImpact = lazy(() => import('./pages/insights/SecondaryAirImpact'));
const TransitioningDLECombustionSystemsTo100Hydrogen = lazy(() => import('./pages/insights/TransitioningDLECombustionSystemsTo100Hydrogen'));
const ImpactOfOperationalModes = lazy(() => import('./pages/insights/ImpactOfOperationalModes'));
const VortexBreakdown = lazy(() => import('./pages/insights/VortexBreakdown'));
const CombustorFlowEvolution = lazy(() => import('./pages/insights/CombustorFlowEvolution'));
const AutomatedCombustorDesign = lazy(() => import('./pages/insights/AutomatedCombustorDesign'));
const SACDynamics = lazy(() => import('./pages/insights/SACDynamics'));
const SACAerodynamics = lazy(() => import('./pages/insights/SACAerodynamics'));

const PageLoader = () => (
  <div className="min-h-[50vh] flex items-center justify-center" role="status" aria-label="Loading page">
    <div className="w-8 h-8 border-2 border-slate-700 border-t-cyan-400 rounded-full animate-spin" />
  </div>
);

/** Stripe Checkout returns buyers to /training/{course.code}?paid=1, and the
    course code carries the cohort suffix (e.g. -2026-05) while the page lives
    at the plain slug. Forward the visit, query string intact, so the payment
    banner lands on the course page instead of a 404. */
const EmissionsCohortRedirect = () => {
  const { search } = useLocation();
  return <Navigate to={`/training/gas-turbine-emissions-mapping${search}`} replace />;
};

/** Same forwarding for the Micro Gas Turbine Design live cohort: Stripe
    returns buyers to /training/micro-gas-turbine-design-2026-10, while the
    live cohort page lives at the -live slug. */
const MgtCohortRedirect = () => {
  const { search } = useLocation();
  return <Navigate to={`/training/micro-gas-turbine-design-live${search}`} replace />;
};

function App() {
  return (
    <>
      <ScrollToTop />
      <div className="min-h-screen flex flex-col">
        <a href="#main-content" className="skip-link">Skip to main content</a>
        <Navbar />
        <main id="main-content" tabIndex={-1} className="flex-grow">
          <Suspense fallback={<PageLoader />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/services" element={<Services />} />
              <Route path="/products" element={<Products />} />
              <Route path="/services/gas-turbine-combustion" element={<GasTurbineCombustionConsulting />} />
              <Route path="/services/industrial-ai" element={<IndustrialAIConsulting />} />
              <Route path="/services/test-cell-design" element={<TestCellDesign />} />
              <Route path="/training" element={<Training />} />
              <Route path="/training/gas-turbine-emissions-mapping" element={<GasTurbineEmissionsMapping />} />
              <Route path="/training/gas-turbine-emissions-mapping-2026-05" element={<EmissionsCohortRedirect />} />
              <Route path="/training/micro-gas-turbine-design" element={<MicroGasTurbineDesign />} />
              <Route path="/training/micro-gas-turbine-design-live" element={<MicroGasTurbineDesignLive />} />
              <Route path="/training/micro-gas-turbine-design-2026-10" element={<MgtCohortRedirect />} />
              <Route path="/learn" element={<LearnDashboard />} />
              <Route path="/learn/signin" element={<LearnSignIn />} />
              <Route path="/learn/welcome" element={<LearnWelcome />} />
              <Route path="/learn/lesson/:lessonId" element={<LearnLesson />} />
              <Route path="/learn/quiz/:moduleId/:itemSet" element={<LearnQuiz />} />
              <Route path="/learn/advanced-exam/:productCode" element={<LearnAdvancedExam />} />
              <Route path="/verify/:code" element={<VerifyCredential />} />
              <Route path="/learn/:productCode" element={<LearnDashboard />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/case-studies" element={<CaseStudies />} />
              <Route path="/testimonials" element={<Testimonials />} />
              <Route path="/case-studies/optimizing-test-cell-assembly" element={<OptimizingTestCellAssembly />} />
              <Route path="/case-studies/enhancing-test-execution-cost-efficiency" element={<EnhancingTestExecutionCostEfficiency />} />
              <Route path="/case-studies/multichannel-emissions-sampling" element={<MultichannelEmissionsSampling />} />
              <Route path="/case-studies/extending-emissions-probe-durability" element={<ExtendingEmissionsProbeDurability />} />
              <Route path="/case-studies/dual-mode-liquid-fuel-pumping-system" element={<DualModeLiquidFuelPumpingSystem />} />
              <Route path="/case-studies/improving-gaseous-fuel-supply-system-response" element={<ImprovingGaseousFuelSupplySystemResponse />} />
              <Route path="/case-studies/oil-filtration-and-particle-removal" element={<OilFiltrationParticleRemoval />} />
              <Route path="/case-studies/test-asset-protection-logic" element={<TestAssetProtectionLogic />} />
              <Route path="/case-studies/new-highperformance-data-acquisition-system" element={<NewHighperformanceDataAcquisitionSystem />} />
              <Route path="/case-studies/reinstatement-of-polypropylene-plant-high-pressure-blow-down-vessel" element={<ReinstatementOfPolypropylenePlant />} />
              <Route path="/case-studies/recovery-reactor-feed-cooler-heat-exchanger" element={<RecoveryReactorFeedCoolerHeatExchanger />} />
              <Route path="/case-studies/case-study-fuel-supply-capability-expansion-specification-procurement-and-commissioning" element={<CaseStudyFuelSupplyCapabilityExpansion />} />
              <Route path="/insights/secondary-air-impact" element={<SecondaryAirImpact />} />
              <Route path="/insights/transitioning-dle-combustion-systems-to-100-hydrogen" element={<TransitioningDLECombustionSystemsTo100Hydrogen />} />
              <Route path="/insights/operational-modes-impact" element={<ImpactOfOperationalModes />} />
              <Route path="/insights/vortex-breakdown" element={<VortexBreakdown />} />
              <Route path="/insights/combustor-flow-evolution" element={<CombustorFlowEvolution />} />
              <Route path="/insights/automated-combustor-design" element={<AutomatedCombustorDesign />} />
              <Route path="/insights/sac-dynamics" element={<SACDynamics />} />
              <Route path="/insights/sac-aerodynamics" element={<SACAerodynamics />} />
              <Route path="/contact" element={<Contact />} />
              <Route path="/admin/login" element={<AdminLogin />} />
              <Route path="/admin" element={<AdminDashboard />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </main>
        <Footer />
      </div>
    </>
  );
}

export default App;
