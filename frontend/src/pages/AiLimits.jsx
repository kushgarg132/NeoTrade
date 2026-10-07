import React from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { AI_TABS } from '../components/layout/sections';
import AutopilotSheet from '../components/settings/AutopilotSheet';

/** AI → Autopilot: everything that acts without a tap -- the autopilot, the
 * engine that feeds it, and the limits both trade inside. */
const AiLimits = () => (
  <Layout>
    <div className="space-y-3 sm:space-y-4 max-w-3xl">
      <SectionTabs tabs={AI_TABS} label="AI account" />
      <AutopilotSheet />
    </div>
  </Layout>
);

export default AiLimits;
