import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
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
import { GRADES, groupByGrade, noPickText } from '../utils/ideas';

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
  const row = (i) => <IdeaRow key={i.id} idea={i} onDone={fresh.reload} news={news} results={results} />;

  const group = (title, rows) => rows.length > 0 && (
    <section className="space-y-3">
      <h3 className="pt-2 text-[13px] font-semibold text-[var(--text-muted)]">{title}</h3>
      {rows.map(row)}
    </section>
  );

  return (
    <Layout>
      <PageHeader title="Ideas" right={<Link to="/ideas/history" className="inline-flex items-center min-h-11 px-2 text-[14px] font-semibold text-[var(--accent)]">History</Link>} />
      <div className="space-y-4">
        <Tabs label="Ideas sections" value={tab} onChange={setTab} tabs={[
          { id: 'picks', label: 'Picks', badge: fresh.data?.items.length || 0 },
          { id: 'holdings', label: 'Holdings', badge: acts.data?.length || 0 },
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
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-[var(--text)]">New ideas</h2>
              <p className="text-[13px] text-[var(--text-muted)]">
                {fresh.data?.items?.length ? `${fresh.data.items.length} shown` : 'Trades the engine would take'}
                {fresh.data?.hiddenCount > 0 && <> · <span title={fresh.data.hiddenReason}>{fresh.data.hiddenCount} more kept back (top 3 per grade)</span></>}
                {' · '}Paper record · not advice.
              </p>
            </div>
            <span className="shrink-0"><Badge kind="paper">Paper</Badge></span>
          </div>
          {fresh.loading ? <Card><Skeleton rows={4} /></Card>
            : fresh.error ? <Card><ErrorLine message="Could not load ideas." onRetry={fresh.reload} /></Card>
            : fresh.data.items.length === 0 ? (
              <Card><Empty title={noPickText(fresh.data.hiddenReason).title} body={noPickText(fresh.data.hiddenReason).body}
                action={<Link to="/ideas/history"><Button variant="secondary">Open history</Button></Link>} /></Card>
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
              </>
            )}
        </div>}
      </div>
    </Layout>
  );
};

export default Ideas;
