import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2, ArrowRight } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import { Sheet, Statement, Row, Cell, Empty, Ruling, Scrip } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { formatCurrency, formatSignedPercent } from '../utils/formatters';
import { cn } from '../utils/cn';

const Watchlist = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .get(endpoints.watchlist.details)
      .then((res) => setRows(res.data))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the watchlist'))
      .finally(() => setLoading(false));
  }, []);

  const remove = async (event, symbol) => {
    event.stopPropagation();
    const previous = rows;
    setRows((list) => list.filter((item) => item.symbol !== symbol));
    try {
      await api.delete(endpoints.watchlist.remove(symbol));
    } catch {
      setRows(previous);
    }
  };

  return (
    <Layout>
      <div className="space-y-4">
      <SectionTabs tabs={RESEARCH_TABS} label="Research" />
      <Sheet title="Watchlist" meta={`${rows.length} scrip`}>
        {loading ? (
          <Ruling rows={4} />
        ) : error ? (
          <Empty title="Could not load the watchlist" detail={error} />
        ) : rows.length === 0 ? (
          <Empty
            title="Nothing watched"
            detail="Enquire on a scrip from the statement and add it from there."
          />
        ) : (
          <Statement
            columns={[
              { key: 'scrip', label: 'Scrip' },
              { key: 'last', label: 'Last', align: 'right' },
              { key: 'change', label: 'Change', align: 'right' },
              { key: 'actions', label: '', align: 'right' },
            ]}
          >
            {rows.map((stock) => (
              <Row
                key={stock.symbol}
                className="group cursor-pointer hover:bg-[var(--paper-sunk)]"
                onClick={() => navigate('/research', { state: { symbol: stock.symbol } })}
              >
                <Cell>
                  <Scrip symbol={stock.symbol} />
                  <span className="block doc-meta normal-case truncate max-w-[16rem]">
                    {stock.error ? 'Quote unavailable' : stock.name}
                  </span>
                </Cell>
                <Cell align="right" mono>
                  {formatCurrency(stock.current_price)}
                </Cell>
                <Cell align="right">
                  <span
                    className={cn(
                      'figure-md text-sm',
                      (stock.day_change_percent || 0) >= 0 ? 'text-up' : 'text-down'
                    )}
                  >
                    {formatSignedPercent(stock.day_change_percent)}
                  </span>
                </Cell>
                <Cell align="right">
                  <span className="inline-flex items-center gap-2">
                    <button
                      type="button"
                      onClick={(event) => remove(event, stock.symbol)}
                      className="p-1 text-[var(--ink-faint)] hover:text-[var(--loss)] transition-colors"
                      aria-label={`Remove ${stock.symbol} from the watchlist`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ArrowRight
                      className="w-4 h-4 text-[var(--ink-faint)] group-hover:text-[var(--stamp)] transition-colors"
                      aria-hidden="true"
                    />
                  </span>
                </Cell>
              </Row>
            ))}
          </Statement>
        )}
      </Sheet>
      </div>
    </Layout>
  );
};

export default Watchlist;
