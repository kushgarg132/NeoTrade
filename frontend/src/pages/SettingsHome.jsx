import React from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import { useAuth } from '../context/AuthContext';
import Accounts from '../components/settings/Accounts';
import Alerts from '../components/settings/Alerts';
import Limits from '../components/settings/Limits';
import Profile from '../components/settings/Profile';
import Theme from '../components/settings/Theme';
import Goal from '../components/settings/Goal';
import Lab from '../components/settings/Lab';

// Old ?tab= values from before the regroup.
const LEGACY = { broker: 'accounts', portfolio: 'limits', safety: 'limits', guardrails: 'limits', ai: 'profile', about: 'lab', beta: 'lab' };

// One plain line per tab: what it is for, before any control.
const TAB_HELP = {
  accounts: 'Connect your broker so NeoTrade can import your trades. Orders go out only when you confirm one.',
  alerts: 'Where NeoTrade reaches you when you are away from the app.',
  limits: 'Your own rules (daily loss, position size) and portfolio limits. Breaches are flagged.',
  profile: 'Who you are, and what the AI assistant knows about you.',
  theme: 'Light or dark.',
  goal: 'One target and a date. Home shows how far along you are.',
  lab: 'Admin only: experimental features and beta usage.',
};

const SettingsHome = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [params] = useSearchParams();
  const tabs = [
    { id: 'accounts', label: 'Accounts' }, { id: 'alerts', label: 'Alerts' }, { id: 'limits', label: 'Limits' },
    { id: 'profile', label: 'Profile' }, { id: 'theme', label: 'Theme' }, { id: 'goal', label: 'Goal' },
    ...(isAdmin ? [{ id: 'lab', label: 'Lab' }] : []),
  ];
  const [tab, setTab] = useTabParam(tabs.map((t) => t.id));
  const legacy = LEGACY[params.get('tab')];
  if (legacy) return <Navigate to={`/settings?tab=${legacy}`} replace />;
  return (
    <Layout>
      <PageHeader title="Settings" />
      <Tabs tabs={tabs} value={tab} onChange={setTab} label="Settings sections" wrap />
      <p className="pt-3 text-[14px] text-[var(--text-muted)]">{TAB_HELP[tab]}</p>
      <div className="pt-3">
        {tab === 'accounts' && <Accounts />}
        {tab === 'alerts' && <Alerts />}
        {tab === 'limits' && <Limits isAdmin={isAdmin} />}
        {tab === 'profile' && <Profile isAdmin={isAdmin} />}
        {tab === 'theme' && <Theme />}
        {tab === 'goal' && <Goal />}
        {tab === 'lab' && <Lab />}
      </div>
    </Layout>
  );
};

export default SettingsHome;
