import React, { useCallback, useEffect, useRef, useState } from 'react';
import Card from '../ui/Card';
import Button from '../ui/Button';
import Skeleton from '../ui/Skeleton';
import api, { endpoints } from '../../utils/api';
import { formatDateTime } from '../../utils/formatters';

/**
 * Import holdings, journal and tax from files, no broker needed: a Zerodha Console tradebook CSV and a
 * CAMS/KFintech CAS PDF. The PDF and its password are read once and never stored.
 */
const ImportFiles = ({ onImported }) => {
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
      .then((res) => { setMessage(describe(res.data)); onImported?.(); })
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
    <Card title="Import files">
      {!status ? <Skeleton rows={3} /> : (
        <div className="space-y-5 text-[14px] text-[var(--text-muted)]">
          <section>
            <h3 className="text-[15px] font-semibold text-[var(--text)]">Stock trades</h3>
            <p className="mt-1">
              Zerodha Console, Reports, Tradebook, download the CSV. Fills the Journal and Tax.
              {status.trades ? ` ${status.trades} imported so far.` : ''}
            </p>
            <Button variant="secondary" className="mt-2" disabled={busy} onClick={() => csvInput.current?.click()}>Choose tradebook CSV</Button>
            <input ref={csvInput} type="file" accept=".csv,text/csv" className="hidden" onChange={importCsv} />
          </section>

          <section>
            <h3 className="text-[15px] font-semibold text-[var(--text)]">Mutual funds</h3>
            <p className="mt-1">
              A CAMS or KFintech consolidated statement (CAS) PDF, from camsonline.com or kfintech.com.
              {status.funds ? ` ${status.funds} fund${status.funds === 1 ? '' : 's'} imported${status.period ? `, statement to ${status.period.to}` : ''}; a new file replaces them.` : ''}
            </p>
            <label htmlFor="cas-password" className="block mt-3 text-[13px]">PDF password</label>
            <input
              id="cas-password" type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full min-h-11 rounded-[12px] border border-[var(--border)] bg-[var(--surface)] px-3 text-[15px] text-[var(--text)]"
            />
            <Button variant="secondary" className="mt-2" disabled={busy || !password} onClick={() => pdfInput.current?.click()}>Choose CAS PDF</Button>
            <input ref={pdfInput} type="file" accept="application/pdf,.pdf" className="hidden" onChange={importPdf} />
          </section>

          {message && <p role="status" className="text-[14px] text-[var(--text)]">{message}</p>}
          <p className="text-[13px]">
            Your file is read once to pull out the holdings and trades, and is not kept. The PDF password is never stored or logged.
            What is read is kept for you only, and you can delete it any time.
          </p>
          {has && <Button variant="danger" disabled={busy} onClick={erase}>Delete my imported data</Button>}
          {status.imported_at && <p className="text-[13px]">Last fund import {formatDateTime(status.imported_at)}</p>}
        </div>
      )}
    </Card>
  );
};

export default ImportFiles;
