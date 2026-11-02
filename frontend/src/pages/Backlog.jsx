import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUp, Search, Trash2 } from 'lucide-react';
import SettingsPage from './SettingsPage';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import ErrorLine from '../components/ui/ErrorLine';
import Skeleton from '../components/ui/Skeleton';
import Button from '../components/ui/Button';
import Tabs from '../components/ui/Tabs';
import api, { endpoints } from '../utils/api';
import { cn } from '../utils/cn';
import { AREAS, AREA_COLOR, EFFORTS, STAGES, VIEWS, advance, byStatus, counts, filterItems, stageTime, timeline } from '../utils/backlog';

/**
 * The operator's backlog of future enhancements (admin-only, /system/future): one app-wide list in Mongo,
 * edited in place. Phone: tabs (Now, Ideas, Done, Dropped). Desktop: a board (Ideas | Next | Doing) with
 * Done and Dropped folded below. Writes are optimistic and roll back with the API's message when refused.
 */

const FIELD = 'w-full bg-transparent border-b border-[var(--border)] py-1 text-[15px] min-h-11 focus:outline-none focus:border-[var(--accent)]';
const ICON_BUTTON = 'min-h-11 min-w-11 px-2 rounded-[10px] border border-[var(--border)] text-[14px] disabled:opacity-40 inline-flex items-center justify-center gap-1.5';
const LABEL = 'text-[12px] font-medium uppercase tracking-wide text-[var(--text-muted)]';
const BOARD = ['idea', 'next', 'doing'];
const STAGE_LABEL = Object.fromEntries(STAGES);

/** A row of single-choice chips (status, effort, area); `allowNone` adds a clear chip. */
const Chips = ({ options, value, onPick, label, allowNone = false }) => (
  <div role="group" aria-label={label} className="flex gap-1.5 overflow-x-auto">
    {[...(allowNone ? [['', 'Any']] : []), ...options].map(([v, text]) => (
      <button key={v || 'none'} type="button" aria-pressed={value === v} onClick={() => onPick(v)}
              className={cn('tap shrink-0 min-h-9 px-3 rounded-full text-[13px] font-medium',
                value === v ? 'bg-[var(--accent)] text-[var(--accent-ink)]' : 'bg-[var(--surface-2)] text-[var(--text-muted)]')}>
        {text}
      </button>
    ))}
  </div>
);
const pairs = (list) => list.map((x) => [x, x]);

const Editor = ({ item, onSave, onMove, onDelete, first, last }) => {
  const [draft, setDraft] = useState({ why: item.why, notes: item.notes });
  const [arming, setArming] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const blur = (key) => () => draft[key] !== item[key] && onSave({ [key]: draft[key] });
  const remove = () => {
    if (arming) return onDelete();
    setArming(true);
    timer.current = setTimeout(() => setArming(false), 3000);
    return undefined;
  };
  return (
    <div className="mt-3 space-y-3 border-t border-[var(--border)] pt-3 fade-in">
      <div className="space-y-1.5"><p className={LABEL}>Status</p>
        <Chips label="Status" options={STAGES} value={item.status} onPick={(status) => onSave({ status })} /></div>
      <div className="space-y-1.5"><p className={LABEL}>Effort</p>
        <Chips label="Effort" options={pairs(EFFORTS)} value={item.effort || ''} allowNone onPick={(effort) => onSave({ effort: effort || null })} /></div>
      <div className="space-y-1.5"><p className={LABEL}>Area</p>
        <Chips label="Area" options={pairs(AREAS)} value={item.area} onPick={(area) => onSave({ area })} /></div>
      <label className="block">
        <span className={LABEL}>Why</span>
        <textarea rows={2} maxLength={2000} className={FIELD} value={draft.why}
                  onChange={(e) => setDraft((d) => ({ ...d, why: e.target.value }))} onBlur={blur('why')} />
      </label>
      <label className="block">
        <span className={LABEL}>Notes</span>
        <textarea rows={3} maxLength={4000} className={FIELD} value={draft.notes}
                  onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))} onBlur={blur('notes')} />
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" aria-label="Move up" className={ICON_BUTTON} disabled={first} onClick={() => onMove(-1)}><ArrowUp className="w-4 h-4" /></button>
        <button type="button" aria-label="Move down" className={ICON_BUTTON} disabled={last} onClick={() => onMove(1)}><ArrowDown className="w-4 h-4" /></button>
        <button type="button" onClick={remove} aria-label={arming ? 'Tap again to delete' : 'Delete item'}
                className={cn(ICON_BUTTON, 'ml-auto px-3', arming && 'border-[var(--loss)] text-[var(--loss)]')}>
          <Trash2 className="w-4 h-4" />{arming ? 'Tap again to delete' : 'Delete'}
        </button>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[12px] text-[var(--text-muted)]">
        {timeline(item).map(({ label, at }) => (
          <React.Fragment key={label}><dt>{label}</dt><dd className="tabular-nums">{at}</dd></React.Fragment>
        ))}
        {item.source && <><dt>From</dt><dd>{item.source}</dd></>}
      </dl>
    </div>
  );
};

const Item = ({ item, open, onToggle, onSave, ...editor }) => {
  const next = advance(item.status);
  return (
    <li className={cn('rounded-[14px] border border-[var(--border)] bg-[var(--surface)] p-3', open && 'ring-1 ring-[var(--accent)]')}>
      <div className="flex items-start gap-2.5">
        <span aria-hidden="true" className="mt-2 w-2.5 h-2.5 shrink-0 rounded-full" style={{ background: AREA_COLOR[item.area] }} />
        <button type="button" onClick={onToggle} aria-expanded={open} className="min-w-0 flex-1 text-left min-h-11">
          <span className="block text-[15px] font-semibold leading-5 text-[var(--text)]">{item.title}</span>
          <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-[var(--text-muted)]">
            <span>{item.area}</span>
            {item.effort && <span className="rounded-full bg-[var(--surface-2)] px-1.5 font-semibold">{item.effort}</span>}
            {stageTime(item) && <span className="tabular-nums">{stageTime(item)}</span>}
          </span>
          {!open && item.why && <span className="mt-1 block line-clamp-1 text-[13px] text-[var(--text-muted)]">{item.why}</span>}
        </button>
        {next && (
          <button type="button" onClick={() => onSave({ status: next.to })} aria-label={`Move to ${STAGE_LABEL[next.to]}`}
                  className="tap shrink-0 min-h-11 min-w-11 px-3 rounded-[10px] bg-[var(--accent-soft)] text-[var(--accent)] text-[13px] font-semibold inline-flex items-center gap-1">
            {next.label}<ArrowRight className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {open && <Editor item={item} onSave={onSave} {...editor} />}
    </li>
  );
};

const Backlog = () => {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [note, setNote] = useState(null);
  const [view, setView] = useState('now');
  const [filters, setFilters] = useState({ q: '', area: '', effort: '' });
  const [openId, setOpenId] = useState(null);
  const [draft, setDraft] = useState({ title: '', area: 'Product', status: 'idea', effort: '' });

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
    if (!draft.title.trim()) return;
    setNote(null);
    const body = { title: draft.title.trim(), area: draft.area, status: draft.status, ...(draft.effort ? { effort: draft.effort } : {}) };
    api.post(endpoints.system.backlog, body)
      .then((res) => {
        setItems((list) => [...list, res.data]);
        setDraft((d) => ({ ...d, title: '' }));
      })
      .catch((err) => setNote(err?.response?.data?.detail?.[0]?.msg || err?.response?.data?.detail || 'Could not add it.'));
  };

  const shown = filterItems(items, filters);
  const total = counts(items);
  const filtering = filters.q || filters.area || filters.effort;

  const list = (status) => {
    const rows = byStatus(shown, status);
    return (
      <ul className="space-y-2">
        {rows.map((item, index) => (
          <Item key={item.id} item={item} open={openId === item.id}
                onToggle={() => setOpenId((id) => (id === item.id ? null : item.id))}
                onSave={(patch) => save(item, patch)} onMove={(step) => move(rows, index, step)}
                onDelete={() => remove(item)} first={index === 0} last={index === rows.length - 1} />
        ))}
      </ul>
    );
  };
  const column = (status, title = STAGE_LABEL[status]) => {
    const n = byStatus(shown, status).length;
    return (
      <section key={status} className="min-w-0 space-y-2">
        <h2 className="flex items-center gap-2 text-[14px] font-semibold text-[var(--text)]">
          {title}<span className="rounded-full bg-[var(--surface-2)] px-2 text-[12px] text-[var(--text-muted)]">{n}</span>
        </h2>
        {n ? list(status) : <p className="rounded-[14px] border border-dashed border-[var(--border)] p-3 text-[13px] text-[var(--text-muted)]">Empty</p>}
      </section>
    );
  };
  const folded = (status) => {
    const n = byStatus(shown, status).length;
    return n > 0 && (
      <details key={status} className="group">
        <summary className="min-h-11 flex cursor-pointer items-center text-[14px] font-medium text-[var(--text-muted)]">{STAGE_LABEL[status]} · {n}</summary>
        {list(status)}
      </details>
    );
  };
  const tabStatuses = VIEWS.find((v) => v.id === view).statuses;

  return (
    <SettingsPage title="Backlog" back="/settings/lab" backLabel="Lab" right={items && <span className="text-[14px] text-[var(--text-muted)]">{total.idea + total.next + total.doing} open</span>}>
      <div className="space-y-3 sm:space-y-4 max-w-6xl">
        {items && items.length > 0 && (
          <div className="grid grid-cols-4 gap-2">
            {[['doing', 'Doing', 'now'], ['next', 'Next', 'now'], ['idea', 'Ideas', 'idea'], ['done', 'Done', 'done']].map(([s, label, v]) => (
              <button key={s} type="button" onClick={() => setView(v)}
                      className={cn('tap rounded-[14px] border border-[var(--border)] bg-[var(--surface)] p-2.5 text-left', view === v && 'lg:border-[var(--border)] border-[var(--accent)]')}>
                <span className="block text-[22px] font-bold tabular-nums leading-7 text-[var(--text)]">{total[s]}</span>
                <span className="text-[12px] text-[var(--text-muted)]">{label}</span>
              </button>
            ))}
          </div>
        )}

        <Card>
          <form onSubmit={add} className="space-y-2.5">
            <div className="flex items-end gap-2">
              <input ref={input} aria-label="New item" placeholder="Add an idea…" maxLength={140} value={draft.title}
                     onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} className={cn(FIELD, 'flex-1 min-w-0')} />
              <Button type="submit" className="shrink-0">Add</Button>
            </div>
            {draft.title && (
              <div className="space-y-2 fade-in">
                <Chips label="New item stage" options={[['idea', 'Idea'], ['next', 'Next']]} value={draft.status} onPick={(status) => setDraft((d) => ({ ...d, status }))} />
                <Chips label="New item effort" options={pairs(EFFORTS)} value={draft.effort} allowNone onPick={(effort) => setDraft((d) => ({ ...d, effort }))} />
                <Chips label="New item area" options={pairs(AREAS)} value={draft.area} onPick={(area) => setDraft((d) => ({ ...d, area }))} />
              </div>
            )}
          </form>
        </Card>

        <div className="space-y-2">
          <label className="flex items-center gap-2 rounded-[12px] bg-[var(--surface-2)] px-3">
            <Search className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
            <input type="search" aria-label="Search the backlog" placeholder="Search title, why, notes" value={filters.q}
                   onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
                   className="min-h-11 w-full bg-transparent text-[15px] focus:outline-none" />
          </label>
          <Chips label="Filter by area" options={pairs(AREAS)} value={filters.area} allowNone onPick={(area) => setFilters((f) => ({ ...f, area }))} />
          <Chips label="Filter by effort" options={EFFORTS.map((e) => [e, `Effort ${e}`])} value={filters.effort} allowNone onPick={(effort) => setFilters((f) => ({ ...f, effort }))} />
        </div>

        {note && <p role="alert" className="text-[14px] text-[var(--loss)]">{note}</p>}
        {error ? <ErrorLine message={`Could not load the backlog: ${error}.`} onRetry={retry} />
          : items === null ? <Skeleton rows={6} />
          : items.length === 0 ? (
            <Empty title="The backlog is empty" body="Type an idea above and tap Add. It starts under Ideas."
                   action={<Button onClick={() => input.current?.focus()}>Add the first item</Button>} />
          ) : filtering && shown.length === 0 ? (
            <Empty title="No item matches" action={<Button variant="secondary" onClick={() => setFilters({ q: '', area: '', effort: '' })}>Clear filters</Button>} />
          ) : (
            <>
              {/* Phone: one tab at a time. */}
              <div className="space-y-3 lg:hidden">
                <Tabs tabs={VIEWS.map((v) => ({ id: v.id, label: v.label }))} value={view} onChange={setView} label="Backlog stage" />
                {tabStatuses.map((s) => (tabStatuses.length > 1 ? column(s) : <div key={s}>{list(s)}</div>))}
                {tabStatuses.every((s) => byStatus(shown, s).length === 0) && (
                  <p className="text-[14px] text-[var(--text-muted)]">This stage is empty{filtering ? ' with these filters' : ''}.</p>
                )}
              </div>
              {/* Desktop: the board, closed stages folded below. */}
              <div className="hidden lg:block space-y-4">
                <div className="grid grid-cols-3 gap-4">{BOARD.map((s) => column(s))}</div>
                <div className="space-y-1">{folded('done')}{folded('dropped')}</div>
              </div>
            </>
          )}
      </div>
    </SettingsPage>
  );
};

export default Backlog;
