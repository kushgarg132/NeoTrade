import React, { useEffect, useState } from 'react';
import { Trash2, X } from 'lucide-react';
import Layout from '../components/Layout';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import PageHeader from '../components/ui/PageHeader';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import { Avatar } from '../components/common/Avatar';
import { Row, Segmented } from '../components/settings/Fields';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { useAuth } from '../context/AuthContext';
import { formatDateTime, formatNoteDate } from '../utils/formatters';

/**
 * Who the user is (their Google identity) and what they tell NeoTrade about
 * themselves. Everything here rides along with every chat message, on the
 * web and on Telegram, so the assistant can answer for this trader.
 * Each section reads as sentences; Edit swaps that one section to its form.
 */

const LIMITS = { display_name: 60, horizon: 60, goals: 500, constraints: 500, about_me: 1500, answer_style: 1500 };
const MAX_CHIPS = 20;
const EXPERIENCE = [['beginner', 'Beginner'], ['intermediate', 'Intermediate'], ['advanced', 'Advanced']];
const RISK = [['low', 'Low'], ['medium', 'Medium'], ['high', 'High']];
const STYLES = [
  ['intraday', 'Intraday'], ['swing', 'Swing'], ['longterm', 'Long-term'], ['options', 'Options'],
];
const STYLE_LABEL = Object.fromEntries(STYLES);

const RISK_HELP = 'How much loss you can sit through. Shapes how the assistant frames ideas; it is not a limit (set those under Settings, Limits).';
const LABEL = 'text-[13px] font-medium text-[var(--text-muted)]';
const META = 'text-[13px] text-[var(--text-muted)]';
const FOCUS = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]';
const CARD = 'rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4';

const inputClass =
  'w-full bg-[var(--surface-2)] border border-[var(--border)] rounded-[12px] px-3 min-h-11 text-[15px] text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]';

/** A value inside a sentence: the part you would change (the same chip as Settings home). */
const Chip = ({ children }) => (
  <span className="inline-block rounded-full bg-[var(--surface-2)] px-2 py-px font-semibold text-[var(--text)]">{children}</span>
);

/** Several values in a sentence, chips separated by a space so the line wraps between them. */
const chips = (items) => items.flatMap((v, i) => [i ? ' ' : null, <Chip key={v}>{v}</Chip>]);

/** One sentence; empty parts drop out. */
const Line = ({ children }) => (
  <p className="py-3 border-b border-[var(--border)] last:border-b-0 text-[15px] leading-7 text-[var(--text-muted)]">{children}</p>
);

/** Free text the user wrote, under a small label, folded to three lines. */
const Prose = ({ label, text }) => (
  <div className="py-3 border-b border-[var(--border)] last:border-b-0">
    <p className={LABEL}>{label}</p>
    <p className="mt-0.5 text-[15px] leading-6 text-[var(--text)] whitespace-pre-line line-clamp-3">{text}</p>
  </div>
);

const Counter = ({ value, limit }) => (
  <span className={cn('text-[13px] text-[var(--text-muted)] tabular-nums', (value || '').length > limit && 'text-[var(--loss)]')}>
    {(value || '').length}/{limit}
  </span>
);

const TextInput = ({ id, label, value, onChange, placeholder }) => (
  <div className="py-3">
    <div className="flex items-baseline justify-between mb-1">
      <label htmlFor={id} className={LABEL}>{label}</label>
      <Counter value={value} limit={LIMITS[id]} />
    </div>
    <input id={id} value={value || ''} placeholder={placeholder} autoComplete="off"
      onChange={(e) => onChange(e.target.value)} className={inputClass} />
  </div>
);

const TextArea = ({ id, label, hint, value, onChange, placeholder, rows = 4 }) => (
  <div className="py-3">
    <div className="flex items-baseline justify-between mb-1">
      <label htmlFor={id} className={LABEL}>{label}</label>
      <Counter value={value} limit={LIMITS[id]} />
    </div>
    {hint && <p className={`${META} mb-1.5`}>{hint}</p>}
    <textarea id={id} rows={rows} value={value || ''} placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={cn(inputClass, 'p-3 resize-y')} />
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
    <div className="py-3">
      <div className="flex items-baseline justify-between mb-1">
        <label htmlFor={id} className={LABEL}>{label}</label>
        <span className={`${META} tabular-nums`}>{value.length}/{MAX_CHIPS}</span>
      </div>
      {hint && <p className={`${META} mb-1.5`}>{hint}</p>}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-1.5">
          {value.map((item) => (
            <span key={item} className="inline-flex items-center gap-0.5 pl-3 min-h-11 text-[14px] font-semibold rounded-full bg-[var(--surface-2)] text-[var(--text)]">
              {item}
              <button type="button" onClick={() => onChange(value.filter((v) => v !== item))}
                className={`min-h-11 min-w-11 inline-flex items-center justify-center rounded-full text-[var(--text-muted)] ${FOCUS}`} aria-label={`Remove ${item}`}>
                <X className="w-4 h-4" />
              </button>
            </span>
          ))}
        </div>
      )}
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
const told = (profile, fields) => fields.some((f) => normal(f, profile[f]) !== normal(f, empty(f)));

/** The section's name, and on the right the one way to change it. */
const SectionHead = ({ title, action }) => (
  <div className="flex items-center justify-between gap-3 px-1 min-h-11">
    <h2 className="text-[13px] font-semibold text-[var(--text-muted)]">{title}</h2>
    {action}
  </div>
);

const EditLink = ({ onClick, label, children }) => (
  <button type="button" onClick={onClick} aria-label={label}
    className={`inline-flex items-center min-h-11 px-1 text-[14px] font-semibold text-[var(--accent)] rounded-[8px] ${FOCUS}`}>
    {children}
  </button>
);

/**
 * A section that reads as sentences until Edit, then shows its fields with one Save.
 * `read(profile)` returns the sentences; `edit(draft, set)` the fields.
 */
const Section = ({ title, fields, profile, onSaved, read, edit, emptyText }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => draftFrom(fields, profile));
  const [state, setState] = useState(null);
  const dirty = fields.some((f) => normal(f, draft[f]) !== normal(f, profile[f]));
  const filled = told(profile, fields);
  const open = () => { setDraft(draftFrom(fields, profile)); setState(null); setEditing(true); };
  const save = () => {
    setState({ busy: true });
    const body = Object.fromEntries(fields.map((f) => [f, draft[f] ?? empty(f)]));
    api.put(endpoints.profile.get, body)
      .then((res) => { onSaved(res.data); setState(null); setEditing(false); })
      .catch((err) => {
        const detail = err?.response?.data?.detail;
        setState({ error: Array.isArray(detail) ? 'Some fields are too long or invalid.' : detail || 'Could not save. Your edits are still here.' });
      });
  };
  const set = (key) => (value) => { setDraft((d) => ({ ...d, [key]: value })); setState(null); };
  return (
    <section aria-label={title}>
      <SectionHead title={title}
        action={!editing && <EditLink onClick={open} label={`${filled ? 'Edit' : 'Add'} ${title.toLowerCase()}`}>{filled ? 'Edit' : 'Add'}</EditLink>} />
      {editing ? (
        <div className={`${CARD} fade-in`}>
          <div>{edit(draft, set)}</div>
          <div className="flex flex-wrap items-center justify-end gap-3 py-3 border-t border-[var(--border)]">
            {state?.error && <span role="alert" className="flex-1 min-w-[10rem] text-[13px] text-[var(--loss)]">{state.error}</span>}
            <Button variant="secondary" onClick={() => setEditing(false)} disabled={state?.busy}>Cancel</Button>
            <Button onClick={save} disabled={!dirty || state?.busy}>{state?.busy ? 'Saving' : 'Save'}</Button>
          </div>
        </div>
      ) : (
        <div className={CARD}>
          {filled ? read(profile) : (
            <button type="button" onClick={open}
              className={`tap w-full text-left py-4 text-[15px] leading-6 text-[var(--text-muted)] ${FOCUS}`}>
              {emptyText}
            </button>
          )}
        </div>
      )}
    </section>
  );
};

const article = (word) => (/^[aeiou]/i.test(word) ? 'an' : 'a');

const tradeLines = (p) => {
  const exp = EXPERIENCE.find(([v]) => v === p.experience)?.[1].toLowerCase();
  const risk = RISK.find(([v]) => v === p.risk_appetite)?.[1].toLowerCase();
  const styles = (p.styles || []).map((s) => STYLE_LABEL[s] || s);
  return (
    <>
      {exp && risk && <Line>You're {article(exp)} <Chip>{exp}</Chip> trader with <Chip>{risk}</Chip> risk appetite.</Line>}
      {exp && !risk && <Line>You're {article(exp)} <Chip>{exp}</Chip> trader.</Line>}
      {!exp && risk && <Line>Your risk appetite is <Chip>{risk}</Chip>.</Line>}
      {styles.length > 0 && <Line>You trade {chips(styles)}</Line>}
      {p.horizon && <Line>You invest over <Chip>{p.horizon}</Chip></Line>}
      {p.goals && <Prose label="Goals" text={p.goals} />}
    </>
  );
};

const preferenceLines = (p) => (
  <>
    {p.favour?.length > 0 && <Line>You favour {chips(p.favour)}</Line>}
    {p.avoid?.length > 0 && <Line>Never suggest {chips(p.avoid)}</Line>}
    {p.constraints && <Prose label="Constraints" text={p.constraints} />}
  </>
);

const answerLines = (p) => (
  <>
    {p.about_me && <Prose label="About you" text={p.about_me} />}
    {p.answer_style && <Prose label="How to answer" text={p.answer_style} />}
  </>
);

/** Google identity and the name NeoTrade uses, which is the one thing here you can change. */
const Identity = ({ account, profile, onSaved, onSignOut }) => {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [state, setState] = useState(null);
  const shown = profile.display_name || account.name;
  const dirty = name.trim() !== (profile.display_name || '');
  const save = () => {
    setState({ busy: true });
    api.put(endpoints.profile.get, { display_name: name })
      .then((res) => { onSaved(res.data); setState(null); setEditing(false); })
      .catch((err) => setState({ error: err?.response?.data?.detail || 'Could not save the name.' }));
  };
  return (
    <section aria-label="Account" className={`${CARD} py-4`}>
      <div className="flex items-center gap-4">
        <Avatar src={account.picture} name={shown} size={64} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <p className="text-[22px] leading-7 font-bold tracking-[-0.02em] text-[var(--text)] truncate">{shown}</p>
            {account.role === 'admin' && <Badge>Admin</Badge>}
          </div>
          <p className={`${META} truncate`}>{account.email}</p>
          {account.created_at && <p className={META}>Member since {formatNoteDate(new Date(account.created_at))}</p>}
        </div>
      </div>
      {editing ? (
        <div className="mt-4 pt-1 border-t border-[var(--border)] fade-in">
          <TextInput id="display_name" label="What NeoTrade calls you" value={name}
            onChange={(v) => { setName(v); setState(null); }} placeholder={account.name} />
          <div className="flex flex-wrap items-center justify-end gap-3 pt-1">
            {state?.error && <span role="alert" className="flex-1 min-w-[10rem] text-[13px] text-[var(--loss)]">{state.error}</span>}
            <Button variant="secondary" onClick={() => setEditing(false)} disabled={state?.busy}>Cancel</Button>
            <Button onClick={save} disabled={!dirty || state?.busy}>{state?.busy ? 'Saving' : 'Save'}</Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 mt-4 pt-3 border-t border-[var(--border)]">
          <p className="flex-1 min-w-0 text-[15px] leading-7 text-[var(--text-muted)]">
            NeoTrade calls you <Chip>{shown}</Chip>
          </p>
          <EditLink onClick={() => { setName(profile.display_name || ''); setState(null); setEditing(true); }} label="Edit the name NeoTrade calls you">Edit</EditLink>
        </div>
      )}
      <div className="flex items-center gap-3 mt-1 pt-3 border-t border-[var(--border)]">
        <p className={`flex-1 min-w-0 ${META}`}>Name and photo come from your Google account.</p>
        <Button variant="secondary" onClick={onSignOut}>Sign out</Button>
      </div>
    </section>
  );
};

const MemorySection = ({ memories, onChange }) => {
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
    <section aria-label="Memory">
      <SectionHead title="Memory" action={<span className={`${META} tabular-nums`}>{memories.length} of 50</span>} />
      <div className={CARD}>
        {memories.length === 0 ? (
          <p className="py-4 text-[15px] leading-6 text-[var(--text-muted)]">
            Nothing remembered yet. Tell the assistant a goal or a preference in chat, or add one below.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {memories.map((m) => (
              <li key={m.id} className="flex items-start gap-2 py-2.5">
                <div className="flex-1 min-w-0 pt-0.5">
                  <p className="text-[15px] leading-6 text-[var(--text)]">{m.text}</p>
                  <p className={META}>{m.source === 'chat' ? 'From chat' : 'Added by you'} · {formatDateTime(m.created_at)}</p>
                </div>
                <button type="button" onClick={() => remove(m.id)} aria-label={`Forget: ${m.text}`}
                  className={`-mr-2 min-h-11 min-w-11 inline-flex items-center justify-center rounded-[12px] text-[var(--text-muted)] hover:text-[var(--loss)] ${FOCUS}`}>
                  <Trash2 className="w-4 h-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center gap-2 py-3 border-t border-[var(--border)]">
          <input id="new-memory" value={text} maxLength={200} placeholder="e.g. Saving for a house in 2028" aria-label="New memory"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') add(); }} className={inputClass} />
          <Button variant="secondary" onClick={add} disabled={!text.trim() || memories.length >= 50}>Add</Button>
        </div>
        {error && <p role="alert" className="text-[13px] text-[var(--loss)] pb-3">{error}</p>}
      </div>
      <p className={`${META} px-1 pt-2`}>NeoTrade asks before it remembers anything you say in chat.</p>
    </section>
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
        <div className="max-w-2xl">
          <PageHeader title="Profile" back="/settings" />
          <div className={`${CARD} py-4`}>
            {error ? <ErrorLine message={error} onRetry={() => { setError(null); setTick((t) => t + 1); }} /> : <Skeleton rows={4} />}
          </div>
        </div>
      </Layout>
    );
  }

  const { account, profile } = data;
  return (
    <Layout>
      <div className="max-w-2xl">
        <PageHeader title="Profile" back="/settings" />
        <div className="space-y-5 fade-in">
          <Identity account={account} profile={profile} onSaved={saved} onSignOut={logout} />
          <p className={`${META} px-1`}>Used in every chat, on the web and on Telegram. Nothing here changes your orders or limits.</p>

          <Section title="How you trade" profile={profile} onSaved={saved}
            fields={['experience', 'risk_appetite', 'styles', 'horizon', 'goals']}
            emptyText="Tell the assistant your experience, risk appetite and how you trade, so it frames ideas for you."
            read={tradeLines}
            edit={(draft, set) => (
              <>
                <Row label="Experience">
                  <Segmented label="Experience" options={EXPERIENCE} value={draft.experience}
                    onChange={(v) => set('experience')(v === draft.experience ? '' : v)} />
                </Row>
                <Row label="Risk appetite" hint={RISK_HELP}>
                  <Segmented label="Risk appetite" options={RISK} value={draft.risk_appetite}
                    onChange={(v) => set('risk_appetite')(v === draft.risk_appetite ? '' : v)} />
                </Row>
                <Row label="How you trade" hint="Pick any">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-1 rounded-[12px] bg-[var(--surface-2)] p-1">
                    {STYLES.map(([id, label]) => {
                      const on = (draft.styles || []).includes(id);
                      return (
                        <button key={id} type="button" aria-pressed={on}
                          onClick={() => set('styles')(on ? draft.styles.filter((s) => s !== id) : [...(draft.styles || []), id])}
                          className={cn('min-h-11 px-4 rounded-[8px] text-[14px] font-medium transition-colors', FOCUS,
                            on ? 'bg-[var(--surface)] text-[var(--text)]' : 'text-[var(--text-muted)]')}>
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
            )} />

          <Section title="Likes and limits" profile={profile} onSaved={saved}
            fields={['favour', 'avoid', 'constraints']}
            emptyText="Name sectors or stocks you like, ones the assistant must never suggest, and rules like no F&O."
            read={preferenceLines}
            edit={(draft, set) => (
              <>
                <ChipInput id="favour" label="Favour" hint="Sectors or stocks you like. Press Enter to add."
                  value={draft.favour || []} onChange={set('favour')} placeholder="e.g. IT, HDFCBANK" />
                <ChipInput id="avoid" label="Avoid" hint="The assistant will not suggest these to you."
                  value={draft.avoid || []} onChange={set('avoid')} placeholder="e.g. Tobacco, PSU banks" />
                <TextArea id="constraints" label="Constraints" rows={3} value={draft.constraints} onChange={set('constraints')}
                  placeholder="e.g. No F&O; new tax regime; monthly SIP of ₹20,000" />
              </>
            )} />

          <Section title="How to answer you" profile={profile} onSaved={saved}
            fields={['about_me', 'answer_style']}
            emptyText="Tell the assistant about yourself and how you like answers: short, detailed, Hinglish."
            read={answerLines}
            edit={(draft, set) => (
              <>
                <TextArea id="about_me" label="About me" value={draft.about_me} onChange={set('about_me')}
                  hint="What should NeoTrade know about you?"
                  placeholder="e.g. Salaried engineer in Bengaluru, trade before work, new to swing trading" />
                <TextArea id="answer_style" label="How should NeoTrade answer?" value={draft.answer_style} onChange={set('answer_style')}
                  placeholder="e.g. Short bullet points, explain jargon, Hinglish is fine" />
              </>
            )} />

          <MemorySection memories={profile.memories || []} onChange={(memories) => saved({ ...profile, memories })} />
        </div>
      </div>
    </Layout>
  );
};

export default Profile;
