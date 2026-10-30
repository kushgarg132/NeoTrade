import React, { useEffect, useState } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import { toneText } from '../components/ui/tone';
import { Avatar } from '../components/common/Avatar';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/useTheme';
import api, { endpoints, getPreferences } from '../utils/api';
import {
  settingsRedirect, accountsOf, brokerName, needsYou, SESSION,
  guardrailsLine, portfolioLine, goalLine, autopilotLine, modelLine, alertsLine,
} from '../utils/settings';

const THEMES = [['light', 'Light'], ['dark', 'Dark']];
const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]';

/** A value inside a sentence: the part you would change. */
const Chip = ({ v, tone, private: priv }) => (
  <span className={`${priv ? 'private figure-md ' : ''}inline-block rounded-full bg-[var(--surface-2)] px-2 py-px font-semibold tabular-nums ${toneText(tone)}`}>{v}</span>
);

// A full stop right after a pill reads as stray punctuation: a sentence that ends on a value ends there.
const trim = (parts) => (parts.length > 1 && parts.at(-1) === '.' && typeof parts.at(-2) !== 'string' ? parts.slice(0, -1) : parts);

/** One setting as a sentence; the whole line opens its page. A line whose data failed shows a dash. */
const Line = ({ parts, to, label }) => (
  <Link to={to} className={`tap flex items-center gap-3 min-h-14 py-3 border-b border-[var(--border)] last:border-b-0 ${FOCUS}`}>
    <span className="flex-1 min-w-0 text-[15px] leading-7 text-[var(--text-muted)]">
      {parts ? trim(parts).map((p, i) => (typeof p === 'string' ? <span key={i}>{p}</span> : <Chip key={i} {...p} />)) : <>{label} <Chip v="–" /></>}
    </span>
    <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
  </Link>
);

/** A group: its name, and on account groups the broker with its session. */
const Group = ({ title, account, children }) => {
  const [word, tone] = SESSION[account?.state] || [];
  return (
    <section aria-label={title}>
      <div className="flex items-baseline justify-between gap-3 px-1 pb-1.5">
        <h2 className="text-[13px] font-semibold text-[var(--text-muted)]">{title}</h2>
        {account && (
          <span className="text-[13px] text-[var(--text-muted)]">
            {brokerName(account.broker)}
            {word && <span className={`ml-1.5 font-semibold ${toneText(tone)}`}><span aria-hidden="true">● </span>{word}</span>}
          </span>
        )}
      </div>
      <div className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4">{children}</div>
    </section>
  );
};

/** What is broken, each with its one fix. Absent when nothing is. */
const NeedsYou = ({ items }) => (
  <section aria-label="Needs you" className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4">
    {items.map((it) => (
      <div key={it.text} className="flex items-center gap-3 min-h-14 py-2 border-b border-[var(--border)] last:border-b-0">
        <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${it.tone === 'loss' ? 'bg-[var(--loss)]' : 'bg-[var(--warn)]'}`} />
        <span className="flex-1 min-w-0 text-[15px] font-medium text-[var(--text)]">{it.text}</span>
        <Link to={it.to} className={`tap shrink-0 inline-flex items-center min-h-11 px-4 rounded-[12px] bg-[var(--accent)] text-[var(--accent-ink)] text-[14px] font-semibold ${FOCUS}`}>
          {it.action}
        </Link>
      </div>
    ))}
  </section>
);

const Appearance = () => {
  const { theme, setTheme } = useTheme();
  return (
    <div className="flex items-center gap-3 min-h-14 py-2">
      <span className="flex-1 text-[15px] text-[var(--text-muted)]">Theme</span>
      <div role="radiogroup" aria-label="Theme" className="flex gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
        {THEMES.map(([id, label]) => (
          <button key={id} type="button" role="radio" aria-checked={theme === id} onClick={() => setTheme(id)}
                  className={`min-h-11 px-4 rounded-[8px] text-[14px] font-medium ${FOCUS} ${theme === id ? 'bg-[var(--surface)] text-[var(--text)]' : 'text-[var(--text-muted)]'}`}>
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
  // A failed read leaves its state undefined: its line shows a dash and Needs you stays quiet about it.
  const [prefs, setPrefs] = useState(undefined);
  const [today, setToday] = useState(null);
  const [telegram, setTelegram] = useState(undefined);
  const [displayName, setDisplayName] = useState(null);
  const [models, setModels] = useState(undefined);
  useEffect(() => {
    let live = true;
    getPreferences().then((res) => live && setPrefs(res.data)).catch(() => {});
    // Broker sessions and the kill switch: the same answer Home shows, cached server-side for a minute.
    api.get(endpoints.today).then((res) => live && setToday(res.data)).catch(() => {});
    api.get(endpoints.guardrails.status).then((res) => live && setTelegram(res.data.telegram)).catch(() => {});
    Promise.all([api.get(endpoints.settings.omnirouteTiers), api.get(endpoints.settings.omnirouteModel)])
      .then(([t, m]) => live && setModels({ tiers: t.data.tiers, fallback: m.data.model })).catch(() => {});
    api.get(endpoints.profile.get).then((res) => live && setDisplayName(res.data.profile.display_name || null)).catch(() => {});
    return () => { live = false; };
  }, []);

  const old = settingsRedirect(search);
  if (old) return <Navigate replace to={old} />;

  const accounts = prefs === undefined && !today ? null : accountsOf(prefs, today);
  const needs = needsYou({ accounts, today, telegram });
  const name = displayName || user?.name;
  const profile = (
    <Link to="/profile" aria-label={`Your profile${name ? `: ${name}` : ''}`} className={`tap rounded-full ${FOCUS}`}>
      <Avatar src={user?.picture} name={name} size={44} />
    </Link>
  );

  return (
    <Layout>
      <PageHeader title="Settings" right={profile} />
      <div className="space-y-5 fade-in">
        {needs.length > 0 && <NeedsYou items={needs} />}
        <Group title="Your account" account={accounts?.mine}>
          <Line parts={guardrailsLine(prefs)} to="/settings/guardrails" label="Guardrails" />
          <Line parts={portfolioLine(prefs)} to="/settings/portfolio" label="Portfolio review" />
          <Line parts={goalLine(prefs)} to="/settings/goal" label="Goal" />
        </Group>
        <Group title="AI account" account={accounts?.ai}>
          {isAdmin && <Line parts={autopilotLine(prefs)} to="/settings/autopilot" label="Autopilot" />}
          <Line parts={modelLine(models)} to="/settings/ai" label="AI model" />
        </Group>
        <Group title="App">
          <Line parts={alertsLine(telegram, prefs)} to="/settings/notifications" label="Notifications" />
          <Line parts={['Brokers and which account is which.']} to="/settings/brokers" label="Brokers" />
          <Appearance />
        </Group>
        {isAdmin && (
          <Group title="Admin">
            <Line parts={['Lab: strategies, runs, forward record, handbook.']} to="/settings/lab" label="Lab" />
          </Group>
        )}
      </div>
    </Layout>
  );
};

export default SettingsHome;
