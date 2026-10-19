import React from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { LAB_TABS } from '../components/layout/sections';
import AutopilotSheet from '../components/settings/AutopilotSheet';
import EngineSettings from '../components/paper/EngineSettings';

/** AI → Settings: everything that acts without a tap -- the autopilot, the
 * engine that feeds it, the limits both trade inside, and each strategy's
 * paper / live switch with what it still needs. */
const AiLimits = () => (
  <Layout>
    <div className="space-y-3 sm:space-y-4 max-w-3xl">
      <SectionTabs tabs={LAB_TABS} label="Lab" />
      <AutopilotSheet />
      <EngineSettings />
    </div>
  </Layout>
);

export default AiLimits;
