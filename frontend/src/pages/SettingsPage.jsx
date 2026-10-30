import React from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import { PageTitle } from '../components/settings/pageTitle';

/** One Settings page: the shell every /settings/* page shares. A section titled like the page drops its title. */
const SettingsPage = ({ title, back = '/settings', backLabel = 'Settings', right, children }) => (
  <Layout>
    <PageHeader title={title} back={back} backLabel={backLabel} right={right} />
    <PageTitle.Provider value={title}>
      <div className="space-y-4 fade-in">{children}</div>
    </PageTitle.Provider>
  </Layout>
);

export default SettingsPage;
