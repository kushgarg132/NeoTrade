import React, { useEffect, useState } from 'react';
import { Sheet } from '../doc/Doc';
import { Badge } from '../common/Badge';
import NewStrategySheet from './NewStrategySheet';
import api, { endpoints } from '../../utils/api';
import { builtLine } from '../../utils/library';

const CHIPS = { testing: ['Testing', 'secondary'], active: ['Active', 'success'], rejected: ['Rejected', 'destructive'], retired: ['Retired', 'secondary'] };
const ORDER = ['testing', 'active', 'rejected', 'retired'];

/** Practice › Strategies → Mine: the user's own strategies, the New strategy form, Retire and Re-test. */
const MyStrategies = ({ built, refresh }) => {
  const [open, setOpen] = useState(false);
  const [vocab, setVocab] = useState(null);
  const [vocabFailed, setVocabFailed] = useState(false);
  const [errors, setErrors] = useState({}); // slug -> 409/429 detail
  const rows = built ? ORDER.flatMap((s) => (built[s] || []).filter((r) => r.mine).map((r) => ({ ...r, status: s }))) : [];
  const testing = rows.some((r) => r.status === 'testing');

  // A backtest takes a while; look again every 10 s until none is left.
  useEffect(() => {
    if (!testing) return undefined;
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [testing, refresh]);

  const openForm = () => {
    setOpen((o) => !o);
    if (!vocab) api.get(endpoints.strategyVocabulary).then((res) => setVocab(res.data)).catch(() => setVocabFailed(true));
  };
  const act = (slug, action) =>
    api.post(`${endpoints.builtStrategies}/${slug}/${action}`)
      .then(() => { setErrors((e) => ({ ...e, [slug]: null })); refresh(); })
      .catch((err) => setErrors((e) => ({ ...e, [slug]: err?.response?.data?.detail || 'Could not do that.' })));

  return (
    <Sheet title="Mine" meta={rows.length ? `${rows.length}` : undefined}
           actions={<button type="button" onClick={openForm} aria-expanded={open}
                            className="field-label text-[var(--stamp)] hover:underline min-h-9 inline-flex items-center">
                      {open ? 'Close' : 'New strategy'}
                    </button>}>
      {open && (vocab
        ? <NewStrategySheet vocab={vocab} onSubmitted={() => { setOpen(false); refresh(); }} />
        : <p className="text-sm py-2">{vocabFailed ? 'Couldn’t load the building blocks.' : '…'}</p>)}
      {rows.length === 0 && !open && (
        <p className="text-sm text-[var(--ink-soft)]">Build your own from the same blocks the AI uses. It must pass the same checks before it trades.</p>
      )}
      <ul className="divide-y divide-[var(--rule)]">
        {rows.map((r) => (
          <li key={r.slug} className="py-2.5">
            <span className="flex flex-wrap items-baseline gap-2">
              <Badge variant={CHIPS[r.status][1]}>{CHIPS[r.status][0]}</Badge>
              <Badge variant="neutral">{r.horizon === 'swing' ? 'Swing' : 'Intraday'}</Badge>
              {r.name && <span className="text-sm font-medium">{r.name}</span>}
              <span className="text-sm min-w-0">{[r.description, r.thesis].filter(Boolean).join(' — ')}</span>
            </span>
            {r.verdict && <span className="block doc-meta normal-case">{r.verdict}</span>}
            <span className="block doc-meta normal-case">{builtLine(r.metrics, r.horizon)}</span>
            {(r.status === 'active' || r.status === 'rejected') && (
              <button type="button" onClick={() => act(r.slug, r.status === 'active' ? 'retire' : 'retest')}
                      className="text-xs underline min-h-11 sm:min-h-8">
                {r.status === 'active' ? 'Retire' : 'Re-test'}
              </button>
            )}
            {errors[r.slug] && <p className="text-sm text-[var(--loss)]" role="alert">{errors[r.slug]}</p>}
          </li>
        ))}
      </ul>
    </Sheet>
  );
};

export default MyStrategies;
