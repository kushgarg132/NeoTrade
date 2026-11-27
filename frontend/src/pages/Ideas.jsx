import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Hero from '../components/ui/Hero';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Term from '../components/ui/Term';
import { pct } from '../components/ui/format';
import HoldingActions from '../components/ideas/HoldingActions';
import HandledActions from '../components/ideas/HandledActions';
import PickList from '../components/ideas/PickList';
import { useLoad } from '../components/ideas/useLoad';
import { useAuth } from '../context/AuthContext';
import api, { endpoints } from '../utils/api';
import { fetchIdeas } from '../hooks/useNeedCount';
import useSymbolNews, { useSymbolResults } from '../hooks/useSymbolNews';
import { actNowCount, noPickText } from '../utils/ideas';

const FORWARD_NEEDED = 100; // scored forward picks before the record counts as measured (backend MIN_FORWARD)

/** A lane: one card with its heading, count and note on top, its list inside (the list draws no card of its own). */
const Lane = ({ id, title, count, note, children }) => (
  <section id={id} aria-labelledby={`${id}-h`} className="ui-card scroll-mt-20 rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4 pt-4">
    <div className="flex items-baseline justify-between gap-3">
      <h2 id={`${id}-h`} className="text-[17px] font-bold tracking-[-0.01em] text-[var(--text)]">
        {title}{count > 0 && <span className="ml-2 text-[15px] font-medium tabular-nums text-[var(--text-muted)]">{count}</span>}
      </h2>
      {note}
    </div>
    <div className="mt-1">{children}</div>
  </section>
);

/**
 * Ideas: one page, two lanes. The Hero says how far Picks can be trusted so far (the forward record: share that beat
 * NIFTY, how many of the 100 needed are scored). Then "Decide on your holdings" and "New picks". Admin only.
 */
const Ideas = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const acts = useLoad(useCallback(() => api.get(endpoints.mine.actions).then((r) => r.data), []));
  const fresh = useLoad(useCallback(() => fetchIdeas(isAdmin), [isAdmin]));
  const [showUnproven, setShowUnproven] = useState(false);
  // One news and one results request for every idea on the page, never per row.
  const symbols = (fresh.data?.items || []).map((i) => i.symbol);
  const { news } = useSymbolNews(symbols);
  const results = useSymbolResults(symbols);
  // Act-now rows only, the same count as the nav badge (news, results and dividends are FYI).
  const nHold = acts.data ? actNowCount(acts.data) : 0;
  const nPicks = fresh.data?.items.length || 0;
  const rec = fresh.data?.record;
  const scored = rec?.n || 0;

  return (
    <Layout>
      <PageHeader title="Ideas" />
      <div className="space-y-4">
        <Hero
          label="Picks that beat NIFTY"
          value={scored ? rec.beat_nifty_rate : null}
          format={(v) => (v == null ? '–' : pct(v, { dp: 0 }))}
          privateValue={false}
          action={<Link to="/ideas/history" className="-my-3 -mr-2 inline-flex items-center gap-0.5 min-h-11 px-2 text-[14px] font-semibold text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[10px]">History<ChevronRight className="w-4 h-4" aria-hidden="true" /></Link>}
          change={(
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[14px] tabular-nums text-[var(--text-muted)]">
              {scored
                ? <><span><b className="font-semibold text-[var(--text)]">{Math.min(scored, FORWARD_NEEDED)} of {FORWARD_NEEDED}</b> scored</span><span aria-hidden="true">·</span><span>{pct(rec.win_rate, { dp: 0 })} ended up</span></>
                : <span>No pick scored yet: the record starts when the first one reaches its due date.</span>}
              {rec?.status === 'unproven' && <Badge kind="unproven">Unproven</Badge>}
            </p>
          )}
        >
          <p className="mt-4 pt-3 border-t border-[var(--border)] flex items-center gap-2 text-[13px] text-[var(--text-muted)]">
            <Badge kind="paper">Paper</Badge>
            <span>Paper record · not advice</span>
          </p>
        </Hero>

        <Lane id="holdings" title="Decide on your holdings" count={nHold}>
          {acts.loading ? <div className="pb-4"><Skeleton rows={3} /></div>
            : acts.error ? <div className="pb-4"><ErrorLine message="Could not load your holdings alerts." onRetry={acts.reload} /></div>
            : <HoldingActions actions={acts.data} onChanged={() => { acts.reload(); fresh.reload(); }} />}
        </Lane>

        <Lane id="picks" title="New picks" count={nPicks}
          note={<span className="text-[13px] text-[var(--text-muted)]"><Term id="grade">A proven · B promising</Term></span>}>
          {fresh.loading ? <div className="pb-4"><Skeleton rows={4} /></div>
            : fresh.error ? <div className="pb-4"><ErrorLine message="Could not load ideas." onRetry={fresh.reload} /></div>
            : fresh.data.items.length === 0 ? (
              <div className="pb-2">
                <Empty title={noPickText(fresh.data.hiddenReason).title} body={noPickText(fresh.data.hiddenReason).body}
                  action={<Link to="/ideas/history"><Button variant="secondary">Open history</Button></Link>} />
              </div>
            ) : (
              <PickList items={fresh.data.items} news={news} results={results} showUnproven={showUnproven}
                onToggleUnproven={() => setShowUnproven((v) => !v)} hiddenCount={fresh.data.hiddenCount} hiddenReason={fresh.data.hiddenReason} />
            )}
        </Lane>

        {/* Remounts (reloads) whenever the holdings list changes, e.g. after a dismiss. */}
        {acts.data && <div className="px-1"><HandledActions key={acts.data.map((a) => a.id).join()} onChanged={acts.reload} /></div>}
      </div>
    </Layout>
  );
};

export default Ideas;
