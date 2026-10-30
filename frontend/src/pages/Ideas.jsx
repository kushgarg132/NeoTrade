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
    <>
      <h3 className="mt-3 mb-1 text-[13px] font-semibold text-[var(--text-muted)]">{title}</h3>
      {rows.map(row)}
    </>
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
            <div className="mt-4"><HandledActions key={acts.data.map((a) => a.id).join()} onChanged={acts.reload} /></div>
          </>)}

        {tab === 'picks' && <Card title="New ideas" action={<Badge kind="paper">Paper</Badge>}>
          <p className="-mt-1 mb-2 text-[13px] text-[var(--text-muted)]">Trades the engine would take: entry, stop (SL), target (T) and reward : risk (R:R). Paper record · not advice.</p>
          {fresh.loading ? <Skeleton rows={4} />
            : fresh.error ? <ErrorLine message="Could not load ideas." onRetry={fresh.reload} />
            : fresh.data.items.length === 0 ? (
              <Empty title={noPickText(fresh.data.hiddenReason).title} body={noPickText(fresh.data.hiddenReason).body}
                action={<Link to="/ideas/history"><Button variant="secondary">Open history</Button></Link>} />
            ) : (
              <>
                {engine.length === 0 && A.length === 0 && B.length === 0 && C.length > 0 && <p className="py-3 text-[14px] text-[var(--text-muted)]">No proven setup has fired right now. The ones below have no edge over the average stock so far.</p>}
                {group('Engine ideas', engine)}
                {group(GRADES.A.label, A)}
                {group(GRADES.B.label, B)}
                {C.length > 0 && (
                  <>
                    <button type="button" aria-expanded={showUnproven} onClick={() => setShowUnproven((v) => !v)}
                      className="mt-2 min-h-11 w-full text-left text-[14px] font-semibold text-[var(--text-muted)]">
                      {showUnproven ? 'Hide' : 'Show'} {C.length} unproven idea{C.length > 1 ? 's' : ''} (grade C: no edge yet)
                    </button>
                    {showUnproven && <div className="opacity-80">{C.map(row)}</div>}
                  </>
                )}
              </>
            )}
        </Card>}
      </div>
    </Layout>
  );
};

export default Ideas;
