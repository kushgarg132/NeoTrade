import React from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';

/** One Settings page: the shell every /settings/* page shares. */
const SettingsPage = ({ title, back = '/settings', backLabel = 'Settings', right, children }) => (
  <Layout>
    <PageHeader title={title} back={back} backLabel={backLabel} right={right} />
    <div className="space-y-3">{children}</div>
  </Layout>
);

export default SettingsPage;
