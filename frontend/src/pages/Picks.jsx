import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { RESEARCH_TABS } from '../components/layout/sections';
import { Sheet, Statement, Row, Cell, Empty, Ruling, Scrip, Field, Money } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { formatPercent, formatSignedPercent } from '../utils/formatters';

/**
 * Picks (admin-only, /research/picks): today's setups with the base rates
 * measured over their own past events (backend/forecast/), the walk-forward
 * calibration per setup, and the forward record of stored picks.
 */

const pct = (x) => (x === null || x === undefined ? '—' : formatPercent(x * 100));
const signed = (x) => (x === null || x === undefined ? '—' : formatSignedPercent(x * 100));

const Badge = ({ children }) => (
  <span className="field-label px-1.5 border border-dashed border-[var(--stamp)] text-[var(--stamp)]">{children}</span>
);

const PickCard = ({ pick, unproven }) => (
  <article className="border-b border-[var(--rule)] last:border-b-0 py-3 space-y-2">
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <Scrip symbol={pick.symbol} />
      <span className="field-label">{pick.label} · {pick.horizon}d</span>
      {!pick.edge && <Badge>No edge</Badge>}
      {unproven && <Badge>Unproven</Badge>}
    </div>
    <p className="text-sm text-[var(--ink-soft)]">{pick.explanation}</p>
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
      <div>
        <div className="field-label mb-1">Expected (median)</div>
        <Money value={pick.expected.median * 100} percent />
        <div className="doc-meta normal-case mt-0.5">{signed(pick.expected.p10)} to {signed(pick.expected.p90)}</div>
      </div>
      <Field label="P(up)" value={pct(pick.p_up)} />
      <Field label="P(beat NIFTY)" value={pct(pick.p_beat_nifty)} />
      <Field label="Past events" value={pick.n} />
      <Field label="Entry ref" value={`₹${pick.entry_ref.toFixed(2)}`} />
    </div>
  </article>
);

const SETUP_COLUMNS = [
  { key: 'setup', label: 'Setup' },
  { key: 'n', label: 'n', align: 'right' },
  { key: 'median', label: 'Median net', align: 'right' },
  { key: 'range', label: '10th–90th', align: 'right' },
  { key: 'up', label: 'P(up)', align: 'right' },
  { key: 'beat', label: 'P(beat NIFTY)', align: 'right' },
  { key: 'oos', label: 'Out-of-sample vs NIFTY', align: 'right' },
  { key: 'brier', label: 'Brier', align: 'right' },
];

const YEAR_COLUMNS = [
  { key: 'year', label: 'Year' },
  { key: 'n', label: 'Events', align: 'right' },
  { key: 'pred', label: 'Predicted P(up)', align: 'right' },
  { key: 'real', label: 'Realised', align: 'right' },
  { key: 'excess', label: 'vs NIFTY', align: 'right' },
];

const Picks = () => {
  const [data, setData] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.get(endpoints.picks.today), api.get(endpoints.picks.history(90))])
      .then(([today, past]) => {
        setData(today.data);
        setHistory(past.data.picks.filter((p) => p.outcome));
      })
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load picks'));
  }, []);

  const unproven = data?.forward?.status === 'unproven';

  return (
    <Layout>
      <div className="space-y-4">
        <SectionTabs tabs={RESEARCH_TABS} label="Research" />
        {error ? (
          <Empty title="Could not load picks" detail={error} />
        ) : !data ? (
          <Ruling rows={5} />
        ) : (
          <>
            <Sheet title="Picks" meta={data.date ? `Signals at the ${data.date} close` : 'No run yet'}>
              {data.picks.length === 0 ? (
                <Empty title="No picks" detail="No setup with enough history fired at the last close. The list fills after the 16:00 IST daily pass." />
              ) : (
                data.picks.map((p) => <PickCard key={p._id} pick={p} unproven={unproven} />)
              )}
              <ul className="mt-3 space-y-1 text-xs text-[var(--ink-soft)] list-disc pl-4">
                {data.caveats.map((c) => <li key={c}>{c}</li>)}
              </ul>
            </Sheet>

            <Sheet title="Setups" meta="Net of delivery charges · all past events">
              <Statement columns={SETUP_COLUMNS}>
                {data.setups.map((s) => (
                  <Row key={s.setup}>
                    <Cell>{s.label} · {s.horizon}d {!s.walk_forward.edge && <Badge>No edge</Badge>}</Cell>
                    <Cell align="right" mono>{s.n}</Cell>
                    <Cell align="right" mono>{signed(s.median)}</Cell>
                    <Cell align="right" mono>{signed(s.p10)} / {signed(s.p90)}</Cell>
                    <Cell align="right" mono>{pct(s.p_up)}</Cell>
                    <Cell align="right" mono>{pct(s.p_beat_nifty)}</Cell>
                    <Cell align="right" mono>{signed(s.walk_forward.oos_excess)} (n {s.walk_forward.oos_n})</Cell>
                    <Cell align="right" mono>{s.walk_forward.brier?.toFixed(3) ?? '—'}</Cell>
                  </Row>
                ))}
              </Statement>
            </Sheet>

            {data.setups.map((s) => (
              <Sheet key={s.setup} title={`Walk-forward · ${s.label}`} meta="Each year predicted only from events that matured before it">
                {s.walk_forward.years.length === 0 ? (
                  <Empty title="Not enough history" detail="A year is tested once 30 earlier events have matured." />
                ) : (
                  <Statement columns={YEAR_COLUMNS}>
                    {s.walk_forward.years.map((y) => (
                      <Row key={y.year}>
                        <Cell mono>{y.year}</Cell>
                        <Cell align="right" mono>{y.n}</Cell>
                        <Cell align="right" mono>{pct(y.predicted_p_up)}</Cell>
                        <Cell align="right" mono>{pct(y.realised_p_up)}</Cell>
                        <Cell align="right" mono>{signed(y.mean_excess)}</Cell>
                      </Row>
                    ))}
                  </Statement>
                )}
              </Sheet>
            ))}

            <Sheet title="Forward record" meta={unproven ? `Unproven · ${data.forward.n} of 100 scored` : `${data.forward.n} scored`}>
              {data.forward.n === 0 ? (
                <Empty title="Nothing scored yet" detail="A pick is scored once its horizon has passed." />
              ) : (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Won" value={pct(data.forward.win_rate)} />
                    <Field label="Beat NIFTY" value={pct(data.forward.beat_nifty_rate)} />
                  </div>
                  <Statement columns={[
                    { key: 'b', label: 'Predicted P(up)' }, { key: 'n', label: 'Picks', align: 'right' },
                    { key: 'p', label: 'Mean predicted', align: 'right' }, { key: 'r', label: 'Realised', align: 'right' },
                  ]}>
                    {data.forward.buckets.map((b) => (
                      <Row key={b.bucket}>
                        <Cell mono>{b.bucket}</Cell>
                        <Cell align="right" mono>{b.n}</Cell>
                        <Cell align="right" mono>{pct(b.predicted)}</Cell>
                        <Cell align="right" mono>{pct(b.realised)}</Cell>
                      </Row>
                    ))}
                  </Statement>
                  <Statement columns={[
                    { key: 'd', label: 'Date' }, { key: 's', label: 'Pick' },
                    { key: 'net', label: 'Net', align: 'right' }, { key: 'nifty', label: 'NIFTY', align: 'right' },
                  ]}>
                    {history.map((p) => (
                      <Row key={p._id}>
                        <Cell mono>{p.date}</Cell>
                        <Cell>{p.symbol} · {p.label}</Cell>
                        <Cell align="right"><Money value={p.outcome.net * 100} percent /></Cell>
                        <Cell align="right" mono>{signed(p.outcome.nifty)}</Cell>
                      </Row>
                    ))}
                  </Statement>
                </div>
              )}
            </Sheet>
          </>
        )}
      </div>
    </Layout>
  );
};

export default Picks;
