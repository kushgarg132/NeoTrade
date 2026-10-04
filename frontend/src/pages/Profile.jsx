import React, { useEffect, useState } from 'react';
import { Trash2, X } from 'lucide-react';
import Layout from '../components/Layout';
import { Sheet, Ruling, Empty } from '../components/doc/Doc';
import { Button } from '../components/common/Button';
import { Avatar } from '../components/common/Avatar';
import { Row } from '../components/settings/Fields';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { useAuth } from '../context/AuthContext';
import { formatDateTime } from '../utils/formatters';

/**
 * Who the user is (their Google identity) and what they tell NeoTrade about
 * themselves. Everything here rides along with every chat message, on the
 * web and on Telegram, so the assistant can answer for this trader.
 */

const LIMITS = { display_name: 60, horizon: 60, goals: 500, constraints: 500, about_me: 1500, answer_style: 1500 };
const MAX_CHIPS = 20;
const EXPERIENCE = ['beginner', 'intermediate', 'advanced'];
const RISK = ['low', 'medium', 'high'];
const STYLES = [
  ['intraday', 'Intraday'], ['swing', 'Swing'], ['longterm', 'Long-term'], ['options', 'Options'],
];

const inputClass =
  'w-full bg-transparent border-b border-[var(--rule-strong)] py-1.5 text-sm focus:outline-none focus:border-[var(--stamp)]';

const Counter = ({ value, limit }) => (
  <span className={cn('doc-meta', (value || '').length > limit && 'text-[var(--loss)]')}>
    {(value || '').length}/{limit}
  </span>
);

const TextInput = ({ id, label, value, onChange, placeholder }) => (
  <div>
    <div className="flex items-baseline justify-between mb-1">
      <label htmlFor={id} className="field-label">{label}</label>
      <Counter value={value} limit={LIMITS[id]} />
    </div>
    <input id={id} value={value || ''} placeholder={placeholder} autoComplete="off"
      onChange={(e) => onChange(e.target.value)} className={inputClass} />
  </div>
);

const TextArea = ({ id, label, hint, value, onChange, placeholder, rows = 4 }) => (
  <div>
    <div className="flex items-baseline justify-between mb-1">
      <label htmlFor={id} className="field-label">{label}</label>
      <Counter value={value} limit={LIMITS[id]} />
    </div>
    {hint && <p className="doc-meta normal-case mb-1.5">{hint}</p>}
    <textarea id={id} rows={rows} value={value || ''} placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-transparent border border-[var(--rule-strong)] p-2 text-sm focus:outline-none focus:border-[var(--stamp)] resize-y" />
  </div>
);

/** One-of choice; tapping the chosen option clears it. */
const Segmented = ({ options, value, onChange, label }) => (
  <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
    {options.map((option) => (
      <button key={option} type="button" role="radio" aria-checked={value === option}
        onClick={() => onChange(value === option ? '' : option)}
        className={cn(
          'h-11 sm:h-8 px-3 text-xs capitalize border transition-colors',
          value === option
            ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
            : 'border-[var(--rule-strong)] text-[var(--ink-soft)] hover:border-[var(--ink)]',
        )}>
        {option}
      </button>
    ))}
  </div>
);

const ChipInput = ({ id, label, hint, value = [], onChange, placeholder }) => {
  const [text, setText] = useState('');
  const add = () => {
    const item = text.trim().slice(0, 40);
    if (item && !value.includes(item) && value.length < MAX_CHIPS) onChange([...value, item]);
    setText('');
  };
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label htmlFor={id} className="field-label">{label}</label>
        <span className="doc-meta">{value.length}/{MAX_CHIPS}</span>
      </div>
      {hint && <p className="doc-meta normal-case mb-1.5">{hint}</p>}
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {value.map((item) => (
          <span key={item} className="inline-flex items-center gap-1 pl-2 pr-1 h-8 text-xs border border-[var(--rule-strong)]">
            {item}
            <button type="button" onClick={() => onChange(value.filter((v) => v !== item))}
              className="p-1 text-[var(--ink-faint)] hover:text-[var(--loss)]" aria-label={`Remove ${item}`}>
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
      </div>
      <input id={id} value={text} placeholder={placeholder} autoComplete="off"
        disabled={value.length >= MAX_CHIPS}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}
        onBlur={add} className={inputClass} />
    </div>
  );
};

const LIST_FIELDS = new Set(['styles', 'favour', 'avoid']);
const empty = (field) => (LIST_FIELDS.has(field) ? [] : '');
/** The value as the server stores it: trimmed text, absent when blank. */
const normal = (field, value) => {
  if (LIST_FIELDS.has(field)) return JSON.stringify(value || []);
  return typeof value === 'string' ? value.trim() : value ?? '';
};
const draftFrom = (fields, profile) => Object.fromEntries(fields.map((f) => [f, profile[f] ?? empty(f)]));

/** A sheet whose fields save together with one button. */
const FormSheet = ({ title, meta, fields, profile, onSaved, children }) => {
  const [draft, setDraft] = useState(() => draftFrom(fields, profile));
  const [state, setState] = useState(null);
  const dirty = fields.some((f) => normal(f, draft[f]) !== normal(f, profile[f]));
  const save = () => {
    setState({ busy: true });
    const body = Object.fromEntries(fields.map((f) => [f, draft[f] ?? empty(f)]));
    api.put(endpoints.profile.get, body)
      .then((res) => { onSaved(res.data); setDraft(draftFrom(fields, res.data)); setState({ saved: true }); })
      .catch((err) => {
        const detail = err?.response?.data?.detail;
        setState({ error: Array.isArray(detail) ? 'Some fields are too long or invalid.' : detail || 'Could not save.' });
      });
  };
  const set = (key) => (value) => { setDraft((d) => ({ ...d, [key]: value })); setState(null); };
  return (
    <Sheet title={title} meta={meta}>
      <div className="space-y-4">{children(draft, set)}</div>
      <div className="flex items-center justify-end gap-3 pt-4">
        {state?.error && <span className="doc-meta normal-case text-[var(--loss)]">{state.error}</span>}
        {state?.saved && !dirty && <span className="doc-meta normal-case text-[var(--gain)]">Saved</span>}
        <Button size="sm" onClick={save} disabled={!dirty || state?.busy}>Save</Button>
      </div>
    </Sheet>
  );
};

const MemorySheet = ({ memories, onChange }) => {
  const [text, setText] = useState('');
  const [error, setError] = useState(null);
  const add = () => {
    if (!text.trim()) return;
    api.post(endpoints.profile.memories, { text })
      .then((res) => { onChange([...memories, res.data]); setText(''); setError(null); })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not add that.'));
  };
  const remove = (id) =>
    api.delete(`${endpoints.profile.memories}/${id}`)
      .then(() => onChange(memories.filter((m) => m.id !== id)))
      .catch(() => setError('Could not delete that.'));
  return (
    <Sheet title="Memory" meta={`${memories.length}/50`}>
      <p className="doc-meta normal-case mb-3">
        Things NeoTrade remembers about you. NeoTrade asks before it remembers anything you say in chat.
      </p>
      {memories.length === 0 ? (
        <Empty title="Nothing remembered yet" detail="Tell the assistant about a goal or a preference, or add one here." />
      ) : (
        <ul className="divide-y divide-[var(--rule)]">
          {memories.map((m) => (
            <li key={m.id} className="flex items-start gap-3 py-2.5">
              <div className="flex-1 min-w-0">
                <p className="text-sm">{m.text}</p>
                <p className="doc-meta">{m.source === 'chat' ? 'From chat' : 'Added by you'} · {formatDateTime(m.created_at)}</p>
              </div>
              <button type="button" onClick={() => remove(m.id)} aria-label="Delete memory"
                className="p-2 text-[var(--ink-faint)] hover:text-[var(--loss)]">
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2 pt-3">
        <input value={text} maxLength={200} placeholder="e.g. Saving for a house in 2028" aria-label="New memory"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') add(); }} className={inputClass} />
        <Button size="sm" variant="secondary" onClick={add} disabled={!text.trim() || memories.length >= 50}>Add</Button>
      </div>
      {error && <p className="doc-meta normal-case text-[var(--loss)] pt-2">{error}</p>}
    </Sheet>
  );
};

const Profile = () => {
  const { logout } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get(endpoints.profile.get)
      .then((res) => setData(res.data))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load your profile.'));
  }, []);

  const saved = (profile) => setData((d) => ({ ...d, profile }));

  if (!data) {
    return (
      <Layout>
        <div className="max-w-3xl">
          {error ? <Empty title="Profile unavailable" detail={error} /> : <Sheet title="Profile"><Ruling rows={4} /></Sheet>}
        </div>
      </Layout>
    );
  }

  const { account, profile } = data;
  const name = profile.display_name || account.name;
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <Sheet title="Account" meta={account.role === 'admin' ? 'Admin' : undefined}>
          <div className="flex items-center gap-4">
            <Avatar src={account.picture} name={name} size={64} />
            <div className="flex-1 min-w-0">
              <p className="text-base font-semibold truncate">{name}</p>
              <p className="doc-meta normal-case truncate">{account.email}</p>
              <p className="doc-meta">Member since {formatDateTime(account.created_at)}</p>
            </div>
            <Button size="sm" variant="ghost" onClick={logout}>Sign out</Button>
          </div>
          <p className="doc-meta normal-case pt-3">Name and photo come from your Google account.</p>
        </Sheet>

        <FormSheet title="Display name" fields={['display_name']} profile={profile} onSaved={saved}>
          {(draft, set) => (
            <TextInput id="display_name" label="What NeoTrade calls you" value={draft.display_name}
              onChange={set('display_name')} placeholder={account.name} />
          )}
        </FormSheet>

        <FormSheet title="Trading profile" fields={['experience', 'risk_appetite', 'styles', 'horizon', 'goals']}
          profile={profile} onSaved={saved}>
          {(draft, set) => (
            <>
              <Row label="Experience"><Segmented label="Experience" options={EXPERIENCE} value={draft.experience} onChange={set('experience')} /></Row>
              <Row label="Risk appetite"><Segmented label="Risk appetite" options={RISK} value={draft.risk_appetite} onChange={set('risk_appetite')} /></Row>
              <Row label="How you trade" hint="Pick any">
                <div className="flex flex-wrap gap-1.5">
                  {STYLES.map(([id, label]) => {
                    const on = (draft.styles || []).includes(id);
                    return (
                      <button key={id} type="button" aria-pressed={on}
                        onClick={() => set('styles')(on ? draft.styles.filter((s) => s !== id) : [...(draft.styles || []), id])}
                        className={cn('h-11 sm:h-8 px-3 text-xs border transition-colors',
                          on ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]'
                            : 'border-[var(--rule-strong)] text-[var(--ink-soft)] hover:border-[var(--ink)]')}>
                        {label}
                      </button>
                    );
                  })}
                </div>
              </Row>
              <TextInput id="horizon" label="Investment horizon" value={draft.horizon} onChange={set('horizon')} placeholder="e.g. 3-5 years" />
              <TextArea id="goals" label="Goals" rows={3} value={draft.goals} onChange={set('goals')}
                placeholder="e.g. Grow a retirement corpus; learn options safely" />
            </>
          )}
        </FormSheet>

        <FormSheet title="Preferences" fields={['favour', 'avoid', 'constraints']} profile={profile} onSaved={saved}>
          {(draft, set) => (
            <>
              <ChipInput id="favour" label="Favour" hint="Sectors or stocks you like. Press Enter to add."
                value={draft.favour || []} onChange={set('favour')} placeholder="e.g. IT, HDFCBANK" />
              <ChipInput id="avoid" label="Avoid" hint="Never suggested to you."
                value={draft.avoid || []} onChange={set('avoid')} placeholder="e.g. Tobacco, PSU banks" />
              <TextArea id="constraints" label="Constraints" rows={3} value={draft.constraints} onChange={set('constraints')}
                placeholder="e.g. No F&O; new tax regime; monthly SIP of ₹20,000" />
            </>
          )}
        </FormSheet>

        <FormSheet title="AI instructions" meta="Used in every chat, web and Telegram"
          fields={['about_me', 'answer_style']} profile={profile} onSaved={saved}>
          {(draft, set) => (
            <>
              <TextArea id="about_me" label="About me" value={draft.about_me} onChange={set('about_me')}
                hint="What should NeoTrade know about you?"
                placeholder="e.g. Salaried engineer in Bengaluru, trade before work, new to swing trading" />
              <TextArea id="answer_style" label="How should NeoTrade answer?" value={draft.answer_style} onChange={set('answer_style')}
                placeholder="e.g. Short bullet points, explain jargon, Hinglish is fine" />
            </>
          )}
        </FormSheet>

        <MemorySheet memories={profile.memories || []} onChange={(memories) => saved({ ...profile, memories })} />
      </div>
    </Layout>
  );
};

export default Profile;
