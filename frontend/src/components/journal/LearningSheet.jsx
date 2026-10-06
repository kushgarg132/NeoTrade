import React, { useEffect, useState } from 'react';
import { Sheet, Statement, Row, Cell, Money, Empty } from '../doc/Doc';
import api, { endpoints } from '../../utils/api';
import { formatPercent, formatSigned, formatDateTime } from '../../utils/formatters';

/**
 * What the paper engine learned from its own closed paper trades
 * (backend/learning): the rules it follows now, what it changed and why,
 * every setup's record net of charges, and each strategy's monthly re-tune.
 * Statistics made every change shown here; nothing is a recommendation.
 */

const name = (strategy) => (strategy || '').replace(/_/g, ' ');

const REGIME = { up: 'Nifty above its 200-day average', down: 'Nifty below its 200-day average' };
const WHEN = { up: 'the Nifty is above its 200-day average', down: 'the Nifty is below its 200-day average' };
const when = (regimes) => regimes.map((r) => WHEN[r] || r).join(' or ');

const setup = (row) =>
  row.by === 'all'
    ? 'all trades'
    : row.by === 'regime'
      ? REGIME[row.group] || row.group
      : row.by === 'strength'
        ? `strength ${row.group}`
        : name(row.group);

const IDEA_STATUS = {
  queued: 'waiting for this month\'s test',
  accepted: 'won on unseen data, now running',
  rejected: 'did not hold up on unseen data',
};

const params = (p) =>
  p
    ? Object.entries(p)
        .map(([k, v]) => `${name(k)} ${v}`)
        .join(' · ')
    : 'defaults';

const changeText = (c) => {
  switch (c.rule) {
    case 'pause':
      return 'Paused: it lost money over its paper trades';
    case 'resume':
      return 'Resumed after a newer backtest passed the gate; judged afresh from here';
    case 'floor':
      return `Needs strength ${c.after.toFixed(2)} or more to trade (was ${c.before.toFixed(2)})`;
    case 'regime':
      return `Stops trading when ${when(c.after)}`;
    default:
      return `${c.rule}: ${JSON.stringify(c.before)} → ${JSON.stringify(c.after)}`;
  }
};

const evidence = (e) =>
  e && e.trades !== undefined
    ? `${setup(e)}: ${e.trades} trades, win rate ${formatPercent(e.win_rate * 100)}, net ${formatSigned(e.net)}` +
      (e.profit_factor != null ? `, profit factor ${e.profit_factor.toFixed(2)}` : '')
    : null;

const Rules = ({ rules }) => {
  const lines = [
    ...rules.paused.map((s) => `${name(s)} is paused`),
    ...Object.entries(rules.floors).map(([s, f]) => `${name(s)} needs strength ${f.toFixed(2)} or more`),
    ...Object.entries(rules.skip_regimes).map(
      ([s, r]) => `${name(s)} sits out when ${when(r)}`
    ),
  ];
  return (
    <div className="mb-4">
      <p className="field-label mb-1">Rules it follows now</p>
      {lines.length === 0 ? (
        <p className="doc-meta normal-case">None yet: every strategy runs as written.</p>
      ) : (
        <ul>
          {lines.map((line) => (
            <li key={line} className="text-sm text-[var(--ink)] py-0.5">
              {line}
            </li>
          ))}
        </ul>
      )}
      <p className="doc-meta normal-case mt-1">
        Today: {REGIME[rules.regime_today] || 'market trend not known yet'}.
      </p>
    </div>
  );
};

const LearningSheet = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get(endpoints.journal.learning)
      .then((res) => setData(res.data))
      .catch((err) => setError(err.response?.data?.detail || err.message));
  }, []);

  if (error) {
    return (
      <Sheet title="What the engine learned">
        <Empty title="Could not load what the engine learned" detail={String(error)} />
      </Sheet>
    );
  }
  if (!data) return <Sheet title="What the engine learned" meta="Loading" />;
  return <LearningView data={data} />;
};

const LearningView = ({ data }) => {
  const nothing = data.groups.length === 0 && data.changes.length === 0;

  return (
    <>
      <Sheet title="What the engine learned" meta="Your paper trades, net of charges">
        {nothing ? (
          <Empty
            title="No closed paper trades yet"
            detail="After each day's close the engine judges its own closed paper trades. A setup shows here once it has 10 trades; a strategy is paused only after it loses over 30."
          />
        ) : (
          <>
            <Rules rules={data.rules} />
            <p className="field-label mb-1">Changes in the last 30 days</p>
            {data.changes.length === 0 ? (
              <p className="doc-meta normal-case">None: no setup has lost money over enough trades to act on.</p>
            ) : (
              <ul>
                {data.changes.map((c) => (
                  <li key={`${c.at}:${c.strategy}:${c.rule}`} className="py-2 border-b border-[var(--rule)] last:border-b-0">
                    <p className="text-sm text-[var(--ink)]">
                      <span className="capitalize">{name(c.strategy)}</span> · {changeText(c)}
                    </p>
                    <p className="doc-meta normal-case mt-1">
                      {formatDateTime(c.at)}
                      {evidence(c.evidence) && ` · ${evidence(c.evidence)}`}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Sheet>

      {data.groups.length > 0 && (
        <Sheet title="Setups, worst first" meta="Per trade is pulled toward zero for small groups">
          <Statement
            columns={[
              { key: 'setup', label: 'Strategy · setup' },
              { key: 'n', label: 'Trades', align: 'right' },
              { key: 'win', label: 'Win', align: 'right' },
              { key: 'net', label: 'Net', align: 'right' },
              { key: 'per', label: 'Per trade', align: 'right' },
            ]}
          >
            {data.groups.map((g) => (
              <Row key={`${g.strategy}:${g.by}:${g.group}`}>
                <Cell>
                  <span className="capitalize">{name(g.strategy)}</span>
                  <span className="doc-meta normal-case block">{setup(g)}</span>
                </Cell>
                <Cell align="right" mono>
                  {g.trades}
                </Cell>
                <Cell align="right" mono>
                  {formatPercent(g.win_rate * 100)}
                </Cell>
                <Cell align="right">
                  <Money value={g.net} />
                </Cell>
                <Cell align="right" mono>
                  {formatSigned(g.shrunk)}
                </Cell>
              </Row>
            ))}
          </Statement>
        </Sheet>
      )}

      <Sheet title="Monthly re-tune" meta="Daily strategies, last 3 years">
        {data.hypotheses?.length > 0 && (
          <div className="mb-4">
            <p className="field-label mb-1">AI ideas, tested before use</p>
            <ul>
              {data.hypotheses.map((h) => (
                <li key={h.id} className="py-2 border-b border-[var(--rule)] last:border-b-0">
                  <p className="text-sm text-[var(--ink)]">
                    <span className="capitalize">{name(h.strategy)}</span> · {params(h.params)} ·{' '}
                    {IDEA_STATUS[h.status] || h.status}
                  </p>
                  <p className="doc-meta normal-case mt-1">
                    {h.rationale}
                    {h.reason && ` · ${h.reason}`}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}
        {data.retunes.length === 0 ? (
          <Empty
            title="Not re-tuned yet"
            detail="Once a month each daily strategy's thresholds are tested on two years and checked on the year after. They change only if the new ones win on that unseen year."
          />
        ) : (
          <ul>
            {data.retunes.map((r) => (
              <li key={r.strategy} className="py-2 border-b border-[var(--rule)] last:border-b-0">
                <p className="text-sm text-[var(--ink)]">
                  <span className="capitalize">{name(r.strategy)}</span> ·{' '}
                  {r.accepted ? `changed to ${params(r.params)}` : 'kept its thresholds'}
                </p>
                <p className="doc-meta normal-case mt-1">
                  {formatDateTime(r.at)} · {r.reason} · running {params(r.running)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Sheet>
    </>
  );
};

export default LearningSheet;
