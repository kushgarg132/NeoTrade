import React from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { AI_TABS } from '../components/layout/sections';
import AutopilotSheet from '../components/settings/AutopilotSheet';
import EngineSwitches from '../components/settings/EngineSwitches';

/** AI → Autopilot: everything that acts without a tap -- the engine's own
 * switches, then the autopilot's switch, live mode and fence. */
const AiLimits = () => (
  <Layout>
    <div className="space-y-3 sm:space-y-4 max-w-3xl">
      <SectionTabs tabs={AI_TABS} label="AI account" />
      <EngineSwitches />
      <AutopilotSheet />
    </div>
  </Layout>
);

export default AiLimits;
