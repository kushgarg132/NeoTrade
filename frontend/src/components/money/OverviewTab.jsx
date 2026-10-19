import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import Card from '../ui/Card';
import Stat from '../ui/Stat';
import ListRow from '../ui/ListRow';
import Empty from '../ui/Empty';
import Skeleton from '../ui/Skeleton';
import { inr, pct, tone } from '../ui/format';
import ValueChart from './ValueChart';
import useHoldings from './useHoldings';
import useSymbolNews from '../../hooks/useSymbolNews';
import { topMovers, whyLine } from '../../utils/money';
import { stockPath } from '../../utils/stocks';

/** Invested, total P&L and today's three biggest movers with a one-line why. `headline` comes from /mine/overview. */
const OverviewTab = ({ headline }) => {
  const { snapshot, loading } = useHoldings();
  const movers = useMemo(() => topMovers((snapshot?.holdings || []).filter((h) => h.kind !== 'MF'), 3), [snapshot]);
  const { news } = useSymbolNews(movers.map((m) => m.symbol));
  const invested = headline ? headline.value - headline.pnl : null;

  return (
    <div className="space-y-4">
      <ValueChart />

      {headline && (
        <Card>
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Put in" value={inr(invested)} />
            <Stat
              label="Total P&L"
              value={inr(headline.pnl, { sign: true })}
              delta={pct(headline.pnl_pct / 100, { sign: true })}
              tone={tone(headline.pnl)}
            />
          </div>
        </Card>
      )}

      <Card title="Biggest movers today" action={<Link to="/money?tab=holdings" className="inline-flex items-center min-h-11 text-[14px] font-semibold text-[var(--accent)]">All holdings<ChevronRight className="w-4 h-4" aria-hidden="true" /></Link>}>
        {loading ? (
          <Skeleton rows={3} />
        ) : movers.length === 0 ? (
          <Empty title="No moves to show" body="Movers appear once your holdings have a price today." />
        ) : (
          movers.map((m) => (
            <ListRow
              key={m.symbol}
              to={stockPath(m.symbol)}
              title={m.symbol}
              sub={whyLine({ ...m, news: news?.[m.symbol] })}
              right={`${inr(m.day_rupees, { sign: true })} · ${pct(m.day_pct, { sign: true })}`}
              rightTone={tone(m.day_rupees)}
            />
          ))
        )}
      </Card>
    </div>
  );
};

export default OverviewTab;
