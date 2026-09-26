import React from 'react';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import EngineSettings from '../components/paper/EngineSettings';

/** The engine's own settings, kept inside the paper section they govern. */
const PaperSettings = () => (
  <Layout>
    <PaperShell>
      <div className="max-w-3xl">
        <EngineSettings />
      </div>
    </PaperShell>
  </Layout>
);

export default PaperSettings;
