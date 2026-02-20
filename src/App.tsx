import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import Home from './pages/Home';
import Services from './pages/Services';
import Training from './pages/Training';
import Insights from './pages/Insights';
import CaseStudies from './pages/CaseStudies';
import Testimonials from './pages/Testimonials';
import OptimizingTestCellAssembly from './pages/case-studies/OptimizingTestCellAssembly';
import EnhancingTestExecutionCostEfficiency from './pages/case-studies/EnhancingTestExecutionCostEfficiency';
import MultichannelEmissionsSampling from './pages/case-studies/MultichannelEmissionsSampling';
import ExtendingEmissionsProbeDurability from './pages/case-studies/ExtendingEmissionsProbeDurability';
import DualModeLiquidFuelPumpingSystem from './pages/case-studies/DualModeLiquidFuelPumpingSystem';
import ImprovingGaseousFuelSupplySystemResponse from './pages/case-studies/ImprovingGaseousFuelSupplySystemResponse';
import OilFiltrationParticleRemoval from './pages/case-studies/OilFiltrationParticleRemoval';
import TestAssetProtectionLogic from './pages/case-studies/TestAssetProtectionLogic';
import CaseStudyFuelSupplyCapabilityExpansionSpecificationProcurementAndCommissioning from './pages/case-studies/CaseStudyFuelSupplyCapabilityExpansionSpecificationProcurementAndCommissioning';
import NewHighperformanceDataAcquisitionSystem from './pages/case-studies/NewHighperformanceDataAcquisitionSystem';
import SecondaryAirImpact from './pages/insights/SecondaryAirImpact';
import VortexBreakdown from './pages/insights/VortexBreakdown';
import CombustorFlowEvolution from './pages/insights/CombustorFlowEvolution';
import AutomatedCombustorDesign from './pages/insights/AutomatedCombustorDesign';
import SACDynamics from './pages/insights/SACDynamics';
import SACAerodynamics from './pages/insights/SACAerodynamics';
import Contact from './pages/Contact';

function App() {
  return (
    <Router>
      <div className="min-h-screen flex flex-col">
        <Navbar />
        <main className="flex-grow">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/services" element={<Services />} />
            <Route path="/training" element={<Training />} />
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
            <Route path="/insights/secondary-air-impact" element={<SecondaryAirImpact />} />
            <Route path="/insights/vortex-breakdown" element={<VortexBreakdown />} />
            <Route path="/insights/combustor-flow-evolution" element={<CombustorFlowEvolution />} />
            <Route path="/insights/automated-combustor-design" element={<AutomatedCombustorDesign />} />
            <Route path="/insights/sac-dynamics" element={<SACDynamics />} />
            <Route path="/insights/sac-aerodynamics" element={<SACAerodynamics />} />
            <Route path="/contact" element={<Contact />} />
            <Route path="/case-studies/case-study-fuel-supply-capability-expansion-specification-procurement-and-commissioning" element={<CaseStudyFuelSupplyCapabilityExpansionSpecificationProcurementAndCommissioning />} />
      </Routes>
        </main>
        <Footer />
      </div>
    </Router>
  );
}

export default App;
