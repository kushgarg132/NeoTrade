import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import useStored from '../../hooks/useStored';
import { endpoints } from '../../utils/api';
import { indexPath } from '../../utils/routes';

const SHOWN = 3; // a blue chip is in many indices: three, then "+N" for the rest

/** The indices this stock is in, on its hero, each opening that index's page; the first three, then "+N". A small
 *  pill in a 44px tap area stays under the price. Absent when it is in none we list. */
const StockIndices = ({ symbol }) => {
  const { data } = useStored(endpoints.stockIndices(symbol));
  const [all, setAll] = useState(false);
  if (!data?.indices?.length) return null;
  const list = all ? data.indices : data.indices.slice(0, SHOWN);
  const rest = data.indices.length - SHOWN;
  return (
    <div role="group" aria-label="Indices this stock is in" className="-mb-2 mt-1 flex flex-wrap gap-x-1.5">
      {list.map((i) => (
        <Link key={i.symbol} to={indexPath(i.symbol)} aria-label={`${i.name}: open its page`} className="tap inline-flex min-h-11 items-center">
          <span className="whitespace-nowrap rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[12px] font-medium text-[var(--text-muted)]">{i.name}</span>
        </Link>
      ))}
      {!all && rest > 0 && (
        <button type="button" onClick={() => setAll(true)} aria-label={`Show ${rest} more indices`} className="tap inline-flex min-h-11 items-center">
          <span className="rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[12px] font-semibold text-[var(--text)]">+{rest}</span>
        </button>
      )}
    </div>
  );
};

export default StockIndices;
