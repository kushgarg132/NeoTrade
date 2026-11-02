import React from 'react';
import { Link } from 'react-router-dom';
import useStored from '../../hooks/useStored';
import { endpoints } from '../../utils/api';
import { indexPath } from '../../utils/routes';

/** The indices this stock is in, on its hero, each opening that index's page. They wrap so all show at once; a small
 *  pill in a 44px tap area stays under the price. Absent when it is in none we list. */
const StockIndices = ({ symbol }) => {
  const { data } = useStored(endpoints.stockIndices(symbol));
  if (!data?.indices?.length) return null;
  return (
    <div role="group" aria-label="Indices this stock is in" className="-mb-2 mt-1 flex flex-wrap gap-x-1.5">
      {data.indices.map((i) => (
        <Link key={i.symbol} to={indexPath(i.symbol)} aria-label={`${i.name}: open its page`} className="tap inline-flex min-h-11 items-center">
          <span className="whitespace-nowrap rounded-full bg-[var(--surface-2)] px-2.5 py-1 text-[12px] font-medium text-[var(--text-muted)]">{i.name}</span>
        </Link>
      ))}
    </div>
  );
};

export default StockIndices;
