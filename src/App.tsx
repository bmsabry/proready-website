import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import ScrollToTop from './components/ScrollToTop';
import Home from './pages/Home';

const Services = lazy(() => import('./pages/Services'));
const Training = lazy(() => import('./pages/Training'));
const Insights = lazy(() => import('./pages/Insights'));
const CaseStudies = lazy(() => import('./pages/CaseStudies'));
const Testimonials = lazy(() => import('./pages/Testimonials'));
const Contact = lazy(() => import('./pages/Contact'));
const AdminLogin = lazy(() => import('./pages/admin/AdminLogin'));
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard'));
const GasTurbineEmissionsMapping = lazy(() => import('./pages/training/GasTurbineEmissionsMapping'));

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

function App() {
  return (
    <Router>
      <ScrollToTop />
      <div className="min-h-screen flex flex-col">
        <a href="#main-content" className="skip-link">Skip to main content</a>
        <Navbar />
        <main id="main-content" tabIndex={-1} className="flex-grow">
          <Suspense fallback={<PageLoader />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/services" element={<Services />} />
              <Route path="/training" element={<Training />} />
              <Route path="/training/gas-turbine-emissions-mapping" element={<GasTurbineEmissionsMapping />} />
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
            </Routes>
          </Suspense>
        </main>
        <Footer />
      </div>
    </Router>
  );
}

export default App;
