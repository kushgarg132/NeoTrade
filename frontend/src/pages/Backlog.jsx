import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { LAB_TABS } from '../components/layout/sections';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import PageHeader from '../components/ui/PageHeader';
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
const FIELD = 'w-full bg-transparent border-b border-[var(--border)] py-1 text-[15px] min-h-11 focus:outline-none focus:border-[var(--accent)]';
const SMALL_BUTTON = 'min-h-11 min-w-11 px-2 rounded-[8px] border border-[var(--border)] text-[15px] disabled:opacity-40 inline-flex items-center justify-center';

const Editor = ({ item, onSave }) => {
  const [draft, setDraft] = useState({ why: item.why, notes: item.notes });
  const blur = (key) => () => draft[key] !== item[key] && onSave({ [key]: draft[key] });
  return (
    <div className="mt-2 space-y-2">
      <label className="block">
        <span className="text-[13px] text-[var(--text-muted)]">Why</span>
        <textarea rows={2} maxLength={2000} className={FIELD} value={draft.why}
                  onChange={(e) => setDraft((d) => ({ ...d, why: e.target.value }))} onBlur={blur('why')} />
      </label>
      <label className="block">
        <span className="text-[13px] text-[var(--text-muted)]">Notes</span>
        <textarea rows={3} maxLength={4000} className={FIELD} value={draft.notes}
                  onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))} onBlur={blur('notes')} />
      </label>
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-[15px]">
          <span className="text-[13px] text-[var(--text-muted)]">Status</span>
          <select className={FIELD} value={item.status} onChange={(e) => onSave({ status: e.target.value })}>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-[15px]">
          <span className="text-[13px] text-[var(--text-muted)]">Effort</span>
          <select className={FIELD} value={item.effort || ''} onChange={(e) => onSave({ effort: e.target.value || null })}>
            <option value="">—</option>
            {['S', 'M', 'L'].map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-[15px]">
          <span className="text-[13px] text-[var(--text-muted)]">Area</span>
          <select className={FIELD} value={item.area} onChange={(e) => onSave({ area: e.target.value })}>
            {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
      </div>
      {item.source && <p className="text-[12px] text-[var(--text-muted)]">From {item.source} · updated {formatTimeAgo(item.updated_at)}</p>}
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
        <button type="button" onClick={onToggle} aria-expanded={open} className="min-w-0 flex-1 text-left min-h-11">
          <span className="block text-[15px] font-semibold">{item.title}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <Badge>{item.area}</Badge>
            {item.effort && <Badge>{`Effort ${item.effort}`}</Badge>}
            {!open && item.why && <span className="min-w-0 truncate text-[13px] text-[var(--text-muted)]">{item.why}</span>}
          </span>
        </button>
        <div className="flex shrink-0 gap-1">
          <button type="button" aria-label="Move up" className={SMALL_BUTTON} disabled={first} onClick={() => onMove(-1)}>
            <ArrowUp className="w-4 h-4" />
          </button>
          <button type="button" aria-label="Move down" className={SMALL_BUTTON} disabled={last} onClick={() => onMove(1)}>
            <ArrowDown className="w-4 h-4" />
          </button>
          <button type="button" onClick={remove} aria-label={arming ? 'Tap again to delete' : 'Delete item'}
                  className={cn(SMALL_BUTTON, arming && 'border-[var(--loss)] text-[var(--loss)] px-3')}>
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

  const load = useCallback(() => {
    api.get(endpoints.system.backlog)
      .then((res) => setItems(res.data?.items ?? []))
      .catch((err) => setError(err?.response?.data?.detail || 'The server did not answer'));
  }, []);
  useEffect(load, [load]);
  const retry = () => {
    setError(null);
    load();
  };
  const input = useRef(null);

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

  const list = (rows) => {
    return (
      <ul className="divide-y divide-[var(--border)]">
        {rows.map((item, index) => (
          <Item key={item.id} item={item} open={openId === item.id}
                onToggle={() => setOpenId((id) => (id === item.id ? null : item.id))}
                onSave={(patch) => save(item, patch)} onMove={(step) => move(rows, index, step)}
                onDelete={() => remove(item)} first={index === 0} last={index === rows.length - 1} />
        ))}
      </ul>
    );
  };

  const shown = [...OPEN, ...CLOSED].reduce((n, [status]) => n + group(status).length, 0);
  const openCount = (items || []).filter((i) => !['done', 'dropped'].includes(i.status)).length;

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SectionTabs tabs={LAB_TABS} label="Lab" />
        <PageHeader title="Backlog" right={items && <span className="text-[14px] text-[var(--text-muted)]">{openCount} open</span>} />
        <p className="-mt-2 text-[14px] text-[var(--text-muted)]">Your list of future changes to NeoTrade. Idea, then Next, then Doing; Done and Dropped fold away.</p>
        <Card>
          <form onSubmit={add} className="flex items-end gap-2">
            <input ref={input} aria-label="New item" placeholder="Add an idea…" maxLength={140} value={title}
                   onChange={(e) => setTitle(e.target.value)} className={cn(FIELD, 'flex-1 min-w-0')} />
            <select aria-label="Area" value={newArea} onChange={(e) => setNewArea(e.target.value)} className={cn(FIELD, 'w-auto shrink-0')}>
              {AREAS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <Button type="submit" className="shrink-0">Add</Button>
          </form>
        </Card>
        <div className="flex gap-1.5 overflow-x-auto" role="group" aria-label="Filter by area">
          {['', ...AREAS].map((a) => (
            <button key={a || 'all'} type="button" aria-pressed={area === a} onClick={() => setArea(a)}
                    className={cn('shrink-0 min-h-11 px-3.5 rounded-full text-[14px] font-medium',
                      area === a ? 'bg-[var(--accent)] text-[var(--surface)]' : 'bg-[var(--surface-2)] text-[var(--text-muted)]')}>
              {a || 'All'}
            </button>
          ))}
        </div>
        {note && <p role="alert" className="text-[14px] text-[var(--loss)]">{note}</p>}
        {error ? <ErrorLine message={`Could not load the backlog: ${error}.`} onRetry={retry} />
          : items === null ? <Skeleton rows={6} />
          : items.length === 0 ? (
            <Empty title="The backlog is empty" body="Type an idea above and tap Add. It starts under Ideas."
                   action={<Button onClick={() => input.current?.focus()}>Add the first item</Button>} />
          ) : shown === 0 ? (
            <Empty title={`Nothing filed under ${area}`} action={<Button variant="secondary" onClick={() => setArea('')}>Show all areas</Button>} />
          ) : (
            <Card>
              {OPEN.map(([status, label]) => {
                const rows = group(status);
                return rows.length > 0 && (
                  <section key={status} className="mb-3 last:mb-0">
                    <h2 className="text-[15px] font-semibold">{label} · {rows.length}</h2>
                    {list(rows)}
                  </section>
                );
              })}
              {CLOSED.map(([status, label]) => {
                const rows = group(status);
                return rows.length > 0 && (
                  <details key={status} className="mt-1">
                    <summary className="text-[14px] text-[var(--text-muted)] cursor-pointer min-h-11 flex items-center">{label} · {rows.length}</summary>
                    {list(rows)}
                  </details>
                );
              })}
            </Card>
          )}
      </div>
    </Layout>
  );
};

export default Backlog;
