import React, { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import Layout from '../components/Layout';
import SystemTabs from '../components/system/SystemTabs';
import { Sheet, Empty, Ruling } from '../components/doc/Doc';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { formatTimeAgo } from '../utils/formatters';

/**
 * The operator's backlog of future enhancements (admin-only, /system/future):
 * one app-wide list in Mongo, edited in place. Writes are optimistic and roll
 * back with the API's message when refused.
 */

const AREAS = ['System', 'Data', 'Trading', 'AI', 'News', 'Journal', 'UI', 'Ops', 'Product'];
const OPEN = [['doing', 'Doing'], ['next', 'Next'], ['idea', 'Ideas']];
const CLOSED = [['done', 'Done'], ['dropped', 'Dropped']];
const STATUSES = ['idea', 'next', 'doing', 'done', 'dropped'];
const FIELD = 'w-full bg-transparent border-b border-[var(--rule-strong)] py-1 text-sm focus:outline-none focus:border-[var(--stamp)]';
const SMALL_BUTTON = 'min-h-11 sm:min-h-8 px-2 border border-[var(--rule-strong)] text-sm disabled:opacity-40';

const Editor = ({ item, onSave }) => {
  const [draft, setDraft] = useState({ why: item.why, notes: item.notes });
  const blur = (key) => () => draft[key] !== item[key] && onSave({ [key]: draft[key] });
  return (
    <div className="mt-2 space-y-2">
      <label className="block">
        <span className="field-label">Why</span>
        <textarea rows={2} maxLength={2000} className={FIELD} value={draft.why}
                  onChange={(e) => setDraft((d) => ({ ...d, why: e.target.value }))} onBlur={blur('why')} />
      </label>
      <label className="block">
        <span className="field-label">Notes</span>
        <textarea rows={3} maxLength={4000} className={FIELD} value={draft.notes}
                  onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))} onBlur={blur('notes')} />
      </label>
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="field-label">Status</span>
          <select className={FIELD} value={item.status} onChange={(e) => onSave({ status: e.target.value })}>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="field-label">Effort</span>
          <select className={FIELD} value={item.effort || ''} onChange={(e) => onSave({ effort: e.target.value || null })}>
            <option value="">—</option>
            {['S', 'M', 'L'].map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="field-label">Area</span>
          <select className={FIELD} value={item.area} onChange={(e) => onSave({ area: e.target.value })}>
            {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
      </div>
      {item.source && <p className="doc-meta normal-case">From {item.source} · updated {formatTimeAgo(item.updated_at)}</p>}
    </div>
  );
};

const Item = ({ item, open, onToggle, onSave, onMove, onDelete, first, last }) => {
  const [arming, setArming] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const remove = () => {
    if (arming) return onDelete();
    setArming(true);
    timer.current = setTimeout(() => setArming(false), 3000);
    return undefined;
  };
  return (
    <li className="py-2.5">
      <div className="flex items-start gap-2">
        <button type="button" onClick={onToggle} aria-expanded={open} className="min-w-0 flex-1 text-left min-h-11 sm:min-h-0">
          <span className="block text-sm font-semibold">{item.title}</span>
          <span className="doc-meta normal-case">
            {[item.area, item.effort && `effort ${item.effort}`, !open && item.why].filter(Boolean).join(' · ')}
          </span>
        </button>
        <div className="flex shrink-0 gap-1">
          <button type="button" aria-label="Move up" className={SMALL_BUTTON} disabled={first} onClick={() => onMove(-1)}>
            <ArrowUp className="w-3.5 h-3.5" />
          </button>
          <button type="button" aria-label="Move down" className={SMALL_BUTTON} disabled={last} onClick={() => onMove(1)}>
            <ArrowDown className="w-3.5 h-3.5" />
          </button>
          <button type="button" onClick={remove}
                  className={cn(SMALL_BUTTON, arming && 'border-[var(--loss)] text-[var(--loss)]')}>
            {arming ? 'Delete?' : '×'}
          </button>
        </div>
      </div>
      {open && <Editor item={item} onSave={onSave} />}
    </li>
  );
};

const Backlog = () => {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [area, setArea] = useState('');
  const [openId, setOpenId] = useState(null);
  const [title, setTitle] = useState('');
  const [newArea, setNewArea] = useState('Product');

  useEffect(() => {
    api.get(endpoints.system.backlog)
      .then((res) => setItems(res.data.items))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the backlog'));
  }, []);

  // Optimistic: apply now, put the old list back if the API refuses.
  const write = (next, request) => {
    const before = items;
    setItems(next);
    setNote(null);
    return request().catch((err) => {
      setItems(before);
      setNote(err?.response?.data?.detail?.[0]?.msg || err?.response?.data?.detail || 'That change was not saved.');
    });
  };

  const save = (item, patch) =>
    write(items.map((i) => (i.id === item.id ? { ...i, ...patch } : i)),
      () => api.patch(endpoints.system.item(item.id), patch)
        .then((res) => setItems((list) => list.map((i) => (i.id === item.id ? res.data : i)))));

  const move = (group, index, step) => {
    const a = group[index];
    const b = group[index + step];
    // An item that changed status keeps its old rank, so two can tie: nudge past the neighbour.
    const rankA = a.rank === b.rank ? b.rank + step / 2 : b.rank;
    const rankB = a.rank;
    const next = items.map((i) => (i.id === a.id ? { ...i, rank: rankA } : i.id === b.id ? { ...i, rank: rankB } : i));
    write(next, () => Promise.all([
      api.patch(endpoints.system.item(a.id), { rank: rankA }),
      api.patch(endpoints.system.item(b.id), { rank: rankB }),
    ]));
  };

  const remove = (item) => write(items.filter((i) => i.id !== item.id), () => api.delete(endpoints.system.item(item.id)));

  const add = (event) => {
    event.preventDefault();
    if (!title.trim()) return;
    setNote(null);
    api.post(endpoints.system.backlog, { title: title.trim(), area: newArea })
      .then((res) => {
        setItems((list) => [...list, res.data]);
        setTitle('');
      })
      .catch((err) => setNote(err?.response?.data?.detail?.[0]?.msg || err?.response?.data?.detail || 'Could not add it.'));
  };

  const group = (status) =>
    (items || []).filter((i) => i.status === status && (!area || i.area === area)).sort((a, b) => a.rank - b.rank);

  const list = (status) => {
    const rows = group(status);
    if (rows.length === 0) return <p className="doc-meta normal-case py-2">Nothing here.</p>;
    return (
      <ul className="divide-y divide-[var(--rule)]">
        {rows.map((item, index) => (
          <Item key={item.id} item={item} open={openId === item.id}
                onToggle={() => setOpenId((id) => (id === item.id ? null : item.id))}
                onSave={(patch) => save(item, patch)} onMove={(step) => move(rows, index, step)}
                onDelete={() => remove(item)} first={index === 0} last={index === rows.length - 1} />
        ))}
      </ul>
    );
  };

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SystemTabs active="future" />
        <Sheet title="Future" meta={items ? `${items.filter((i) => !['done', 'dropped'].includes(i.status)).length} open` : undefined}>
          <form onSubmit={add} className="flex flex-wrap items-end gap-2 pb-3 border-b border-[var(--rule)]">
            <input aria-label="New item" placeholder="Add an idea…" maxLength={140} value={title}
                   onChange={(e) => setTitle(e.target.value)} className={cn(FIELD, 'flex-1 min-w-[12rem]')} />
            <select aria-label="Area" value={newArea} onChange={(e) => setNewArea(e.target.value)} className={cn(FIELD, 'w-auto')}>
              {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <button type="submit" className="min-h-11 px-3 text-sm border border-[var(--rule-strong)]">Add</button>
          </form>
          <div className="flex flex-wrap gap-1.5 py-2" role="group" aria-label="Filter by area">
            {['', ...AREAS].map((a) => (
              <button key={a || 'all'} type="button" aria-pressed={area === a} onClick={() => setArea(a)}
                      className={cn('min-h-9 px-2.5 field-label border',
                        area === a ? 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]' : 'border-[var(--rule-strong)] text-[var(--ink-soft)]')}>
                {a || 'All'}
              </button>
            ))}
          </div>
          {note && <p role="alert" className="text-sm text-[var(--loss)] py-1">{note}</p>}
          {error ? <Empty title="Could not load the backlog" detail={error} /> : items === null ? <Ruling rows={6} /> : (
            <>
              {OPEN.map(([status, label]) => (
                <section key={status} className="mt-3">
                  <h2 className="field-label text-[var(--ink)]">{label} · {group(status).length}</h2>
                  {list(status)}
                </section>
              ))}
              {CLOSED.map(([status, label]) => (
                <details key={status} className="mt-3">
                  <summary className="field-label cursor-pointer min-h-11 sm:min-h-0 py-1">{label} · {group(status).length}</summary>
                  {list(status)}
                </details>
              ))}
            </>
          )}
        </Sheet>
      </div>
    </Layout>
  );
};

export default Backlog;
