import React, { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import ListRow from '../components/ui/ListRow';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/useTheme';
import api, { endpoints, getPreferences } from '../utils/api';
import {
  settingsRedirect, brokersState, guardrailsState, portfolioState, telegramState, goalState, modelState, autopilotState,
} from '../utils/settings';

const THEMES = [['light', 'Light'], ['dark', 'Dark']];

const Group = ({ title, children }) => (
  <section aria-label={title}>
    <h2 className="px-1 pb-1.5 text-[13px] font-medium text-[var(--text-muted)]">{title}</h2>
    <div className="rounded-[16px] border border-[var(--border)] bg-[var(--surface)] px-4">{children}</div>
  </section>
);

const Row = ({ title, state, to }) => <ListRow title={title} right={state} to={to} privateValue={false} />;

const Appearance = () => {
  const { theme, setTheme } = useTheme();
  return (
    <div className="flex items-center gap-3 min-h-14 py-2">
      <span className="flex-1 text-[15px] font-medium text-[var(--text)]">Appearance</span>
      <div role="radiogroup" aria-label="Theme" className="flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
        {THEMES.map(([id, label]) => (
          <button key={id} type="button" role="radio" aria-checked={theme === id} onClick={() => setTheme(id)}
                  className={`min-h-11 px-4 rounded-[8px] text-[14px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${theme === id ? 'bg-[var(--surface)] text-[var(--text)] shadow-sm' : 'text-[var(--text-muted)]'}`}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
};

const SettingsHome = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const { search } = useLocation();
  // A failed read leaves its state undefined, which every state helper shows as "–".
  const [prefs, setPrefs] = useState(undefined);
  const [telegram, setTelegram] = useState(undefined);
  useEffect(() => {
    let live = true;
    getPreferences().then((res) => live && setPrefs(res.data)).catch(() => {});
    api.get(endpoints.guardrails.telegram).then((res) => live && setTelegram(res.data)).catch(() => {});
    return () => { live = false; };
  }, []);

  const old = settingsRedirect(search);
  if (old) return <Navigate replace to={old} />;

  return (
    <Layout>
      <PageHeader title="Settings" />
      <div className="space-y-4">
        <Group title="Account">
          <Row title="Profile" state={user?.name || '–'} to="/settings/profile" />
          <Row title="Brokers" state={brokersState(prefs)} to="/settings/brokers" />
        </Group>
        <Group title="Safety">
          <Row title="Guardrails & daily loss" state={guardrailsState(prefs)} to="/settings/guardrails" />
          <Row title="Portfolio review" state={portfolioState(prefs)} to="/settings/portfolio" />
        </Group>
        <Group title="Notifications">
          <Row title="Telegram & alerts" state={telegramState(telegram)} to="/settings/notifications" />
        </Group>
        <Group title="You">
          <Row title="Goal" state={goalState(prefs)} to="/settings/goal" />
          <Row title="AI model" state={modelState(prefs)} to="/settings/ai" />
          <Appearance />
        </Group>
        {isAdmin && (
          <Group title="Admin">
            <Row title="Autopilot" state={autopilotState(prefs)} to="/settings/autopilot" />
            <Row title="Lab" to="/settings/lab" />
          </Group>
        )}
      </div>
    </Layout>
  );
};

export default SettingsHome;
