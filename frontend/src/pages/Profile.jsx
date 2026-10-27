import React, { useEffect, useState } from 'react';
import { Trash2, X } from 'lucide-react';
import Layout from '../components/Layout';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
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

const RISK_HELP = 'How much loss you can sit through. Shapes how the assistant frames ideas; it is not a limit (set those under Settings, Limits).';
const LABEL = 'text-[13px] font-medium text-[var(--text-muted)]';
const META = 'text-[13px] text-[var(--text-muted)]';

/** Local stand-in for the old doc Sheet: a Card with a muted line under the title. */
const Sheet = ({ title, meta, children }) => (
  <Card title={title}>
    {meta && <p className={`${META} -mt-2 mb-3`}>{meta}</p>}
    {children}
  </Card>
);

const inputClass =
  'w-full bg-[var(--surface)] border border-[var(--border)] rounded-[12px] px-3 min-h-11 text-[15px] focus:outline-none focus:border-[var(--accent)]';

const Counter = ({ value, limit }) => (
  <span className={cn('text-[13px] text-[var(--text-muted)] tabular-nums', (value || '').length > limit && 'text-[var(--loss)]')}>
    {(value || '').length}/{limit}
  </span>
);

const TextInput = ({ id, label, value, onChange, placeholder }) => (
  <div>
    <div className="flex items-baseline justify-between mb-1">
      <label htmlFor={id} className={LABEL}>{label}</label>
      <Counter value={value} limit={LIMITS[id]} />
    </div>
    <input id={id} value={value || ''} placeholder={placeholder} autoComplete="off"
      onChange={(e) => onChange(e.target.value)} className={inputClass} />
  </div>
);

const TextArea = ({ id, label, hint, value, onChange, placeholder, rows = 4 }) => (
  <div>
    <div className="flex items-baseline justify-between mb-1">
      <label htmlFor={id} className={LABEL}>{label}</label>
      <Counter value={value} limit={LIMITS[id]} />
    </div>
    {hint && <p className={`${META} mb-1.5`}>{hint}</p>}
    <textarea id={id} rows={rows} value={value || ''} placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-[var(--surface)] border border-[var(--border)] rounded-[12px] p-3 text-[15px] focus:outline-none focus:border-[var(--accent)] resize-y" />
  </div>
);

/** One-of choice; tapping the chosen option clears it. */
const Segmented = ({ options, value, onChange, label }) => (
  <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
    {options.map((option) => (
      <button key={option} type="button" role="radio" aria-checked={value === option}
        onClick={() => onChange(value === option ? '' : option)}
        className={cn(
          'min-h-11 px-4 rounded-full text-[14px] font-semibold capitalize border transition-colors',
          value === option
            ? 'bg-[var(--text)] text-[var(--surface)] border-[var(--text)]'
            : 'border-[var(--border)] text-[var(--text-muted)]',
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
        <label htmlFor={id} className={LABEL}>{label}</label>
        <span className={`${META} tabular-nums`}>{value.length}/{MAX_CHIPS}</span>
      </div>
      {hint && <p className={`${META} mb-1.5`}>{hint}</p>}
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {value.map((item) => (
          <span key={item} className="inline-flex items-center gap-1 pl-3 pr-1 min-h-11 text-[14px] rounded-full border border-[var(--border)]">
            {item}
            <button type="button" onClick={() => onChange(value.filter((v) => v !== item))}
              className="min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]" aria-label={`Remove ${item}`}>
              <X className="w-4 h-4" />
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
        {state?.error && <span role="alert" className="text-[13px] text-[var(--loss)]">{state.error}</span>}
        {state?.saved && !dirty && <span role="status" className="text-[13px] text-[var(--gain)]">Saved</span>}
        <Button onClick={save} disabled={!dirty || state?.busy}>Save</Button>
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
    <Sheet title="Memory" meta={`${memories.length} of 50 saved. The assistant reads these in every chat.`}>
      <p className={`${META} mb-3`}>
        Things NeoTrade remembers about you. NeoTrade asks before it remembers anything you say in chat.
      </p>
      {memories.length === 0 ? (
        <Empty title="Nothing remembered yet" body="Tell the assistant about a goal or a preference in chat, or add one below." action={<a href="#new-memory" className="inline-flex items-center min-h-11 text-[15px] font-semibold text-[var(--accent)]">Add a memory</a>} />
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {memories.map((m) => (
            <li key={m.id} className="flex items-start gap-3 py-2.5">
              <div className="flex-1 min-w-0">
                <p className="text-[15px]">{m.text}</p>
                <p className={META}>{m.source === 'chat' ? 'From chat' : 'Added by you'} · {formatDateTime(m.created_at)}</p>
              </div>
              <button type="button" onClick={() => remove(m.id)} aria-label="Delete memory"
                className="min-h-11 min-w-11 inline-flex items-center justify-center text-[var(--text-muted)]">
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2 pt-3">
        <input id="new-memory" value={text} maxLength={200} placeholder="e.g. Saving for a house in 2028" aria-label="New memory"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') add(); }} className={inputClass} />
        <Button variant="secondary" onClick={add} disabled={!text.trim() || memories.length >= 50}>Add</Button>
      </div>
      {error && <p role="alert" className="text-[13px] text-[var(--loss)] pt-2">{error}</p>}
    </Sheet>
  );
};

const Profile = () => {
  const { logout } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const [tick, setTick] = useState(0);
  useEffect(() => {
    api.get(endpoints.profile.get)
      .then((res) => { setData(res.data); setError(null); })
      .catch(() => setError("Couldn't load your profile."));
  }, [tick]);

  const saved = (profile) => setData((d) => ({ ...d, profile }));

  if (!data) {
    return (
      <Layout>
        <div className="max-w-3xl">
          <PageHeader title="Profile" back="/settings" />
          <Card>{error ? <ErrorLine message={error} onRetry={() => { setError(null); setTick((t) => t + 1); }} /> : <Skeleton rows={4} />}</Card>
        </div>
      </Layout>
    );
  }

  const { account, profile } = data;
  const name = profile.display_name || account.name;
  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <PageHeader title="Profile" back="/settings" />
        <Sheet title="Account" meta={account.role === 'admin' ? 'Admin' : undefined}>
          <div className="flex items-center gap-4">
            <Avatar src={account.picture} name={name} size={64} />
            <div className="flex-1 min-w-0">
              <p className="text-base font-semibold truncate">{name}</p>
              <p className={`${META} truncate`}>{account.email}</p>
              <p className={META}>Member since {formatDateTime(account.created_at)}</p>
            </div>
            <Button variant="secondary" onClick={logout}>Sign out</Button>
          </div>
          <p className={`${META} pt-3`}>Name and photo come from your Google account.</p>
        </Sheet>

        <FormSheet title="Display name" meta="Shown on this page and used by the assistant." fields={['display_name']} profile={profile} onSaved={saved}>
          {(draft, set) => (
            <TextInput id="display_name" label="What NeoTrade calls you" value={draft.display_name}
              onChange={set('display_name')} placeholder={account.name} />
          )}
        </FormSheet>

        <FormSheet title="Trading profile" meta="Tells the assistant how to talk to you. Nothing here changes your orders or limits." fields={['experience', 'risk_appetite', 'styles', 'horizon', 'goals']}
          profile={profile} onSaved={saved}>
          {(draft, set) => (
            <>
              <Row label="Experience"><Segmented label="Experience" options={EXPERIENCE} value={draft.experience} onChange={set('experience')} /></Row>
              <Row label="Risk appetite" hint={RISK_HELP}><Segmented label="Risk appetite" options={RISK} value={draft.risk_appetite} onChange={set('risk_appetite')} /></Row>
              <Row label="How you trade" hint="Pick any">
                <div className="flex flex-wrap gap-1.5">
                  {STYLES.map(([id, label]) => {
                    const on = (draft.styles || []).includes(id);
                    return (
                      <button key={id} type="button" aria-pressed={on}
                        onClick={() => set('styles')(on ? draft.styles.filter((s) => s !== id) : [...(draft.styles || []), id])}
                        className={cn('min-h-11 px-4 rounded-full text-[14px] font-semibold border transition-colors',
                          on ? 'bg-[var(--text)] text-[var(--surface)] border-[var(--text)]'
                            : 'border-[var(--border)] text-[var(--text-muted)]')}>
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
              <ChipInput id="avoid" label="Avoid" hint="The assistant will not suggest these to you."
                value={draft.avoid || []} onChange={set('avoid')} placeholder="e.g. Tobacco, PSU banks" />
              <TextArea id="constraints" label="Constraints" rows={3} value={draft.constraints} onChange={set('constraints')}
                placeholder="e.g. No F&O; new tax regime; monthly SIP of ₹20,000" />
            </>
          )}
        </FormSheet>

        <FormSheet title="AI instructions" meta="Used in every chat, on the web and on Telegram."
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
