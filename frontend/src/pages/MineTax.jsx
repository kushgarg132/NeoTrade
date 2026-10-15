import React from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { MINE_TABS } from '../components/layout/sections';
import { Sheet, Empty } from '../components/doc/Doc';

// Stub until its task replaces this file.
const MineTax = () => (
  <Layout>
    <div className="space-y-3">
      <SectionTabs tabs={MINE_TABS} label="My account" />
      <Sheet title="Tax">
        <Empty title="Coming soon" detail="This page is being rebuilt." />
      </Sheet>
    </div>
  </Layout>
);

export default MineTax;
