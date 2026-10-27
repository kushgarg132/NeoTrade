import React from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Empty from '../components/ui/Empty';

/** Stub: the detail body lands in wave 2. */
const SectorPage = () => (
  <Layout>
    <PageHeader title="Sector" back="/market" backLabel="Market" />
    <Empty title="Coming soon" />
  </Layout>
);

export default SectorPage;
