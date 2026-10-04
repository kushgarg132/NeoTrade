import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Sheet, Field, Money, NetLine, Statement, Row, Cell, Empty, Ruling } from '../doc/Doc';
import MonthGrid from '../journal/MonthGrid';
import api, { endpoints } from '../../utils/api';
import { useTopic } from '../../hooks/useStream';
import { monthKey, shiftMonth, monthLabel, todayIst } from '../../utils/months';
import { formatPercent, formatSignedPercent, formatCurrency, formatNoteDate } from '../../utils/formatters';

/**
 * The paper track record: every closed paper trade, net of brokerage and
 * taxes, day by day and per strategy. This is what a strategy is judged on
 * before it is trusted with real money -- so it shows the losing figures
 * (drawdown, worst day) as plainly as the winning ones, and sets the result
 * against simply holding NIFTY 50 over the same days.
 */

const ratio = (value) => (value === null || value === undefined ? '—' : value.toFixed(2));

const Scorecard = ({ mode }) => {
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);
  const [month, setMonth] = useState(null);

  const load = () =>
    api
      .get(endpoints.analytics.scorecard('paper', mode))
      .then((res) => {
        setCard(res.data);
        setError(null);
      })
      .catch((err) => setError(err?.response?.data?.detail || 'The scorecard did not load'));

  useEffect(() => {
    setCard(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);
  useTopic('trades', load);

  const byDay = useMemo(
    () => Object.fromEntries((card?.days || []).map((d) => [d.day, { pnl: d.pnl, trips: d.trades }])),
    [card]
  );

  if (error) {
    return (
      <Sheet title="Track record">
        <Empty title="Could not load the track record" detail={error} />
      </Sheet>
    );
  }
  if (!card) {
    return (
      <Sheet title="Track record">
        <Ruling rows={5} />
      </Sheet>
    );
  }

  const { totals, strategies } = card;
  if (totals.trades === 0) {
    return (
      <Sheet title="Track record" meta="Net of charges">
        <Empty
          title="No closed paper trades yet"
          detail="Turn on the daily auto-run and the engine paper-trades every session by itself. Each closed trade lands here, net of charges."
          action={
            <Link to="/ai/practice/settings" className="field-label text-[var(--stamp)] hover:underline">
              Turn on auto-run
            </Link>
          }
        />
      </Sheet>
    );
  }

  const shown = month || monthKey(totals.last_day || todayIst());
  const monthRows = card.days.filter((d) => monthKey(d.day) === shown);
  const monthNet = monthRows.reduce((sum, d) => sum + d.pnl, 0);
  const beat =
    card.nifty_return_pct === null || totals.return_pct === null
      ? null
      : totals.return_pct - card.nifty_return_pct;

  return (
    <div className="space-y-4">
      <Sheet title="Track record" meta="Net of charges">
        <p className="doc-meta normal-case mb-3">
          Every closed paper trade since {formatNoteDate(new Date(totals.first_day))}
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Field label="Trading days" value={`${totals.trading_days} (${totals.winning_days} up)`} />
          <Field label="Trades · win rate" value={`${totals.trades} · ${formatPercent(totals.win_rate * 100)}`} />
          <Field label="Profit factor" value={ratio(totals.profit_factor)} tone={totals.profit_factor >= 1 ? 'up' : 'down'} />
          <Field
            label="Worst drawdown"
            value={`${formatCurrency(totals.max_drawdown)} (${formatPercent(totals.max_drawdown_pct)})`}
            tone={totals.max_drawdown > 0 ? 'down' : undefined}
          />
          <Field label="Best day" value={<Money value={totals.best_day.pnl} />} />
          <Field label="Worst day" value={<Money value={totals.worst_day.pnl} />} />
          <Field label="Charges paid" value={formatCurrency(totals.costs)} />
          <Field
            label="Versus holding NIFTY"
            value={
              beat === null
                ? '—'
                : `${formatSignedPercent(totals.return_pct)} vs ${formatSignedPercent(card.nifty_return_pct)}`
            }
            tone={beat === null ? undefined : beat >= 0 ? 'up' : 'down'}
          />
        </div>
        <NetLine label={`Net result · ${formatSignedPercent(totals.return_pct)} of the paper account`}>
          <Money value={totals.net} size="lg" />
        </NetLine>
      </Sheet>

      <Sheet title="Day by day">
        <div className="flex items-center justify-between mb-2">
          <button
            type="button"
            className="p-2 min-h-9 text-[var(--ink-soft)] hover:text-[var(--ink)]"
            onClick={() => setMonth(shiftMonth(shown, -1))}
            aria-label="Previous month"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="field-label text-[var(--ink)]">{monthLabel(shown)}</span>
          <button
            type="button"
            className="p-2 min-h-9 text-[var(--ink-soft)] hover:text-[var(--ink)]"
            onClick={() => setMonth(shiftMonth(shown, 1))}
            aria-label="Next month"
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <MonthGrid month={shown} byDay={byDay} selected={null} onSelect={() => {}} />
        <NetLine label={`${monthLabel(shown)} · ${monthRows.length} trading days`}>
          <Money value={monthNet} />
        </NetLine>
      </Sheet>

      <Sheet title="By strategy" meta={`${strategies.length}`}>
        <Statement
          columns={[
            { key: 'strategy', label: 'Strategy' },
            { key: 'trades', label: 'Trades', align: 'right' },
            { key: 'win', label: 'Win rate', align: 'right' },
            { key: 'pf', label: 'Profit factor', align: 'right' },
            { key: 'dd', label: 'Drawdown', align: 'right' },
            { key: 'net', label: 'Net', align: 'right' },
          ]}
        >
          {strategies.map((s) => (
            <Row key={s.strategy}>
              <Cell>
                <span className="figure-md">{s.strategy === 'unattributed' ? 'Untagged' : s.strategy.replace(/_/g, ' ')}</span>
              </Cell>
              <Cell align="right" mono>{s.trades}</Cell>
              <Cell align="right" mono>{formatPercent(s.win_rate * 100)}</Cell>
              <Cell align="right" mono>{ratio(s.profit_factor)}</Cell>
              <Cell align="right" mono>{formatCurrency(s.max_drawdown)}</Cell>
              <Cell align="right"><Money value={s.net} /></Cell>
            </Row>
          ))}
        </Statement>
        <p className="mt-3 doc-meta normal-case">
          Untagged: approved proposals and trades from before strategies were recorded. Paper fills at
          the bar's close with no slippage, so real results would run somewhat worse.
        </p>
      </Sheet>
    </div>
  );
};

export default Scorecard;
