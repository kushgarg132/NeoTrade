import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Hero from '../components/ui/Hero';
import Tabs, { useTabParam } from '../components/ui/Tabs';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import HoldingActions from '../components/ideas/HoldingActions';
import HandledActions from '../components/ideas/HandledActions';
import IdeaRow from '../components/ideas/IdeaRow';
import { useLoad } from '../components/ideas/useLoad';
import { useAuth } from '../context/AuthContext';
import api, { endpoints } from '../utils/api';
import { fetchIdeas } from '../hooks/useNeedCount';
import useSymbolNews, { useSymbolResults } from '../hooks/useSymbolNews';
import { GRADES, actNowCount, groupByGrade, noPickText } from '../utils/ideas';

/** Ideas: what needs you on your holdings first, then new ideas (your suggestions, plus Picks for admins). */
const IDS = ['picks', 'holdings'];

const Ideas = () => {
  const [tab, setTab] = useTabParam(IDS);
  const isAdmin = useAuth().user?.role === 'admin';
  const acts = useLoad(useCallback(() => api.get(endpoints.mine.actions).then((r) => r.data), []));
  const fresh = useLoad(useCallback(() => fetchIdeas(isAdmin), [isAdmin]));
  const [showUnproven, setShowUnproven] = useState(false);
  const { engine, A, B, C } = groupByGrade(fresh.data?.items || []);
  // One news and one results request for every idea on the page, never per row.
  const symbols = (fresh.data?.items || []).map((i) => i.symbol);
  const { news } = useSymbolNews(symbols);
  const results = useSymbolResults(symbols);
  const nPicks = fresh.data?.items.length;
  // Act-now rows only, the same count as the nav badge (news, results and dividends are FYI).
  const nHold = acts.data ? actNowCount(acts.data) : null;
  const waiting = nPicks == null && nHold == null ? null : (nPicks || 0) + (nHold || 0);
  const pill = (text) => (
    <span className="inline-flex items-center min-h-8 px-3 rounded-full bg-[var(--surface-2)] text-[13px] font-semibold text-[var(--text)]">{text}</span>
  );
  const row = (i) => <IdeaRow key={i.id} idea={i} onDone={fresh.reload} news={news} results={results} />;

  const group = (title, rows) => rows.length > 0 && (
    <section className="space-y-3">
      <h3 className="pt-2 text-[13px] font-semibold text-[var(--text-muted)]">{title}</h3>
      {rows.map(row)}
    </section>
  );

  return (
    <Layout>
      <PageHeader title="Ideas" />
      <div className="space-y-4">
        <Hero
          label="Waiting for you"
          value={waiting}
          format={(n) => (n == null ? '–' : String(Math.round(n)))}
          privateValue={false}
          action={<Link to="/ideas/history" className="-my-3 -mr-2 inline-flex items-center min-h-11 px-2 text-[14px] font-semibold text-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded-[10px]">History ›</Link>}
          change={waiting != null && (
            <div className="flex flex-wrap gap-2">
              {nHold != null && pill(`${nHold} on holdings`)}
              {nPicks != null && pill(`${nPicks} new idea${nPicks === 1 ? '' : 's'}`)}
            </div>
          )}
        >
          <p className="mt-4 pt-3 border-t border-[var(--border)] flex items-center gap-2 text-[13px] text-[var(--text-muted)]">
            <Badge kind="paper">Paper</Badge>
            <span>Paper record · not advice</span>
          </p>
        </Hero>
        <Tabs label="Ideas sections" value={tab} onChange={setTab} tabs={[
          { id: 'picks', label: 'Picks', badge: fresh.data?.items.length || 0 },
          { id: 'holdings', label: 'Holdings', badge: nHold || 0 },
        ]} />

        {tab === 'holdings' && (acts.loading ? <Skeleton rows={2} />
          : acts.error ? <ErrorLine message="Could not load your holdings alerts." onRetry={acts.reload} />
          : <>
            <HoldingActions actions={acts.data} onChanged={() => { acts.reload(); fresh.reload(); }} />
            {/* Remounts (reloads) whenever the holdings list changes, e.g. after a dismiss. */}
            <div className="mt-6"><HandledActions key={acts.data.map((a) => a.id).join()} onChanged={acts.reload} /></div>
          </>)}

        {/* Each idea is its own card, so the list sits on the page, not inside a Card (no nested cards). */}
        {tab === 'picks' && <div className="space-y-3">
          {fresh.loading ? <Card><Skeleton rows={4} /></Card>
            : fresh.error ? <Card><ErrorLine message="Could not load ideas." onRetry={fresh.reload} /></Card>
            : fresh.data.items.length === 0 ? (
              <Empty title={noPickText(fresh.data.hiddenReason).title} body={noPickText(fresh.data.hiddenReason).body}
                action={<Link to="/ideas/history"><Button variant="secondary">Open history</Button></Link>} />
            ) : (
              <>
                {engine.length === 0 && A.length === 0 && B.length === 0 && C.length > 0 && <p className="text-[14px] text-[var(--text-muted)]">No proven setup has fired right now. The ones below have no edge over the average stock so far.</p>}
                {group('Engine ideas', engine)}
                {group(GRADES.A.label, A)}
                {group(GRADES.B.label, B)}
                {C.length > 0 && (
                  <>
                    <button type="button" aria-expanded={showUnproven} onClick={() => setShowUnproven((v) => !v)}
                      className="mt-2 min-h-11 w-full text-left text-[14px] font-semibold text-[var(--text-muted)]">
                      {showUnproven ? 'Hide' : 'Show'} {C.length} unproven idea{C.length > 1 ? 's' : ''} (grade C: no edge yet)
                    </button>
                    {showUnproven && <div className="space-y-3 opacity-80">{C.map(row)}</div>}
                  </>
                )}
                {fresh.data.hiddenCount > 0 && (
                  <p className="px-1 text-[13px] text-[var(--text-muted)]" title={fresh.data.hiddenReason}>
                    {fresh.data.hiddenCount} more kept back (top 3 per grade).
                  </p>
                )}
              </>
            )}
        </div>}
      </div>
    </Layout>
  );
};

export default Ideas;
