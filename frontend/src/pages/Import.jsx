import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { Sheet, Ruling } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { formatDateTime } from '../utils/formatters';

/**
 * Import: holdings, journal and tax from files, no broker needed. A Zerodha
 * Console tradebook CSV (stock trades) and a CAMS/KFintech CAS PDF (mutual
 * funds). The PDF and its password are read once and never stored.
 */

const BUTTON = 'min-h-11 px-4 border border-[var(--ink)] font-[family-name:var(--font-narrow)] text-xs font-semibold uppercase tracking-[0.11em] disabled:opacity-50';
const INPUT = 'w-full bg-transparent border-b border-[var(--rule-strong)] py-1.5 text-sm focus:outline-none focus:border-[var(--stamp)]';

const Import = () => {
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState('');
  const csvInput = useRef(null);
  const pdfInput = useRef(null);

  const load = useCallback(() => {
    api.get(endpoints.imports.status).then((res) => setStatus(res.data)).catch(() => setStatus({}));
  }, []);
  useEffect(load, [load]);

  const run = (request, describe) => {
    setBusy(true);
    setMessage(null);
    return request()
      .then((res) => setMessage(describe(res.data)))
      .catch((err) => setMessage(err?.response?.data?.detail || 'That did not work. Try again.'))
      .finally(() => { setBusy(false); load(); });
  };

  const importCsv = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    file.text().then((csv) => run(
      () => api.post(endpoints.journal.importConsole, { csv }),
      (r) => `${r.imported} fill${r.imported === 1 ? '' : 's'} imported` +
        (r.duplicates ? `, ${r.duplicates} already there` : '') + (r.skipped ? `, ${r.skipped} unreadable skipped` : '') + '.',
    ));
  };

  const importPdf = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const body = new FormData();
    body.append('file', file);
    body.append('password', password);
    setPassword('');
    run(
      () => api.post(endpoints.imports.cas, body, { headers: { 'Content-Type': 'multipart/form-data' } }),
      (r) => `${r.funds} fund${r.funds === 1 ? '' : 's'} and ${r.transactions} transaction${r.transactions === 1 ? '' : 's'} imported.`,
    );
  };

  const erase = () => {
    if (!window.confirm('Delete everything you imported from files? Fills synced from a broker stay.')) return;
    run(() => api.delete(endpoints.imports.status), (r) => `Deleted ${r.trades} imported fills and ${r.transactions} fund transactions.`);
  };

  const has = status && (status.funds || status.trades);

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <Sheet title="Import your files" meta="No broker needed">
          {!status ? <Ruling rows={3} /> : (
            <div className="space-y-6">
              <section>
                <h2 className="field-label">Stock trades</h2>
                <p className="text-sm text-[var(--ink-soft)] mt-1">
                  Zerodha Console → Reports → Tradebook → download the CSV. Fills the <Link to="/mine/journal" className="underline">Journal</Link> and{' '}
                  <Link to="/mine/tax" className="underline">Tax</Link>.
                  {status.trades ? ` ${status.trades} imported so far.` : ''}
                </p>
                <button type="button" className={`${BUTTON} mt-2`} disabled={busy} onClick={() => csvInput.current?.click()}>Choose tradebook CSV</button>
                <input ref={csvInput} type="file" accept=".csv,text/csv" className="hidden" onChange={importCsv} />
              </section>

              <section>
                <h2 className="field-label">Mutual funds</h2>
                <p className="text-sm text-[var(--ink-soft)] mt-1">
                  A CAMS or KFintech consolidated statement (CAS), PDF, from camsonline.com or kfintech.com. Shows your funds in{' '}
                  <Link to="/mine/holdings" className="underline">Holdings</Link>.
                  {status.funds ? ` ${status.funds} fund${status.funds === 1 ? '' : 's'} imported${status.period ? `, statement to ${status.period.to}` : ''}; a new file replaces them.` : ''}
                </p>
                <label htmlFor="cas-password" className="field-label block mt-3">PDF password</label>
                <input id="cas-password" type="password" autoComplete="off" className={INPUT} value={password} onChange={(e) => setPassword(e.target.value)} />
                <button type="button" className={`${BUTTON} mt-2`} disabled={busy || !password} onClick={() => pdfInput.current?.click()}>Choose CAS PDF</button>
                <input ref={pdfInput} type="file" accept="application/pdf,.pdf" className="hidden" onChange={importPdf} />
              </section>

              {message && <p role="status" className="text-sm">{message}</p>}

              <p className="doc-meta normal-case">
                Your file is read once to pull out the holdings and trades, and is not kept. The PDF password is never stored or logged.
                What is read is kept for you only, and you can delete it any time.
              </p>
              {has && (
                <button type="button" className={BUTTON} disabled={busy} onClick={erase}>Delete my imported data</button>
              )}
              {status.imported_at && <p className="doc-meta normal-case">Last fund import {formatDateTime(status.imported_at)}</p>}
            </div>
          )}
        </Sheet>
      </div>
    </Layout>
  );
};

export default Import;
