import React from 'react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Empty from '../components/ui/Empty';

/** Stub: the detail body lands in wave 2. */
const NewsItem = () => (
  <Layout>
    <PageHeader title="News" back="/market" backLabel="Market" />
    <Empty title="Coming soon" />
  </Layout>
);

export default NewsItem;
