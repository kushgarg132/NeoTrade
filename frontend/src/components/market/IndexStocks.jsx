import React, { useState } from 'react';
import Card from '../ui/Card';
import Empty from '../ui/Empty';
import ErrorLine from '../ui/ErrorLine';
import ListRow from '../ui/ListRow';
import Skeleton from '../ui/Skeleton';
import AsOf from '../ui/AsOf';
import useStored from '../../hooks/useStored';
import { endpoints } from '../../utils/api';
import { pct, tone } from '../ui/format';
import { toneText } from '../ui/tone';
import { stockPath } from '../../utils/stocks';
import { SORTS, sortStocks, upDown } from '../../utils/indexStocks';

const SHOWN = 50;
const num = (v) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 });

/** The stocks in this index with their day move, biggest gain first; each opens its stock page. */
const IndexStocks = ({ ticker }) => {
  const { data, status, retry } = useStored(endpoints.marketIndexStocks(ticker));
  const [sort, setSort] = useState('gain');
  const [all, setAll] = useState(false);
  if (status === 'loading') return <Card><Skeleton rows={6} /></Card>;
  if (status === 'error') return <Card><ErrorLine message="Could not load the stocks." onRetry={retry} /></Card>;
  const rows = sortStocks(data?.stocks, sort);
  if (!rows.length) return <Card><Empty title="No stock list" body="We don't have the stocks in this index." /></Card>;
  const { up, down } = upDown(rows);
  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[14px] font-semibold tabular-nums">
          <span className="text-[var(--gain)]">{up} up</span><span className="text-[var(--text-muted)]"> · {rows.length} stocks · </span><span className="text-[var(--loss)]">{down} down</span>
        </p>
        <select aria-label="Sort stocks" value={sort} onChange={(e) => setSort(e.target.value)}
                className="min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 text-[14px] text-[var(--text)]">
          {SORTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      {(all ? rows : rows.slice(0, SHOWN)).map((s) => (
        <ListRow privateValue={false} key={s.symbol} dense to={stockPath(s.symbol)} title={s.symbol} sub={s.name}
          right={s.price == null ? 'No quote' : <><span className="text-[var(--text)]">{num(s.price)}</span>{'  '}<span className={toneText(tone(s.change_pct))}>{pct(s.change_pct / 100, { sign: true })}</span></>} />
      ))}
      {!all && rows.length > SHOWN && (
        <button type="button" onClick={() => setAll(true)} className="mt-1 min-h-11 text-[14px] font-semibold text-[var(--accent)]">Show all {rows.length}</button>
      )}
      <AsOf rows={rows.filter((s) => s.at)} />
    </Card>
  );
};

export default IndexStocks;
