import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { LAB_TABS } from '../components/layout/sections';
import { Sheet, Statement, Row, Cell, Empty, Ruling } from '../components/doc/Doc';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { pct } from '../utils/forward';

/** Lab › Forward (admin-only, /lab/forward): every decision the system recorded, scored later; click a row for its records. */

const COLUMNS = [
  { key: 'source', label: 'Source' }, { key: 'name', label: 'Name' },
  { key: 'n', label: 'n/100', align: 'right' }, { key: 'excess', label: 'Mean excess', align: 'right' },
  { key: 't', label: 't', align: 'right' }, { key: 'hit', label: 'Hit rate', align: 'right' },
  { key: 'gap', label: 'Calibration gap', align: 'right' }, { key: 'label', label: 'Label' },
  { key: 'gate', label: 'Gate' }, { key: 'dis', label: '' },
];
const RECORD_COLUMNS = [
  { key: 'd', label: 'Date' }, { key: 's', label: 'Symbol' }, { key: 'side', label: 'Side' },
  { key: 'net', label: 'Net', align: 'right' }, { key: 'nifty', label: 'NIFTY', align: 'right' },
];

const gateText = (g) => (g === null || g === undefined ? '—' : g ? 'Passes' : 'Fails');

const LabForward = () => {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [records, setRecords] = useState(null);

  useEffect(() => {
    api.get(endpoints.forward.scorecard)
      .then((res) => setRows(res.data.rows))
      .catch((err) => setError(err.response?.data?.detail || 'Could not load the forward record.'));
  }, []);

  const pick = (row) => {
    setRecords(null);
    const key = `${row.source}:${row.name}`;  // by value: a refetched row is a new object
    if (open === key) return setOpen(null);
    setOpen(key);
    api.get(endpoints.forward.records, { params: { source: row.source, name: row.name } })
      .then((res) => setRecords(res.data.records))
      .catch(() => setRecords([]));
  };

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-4xl">
        <SectionTabs tabs={LAB_TABS} label="Lab" />
        <Sheet title="Forward" meta="Net of charges, excess over NIFTY · proven needs 100 scored, t ≥ 2, calibrated">
          {error && <p role="alert" className="text-sm text-[var(--loss)]">{error}</p>}
          {!error && rows === null && <Ruling rows={4} />}
          {rows && rows.length === 0 && <Empty title="Nothing scored yet" detail="Decisions are recorded as they happen and scored after their horizon, in the 16:00 IST pass." />}
          {rows && rows.length > 0 && (
            <Statement columns={COLUMNS}>
              {rows.map((r) => (
                <Row key={`${r.source}:${r.name}`}>
                  <Cell>{r.source}</Cell>
                  <Cell>
                    <button type="button" onClick={() => pick(r)} aria-expanded={open === `${r.source}:${r.name}`}
                            className="min-h-11 sm:min-h-0 text-left underline decoration-dotted underline-offset-2">{r.name}</button>
                  </Cell>
                  <Cell align="right" mono>{r.progress}/100{r.n > r.progress ? ` (${r.n})` : ''}</Cell>
                  <Cell align="right" mono>{pct(r.mean_excess)}</Cell>
                  <Cell align="right" mono>{r.t == null ? '—' : r.t.toFixed(2)}</Cell>
                  <Cell align="right" mono>{pct(r.hit_rate, 1)}</Cell>
                  <Cell align="right" mono>{pct(r.calibration_gap, 1)}</Cell>
                  <Cell><Badge variant={r.label === 'proven' ? 'success' : 'neutral'}>{r.label}</Badge></Cell>
                  <Cell>{gateText(r.gate)}</Cell>
                  <Cell>{r.disagrees && <Badge variant="warning">Disagrees</Badge>}</Cell>
                </Row>
              ))}
            </Statement>
          )}
        </Sheet>
        {open && (
          <Sheet title={`${open.source} · ${open.name}`} meta="Latest records">
            {records === null ? <Ruling rows={3} /> : records.length === 0 ? <Empty title="No records" /> : (
              <Statement columns={RECORD_COLUMNS}>
                {records.map((x) => (
                  <Row key={x.id}>
                    <Cell mono>{String(x.decided_at).slice(0, 10)}</Cell>
                    <Cell>{x.symbol}</Cell>
                    <Cell>{x.side}</Cell>
                    <Cell align="right" mono>{x.outcome ? (x.outcome.void ? 'void' : pct(x.outcome.net)) : 'pending'}</Cell>
                    <Cell align="right" mono>{x.outcome && !x.outcome.void ? pct(x.outcome.nifty) : '—'}</Cell>
                  </Row>
                ))}
              </Statement>
            )}
          </Sheet>
        )}
      </div>
    </Layout>
  );
};

export default LabForward;
