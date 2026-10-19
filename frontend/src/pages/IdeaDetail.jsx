import React, { useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Stat from '../components/ui/Stat';
import Button from '../components/ui/Button';
import IdeaBadge from '../components/ideas/IdeaBadge';
import RangeBar from '../components/ideas/RangeBar';
import BuyBar from '../components/ideas/BuyBar';
import { useLoad } from '../components/ideas/useLoad';
import api, { endpoints } from '../utils/api';
import { ideaFromSuggestion, ideaFromPick, parseIdeaId } from '../utils/ideas';
import { bareSymbol } from '../utils/formatters';
import { inr, pct } from '../components/ui/format';

const find = async (kind, key) => {
  if (kind === 's') {
    const s = (await api.get(endpoints.suggestions.list({ status: 'PENDING' }))).data.find((x) => x.id === key);
    return s ? ideaFromSuggestion(s) : null;
  }
  const today = (await api.get(endpoints.picks.today)).data;
  const pick = today.picks.find((p) => p._id === key)
    || (await api.get(endpoints.picks.history(90))).data.picks.find((p) => p._id === key);
  return pick ? ideaFromPick(pick, today.setups.find((s) => s.setup === pick.setup)) : null;
};

// Price levels keep their paise (inr rounds to rupees).
const px = (n) => (n == null ? '—' : `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);

const IdeaDetail = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const ref = parseIdeaId(id);
  const kind = ref?.kind;
  const key = ref?.key;
  const { data: idea, loading, error, reload } = useLoad(useCallback(() => (kind ? find(kind, key) : Promise.resolve(null)), [kind, key]));
  const done = () => navigate('/ideas', { replace: true });

  let body;
  if (loading) body = <Skeleton rows={6} />;
  else if (error) body = <ErrorLine message="Could not load this idea." onRetry={reload} />;
  else if (!idea) body = <Empty title="Idea not found" body="It may have been decided or has expired." action={<Button variant="secondary" onClick={done}>Back to Ideas</Button>} />;
  else body = (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[13px] font-semibold text-[var(--text-muted)]">{idea.side}</span>
        <span className="text-[13px] text-[var(--text-muted)]">{idea.setup}{idea.horizon ? ` · ${idea.horizon}d` : ''}</span>
        <IdeaBadge badge={idea.badge} />
        {idea.noEdge && <span className="text-[12px] font-semibold text-[var(--warn)]">No edge</span>}
      </div>

      <Card title="Why">
        {idea.why && <p className="text-[15px] text-[var(--text)]">{idea.why}</p>}
        {idea.reasons.length > 0 && <ul className="list-disc pl-5 text-[15px] text-[var(--text)]">{idea.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        {idea.thesis && <p className="mt-2 text-[14px] text-[var(--text-muted)]">{idea.thesis}</p>}
        {!idea.why && !idea.reasons.length && !idea.thesis && <p className="text-[14px] text-[var(--text-muted)]">No reasons recorded.</p>}
      </Card>

      <Card title="Levels">
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Entry" value={px(idea.entry)} />
          {idea.stop != null && <Stat label="Stop" value={px(idea.stop)} />}
          {idea.target != null && <Stat label="Target" value={px(idea.target)} />}
        </div>
        {idea.qty != null && (
          <div className="mt-4 grid grid-cols-3 gap-3">
            <Stat label="Quantity" value={idea.qty} />
            <Stat label="Size" value={inr(idea.notional)} />
            <Stat label="Risk" value={inr(idea.risk)} />
          </div>
        )}
      </Card>

      {idea.range && (
        <Card title="Likely range">
          <RangeBar range={idea.range} />
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Stat label="Chance up" value={pct(idea.pUp, { dp: 0 })} />
            <Stat label="Beat NIFTY" value={pct(idea.pBeat, { dp: 0 })} />
          </div>
        </Card>
      )}

      {idea.pastN != null && (
        <Card title="Track record">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Past events" value={idea.pastN} />
            <Stat label="Out-of-sample vs NIFTY" value={pct(idea.oosExcess, { sign: true })} delta={idea.oosN != null ? `n ${idea.oosN}` : null} />
            <div className="min-w-0"><div className="text-[13px] text-[var(--text-muted)]">Forward</div><div className="mt-1"><IdeaBadge badge={idea.badge} /></div></div>
          </div>
        </Card>
      )}

      {idea.kind === 's' && !idea.decided && <BuyBar idea={idea} id={key} onDone={done} />}
    </div>
  );

  return (
    <Layout>
      <PageHeader title={idea ? bareSymbol(idea.symbol) : 'Idea'} back="/ideas" />
      {body}
    </Layout>
  );
};

export default IdeaDetail;
