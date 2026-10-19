import React, { useEffect, useMemo, useState } from 'react';
import { Search, Loader2, ChevronDown } from 'lucide-react';
import { Sheet, Empty, Ruling, Button } from './Panel';
import api, { endpoints } from '../../utils/api';
import { cn } from '../../utils/cn';
import { Row } from './Fields';
import { formatQuantity, formatDateTime, formatTimeAgo, formatClock } from '../../utils/formatters';

const TIER_ROWS = [
  { id: 'deep', label: 'Deep', hint: 'Chat, portfolio review, news scoring, peers' },
  { id: 'standard', label: 'Standard', hint: 'Research reports and theses, index explanations' },
  { id: 'fast', label: 'Fast', hint: 'Event tagging, symbol lookup, article sentiment' },
];

const STEP_BUTTON =
  'w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left text-sm border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--accent-soft)]';

/**
 * Family -> model line -> version, the way people think about models
 * ("Claude, then Opus, then 4.6"). A family with one line skips that step.
 * Search all keeps the raw list for an id the tree does not place well.
 */
const ModelChooser = ({ catalog, models, onPick, onClose }) => {
  const [familyKey, setFamilyKey] = useState(null);
  const [lineKey, setLineKey] = useState(null);
  const [search, setSearch] = useState(false);
  const [query, setQuery] = useState('');

  const family = catalog.find((f) => f.key === familyKey);
  const line = family && (family.lines.length === 1 ? family.lines[0] : family.lines.find((l) => l.key === lineKey));
  const step = search ? 'search' : !family ? 'family' : !line ? 'line' : 'version';

  const back = () => {
    if (search) setSearch(false);
    else if (line && family.lines.length > 1) setLineKey(null);
    else if (family) setFamilyKey(null);
    else onClose();
  };

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (term ? models.filter((m) => m.id.toLowerCase().includes(term)) : models).slice(0, 40);
  }, [models, query]);

  // Versions grouped under their number, newest first (the API already sorted them).
  const groups = useMemo(() => {
    if (!line) return [];
    const out = [];
    for (const model of line.models) {
      const key = model.version || model.label;
      const last = out[out.length - 1];
      if (last && last.key === key && model.version) last.models.push(model);
      else out.push({ key, models: [model] });
    }
    return out;
  }, [line]);

  const crumb = [family?.label, family && family.lines.length > 1 ? line?.label : null].filter(Boolean).join(' › ');

  return (
    <div className="mt-2 sheet">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[var(--border)] bg-[var(--surface-2)]">
        <button type="button" onClick={back} className="text-[13px] font-medium text-[var(--text-muted)] text-[var(--accent)] hover:underline min-h-8">
          ‹ {step === 'family' ? 'Close' : 'Back'}
        </button>
        <span className="text-[13px] text-[var(--text-muted)] truncate">
          {step === 'search' ? 'All models' : crumb || 'Choose a family'}
        </span>
        {step !== 'search' ? (
          <button type="button" onClick={() => setSearch(true)} className="text-[13px] font-medium text-[var(--text-muted)] text-[var(--text-muted)] hover:underline min-h-8">
            Search all
          </button>
        ) : (
          <span />
        )}
      </div>
      <div className="max-h-72 overflow-y-auto">
        {step === 'family' &&
          catalog.map((f) => (
            <button key={f.key} type="button" className={STEP_BUTTON} onClick={() => { setFamilyKey(f.key); setLineKey(null); }}>
              <span className="figure-md">{f.label}</span>
              <span className="text-[13px] text-[var(--text-muted)]">{f.count} ›</span>
            </button>
          ))}
        {step === 'line' &&
          family.lines.map((l) => (
            <button key={l.key} type="button" className={STEP_BUTTON} onClick={() => setLineKey(l.key)}>
              <span className="figure-md">{l.label}</span>
              <span className="text-[13px] text-[var(--text-muted)]">{l.models.length} ›</span>
            </button>
          ))}
        {step === 'version' &&
          groups.map((group) => (
            <div key={group.key}>
              {group.models[0].version && (
                <p className="px-3 pt-2 pb-1 text-[13px] font-medium text-[var(--text-muted)] text-[var(--text)] bg-[var(--surface-2)]">
                  {line.key === 'all' || line.key === 'other' ? '' : `${line.label} `}{group.key}
                </p>
              )}
              {group.models.map((model) => (
                <button key={model.id} type="button" className={STEP_BUTTON} onClick={() => onPick(model.id)}>
                  <span className="min-w-0">
                    <span className="text-sm block truncate">
                      {model.version ? model.variant || 'standard' : model.label}
                    </span>
                    <span className="text-[13px] text-[var(--text-muted)] block truncate">{model.id}</span>
                  </span>
                  <span className="text-[13px] text-[var(--text-muted)] shrink-0">{model.provider}</span>
                </button>
              ))}
            </div>
          ))}
        {step === 'search' && (
          <>
            <div className="flex items-center gap-2 px-3 border-b border-[var(--border)]">
              <Search className="w-4 h-4 shrink-0 text-[var(--text-muted)]" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter every model id"
                className="w-full bg-transparent border-0 py-2 text-sm focus:outline-none"
                aria-label="Filter models"
              />
            </div>
            {filtered.length === 0 ? (
              <p className="px-3 py-2.5 text-sm text-[var(--text-muted)]">No match.</p>
            ) : (
              filtered.map((model) => (
                <button key={model.id} type="button" className={STEP_BUTTON} onClick={() => onPick(model.id)}>
                  <span className="figure-md truncate">{model.id}</span>
                </button>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
};

/** One model choice: pick it step by step, test it, save it. */
const ModelRow = ({ label, hint, value, fallback, models, catalog, onSave, clearable, expanded, onToggle }) => {
  const [selected, setSelected] = useState(value || '');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(null);
  const [test, setTest] = useState(null);
  const [note, setNote] = useState(null);

  useEffect(() => setSelected(value || ''), [value]);
  // A result belongs to the model it ran on; picking another clears it.
  useEffect(() => setTest(null), [selected]);

  const effective = selected || fallback;

  const runTest = async () => {
    setBusy('test');
    try {
      const res = await api.post(endpoints.settings.omnirouteModelTest, { model: effective });
      setTest(res.data);
    } catch (err) {
      setTest({ ok: false, error: err?.response?.data?.detail || 'The test request failed' });
    } finally {
      setBusy(null);
    }
  };

  const save = async (model) => {
    setBusy('save');
    setNote(null);
    try {
      await onSave(model);
      setNote(model ? 'Saved.' : 'Cleared: uses the fallback.');
    } catch (err) {
      setNote(err?.response?.status === 403 ? 'Only an administrator can change models.' : 'Could not save.');
    } finally {
      setBusy(null);
    }
  };

  // Collapsed: one line -- the tier and the model it runs on. Tap to open.
  if (!expanded) {
    return (
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={false}
        className="w-full py-3 min-h-11 flex items-center gap-3 border-b border-[var(--border)] last:border-b-0 text-left hover:bg-[var(--surface-2)] transition-colors"
      >
        <span className="text-[13px] font-medium text-[var(--text-muted)] text-[var(--text)] w-20 shrink-0">{label}</span>
        <span className={cn('flex-1 min-w-0 truncate text-sm', selected ? 'figure-md' : 'text-[var(--text-muted)]')}>
          {selected || (clearable ? `Fallback: ${fallback}` : 'No model')}
        </span>
        <ChevronDown className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
      </button>
    );
  }

  return (
    <div className="py-3 border-b border-[var(--border)] last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <button type="button" onClick={onToggle} aria-expanded className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--text-muted)] text-[var(--text)]">
          {label}
          <ChevronDown className="w-4 h-4 rotate-180 text-[var(--text-muted)]" aria-hidden="true" />
        </button>
        {clearable && value && (
          <button type="button" onClick={() => save(null)} disabled={busy !== null} className="text-[13px] font-medium text-[var(--text-muted)] text-[var(--accent)] hover:underline">
            Use fallback
          </button>
        )}
      </div>
      <p className="text-[13px] text-[var(--text-muted)] mt-0.5">{hint}</p>
      <div className="mt-2 flex items-center justify-between gap-3 border-b border-[var(--border)] pb-2">
        <span className={cn('min-w-0 truncate text-sm', selected ? 'figure-md' : 'text-[var(--text-muted)]')}>
          {selected || (clearable ? `Uses fallback: ${fallback}` : 'No model')}
        </span>
        <button
          type="button"
          onClick={() => setOpen((value_) => !value_)}
          aria-expanded={open}
          className="text-[13px] font-medium text-[var(--text-muted)] text-[var(--accent)] hover:underline shrink-0 min-h-8"
        >
          {open ? 'Close' : 'Change'}
        </button>
      </div>
      {open && (
        <ModelChooser
          catalog={catalog}
          models={models}
          onClose={() => setOpen(false)}
          onPick={(id) => {
            setSelected(id);
            setOpen(false);
          }}
        />
      )}
      <div className="mt-2 flex items-center justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={runTest} disabled={busy !== null || !effective}>
          {busy === 'test' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
          Test
        </Button>
        <Button variant="primary" size="sm" onClick={() => save(selected)} disabled={busy !== null || !selected || selected === value}>
          {busy === 'save' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
          Save
        </Button>
      </div>
      {test && (
        <p
          role="status"
          className={cn(
            'mt-2 text-sm px-3 py-2 border break-words',
            test.ok
              ? 'text-[var(--gain)] border-[var(--gain)] bg-[var(--gain-wash)]'
              : 'text-[var(--loss)] border-[var(--loss)] bg-[var(--loss-wash)]'
          )}
        >
          {test.ok ? `${test.model} works · ${(test.latency_ms / 1000).toFixed(1)}s · replied: ${test.reply}` : `Failed: ${test.error}`}
        </p>
      )}
      {note && <p className="mt-1.5 text-[13px] text-[var(--text-muted)]">{note}</p>}
    </div>
  );
};

const ModelSheet = ({ isAdmin }) => {
  const [models, setModels] = useState([]);
  const [fallback, setFallback] = useState('');
  const [tiers, setTiers] = useState({});
  const [catalog, setCatalog] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [openRow, setOpenRow] = useState(null); // at most one tier open at a time
  const toggle = (id) => () => setOpenRow((current) => (current === id ? null : id));

  useEffect(() => {
    let cancelled = false;
    // Only an admin can change the models, so only an admin needs the
    // gateway's full list and catalog for the picker.
    Promise.all([
      api.get(endpoints.settings.omnirouteModel),
      api.get(endpoints.settings.omnirouteTiers),
      ...(isAdmin ? [api.get(endpoints.settings.omnirouteModels), api.get(endpoints.settings.omnirouteCatalog)] : []),
    ])
      .then(([currentRes, tiersRes, modelsRes, catalogRes]) => {
        if (cancelled) return;
        setFallback(currentRes.data.model);
        setTiers(tiersRes.data.tiers);
        if (modelsRes) setModels(modelsRes.data);
        if (catalogRes) setCatalog(catalogRes.data);
      })
      .catch(() => {
        if (!cancelled) setLoadError('Could not reach the OmniRoute gateway.');
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const saveTier = (tier) => async (model) => {
    await api.post(endpoints.settings.omnirouteTiers, { tier, model });
    setTiers((current) => ({ ...current, [tier]: model }));
  };

  const saveFallback = async (model) => {
    await api.post(endpoints.settings.omnirouteModel, { model });
    setFallback(model);
  };

  // Deployment-wide: every user's requests run on these models, so the
  // server only lets an admin change them. Everyone else sees them locked.
  if (!isAdmin) {
    return (
      <Sheet title="Models" meta="Set by an admin">
        {loadError ? (
          <Empty title="Gateway unreachable" detail={loadError} />
        ) : !fallback ? (
          <Ruling rows={4} />
        ) : (
          <>
            <p className="text-sm text-[var(--text-muted)] pb-1">
              The models are chosen by an admin for everyone using this app.
            </p>
            {[...TIER_ROWS, { id: 'fallback', label: 'Fallback', hint: 'Any task whose tier is not set' }].map((row) => (
              <Row key={row.id} label={row.label} hint={row.hint}>
                <span className="figure-md text-[15px] tabular-nums break-all">
                  {row.id === 'fallback' ? fallback : tiers[row.id] || `Fallback (${fallback})`}
                </span>
              </Row>
            ))}
          </>
        )}
      </Sheet>
    );
  }

  return (
    <Sheet title="Models" meta={`${models.length} available`}>
      {loadError ? (
        <Empty title="Gateway unreachable" detail={loadError} />
      ) : (
        <>
          <p className="text-sm text-[var(--text-muted)]">
            Each kind of task runs on its own model, so cheap work does not spend the strongest model's quota.
            The trading engine itself never calls a model on the hot path.
          </p>
          {TIER_ROWS.map((row) => (
            <ModelRow
              key={row.id}
              label={row.label}
              hint={row.hint}
              value={tiers[row.id]}
              fallback={fallback}
              models={models}
              catalog={catalog}
              onSave={saveTier(row.id)}
              clearable
              expanded={openRow === row.id}
              onToggle={toggle(row.id)}
            />
          ))}
          <ModelRow
            label="Fallback"
            hint="Any task whose tier is not set"
            value={fallback}
            fallback={fallback}
            models={models}
            catalog={catalog}
            onSave={saveFallback}
            expanded={openRow === 'fallback'}
            onToggle={toggle('fallback')}
          />
        </>
      )}
    </Sheet>
  );
};

/** The gateway key's own month, and how much each provider account has left. */
const Bar = ({ pct }) => (
  <div className="h-1.5 bg-[var(--surface-2)] flex-1 min-w-[3rem]" aria-hidden="true">
    <div
      className={cn('h-full', pct < 20 ? 'bg-[var(--loss)]' : 'bg-[var(--text)]')}
      style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
    />
  </div>
);

const pctText = (pct) => (pct == null ? '—' : `${Math.round(pct)}% left`);

/** "6:19 AM" today, "07 Oct" later: when a pool fills back up. */
const resetText = (iso) => {
  if (!iso) return '';
  const when = new Date(iso);
  const sameDay = when.toDateString() === new Date().toDateString();
  return sameDay
    ? formatClock(when)
    : when.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' });
};

const PoolRow = ({ pool }) => {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={!pool.models.length}
        aria-expanded={open}
        className="w-full flex items-center gap-2 py-1 text-left text-[13px] disabled:cursor-default"
      >
        <span className="w-[6.5rem] shrink-0 leading-tight text-[var(--text)]">{pool.label}</span>
        <Bar pct={pool.remaining_pct} />
        <span className="figure-md w-[4.25rem] text-right shrink-0 whitespace-nowrap">{pctText(pool.remaining_pct)}</span>
      </button>
      <p className="text-[13px] text-[var(--text-muted)] pl-[6.5rem] -mt-0.5">
        {pool.reset_at ? `resets ${resetText(pool.reset_at)}` : ''}
        {pool.models.length ? ` · ${pool.models.length} model${pool.models.length === 1 ? '' : 's'}` : ''}
      </p>
      {open && (
        <p className="pl-[6.5rem] pt-1 pb-1.5 text-[13px] text-[var(--text-muted)] break-words">{pool.models.join(', ')}</p>
      )}
    </li>
  );
};

const ProviderRow = ({ provider }) => (
  <li className="py-2 border-b border-[var(--border)] last:border-b-0">
    <p className="flex items-baseline gap-2 mb-1">
      <span className="figure-md text-[15px] tabular-nums">{provider.provider}</span>
      {provider.plan && <span className="text-[13px] text-[var(--text-muted)]">{provider.plan}</span>}
    </p>
    <ul className="space-y-1">
      {provider.pools.map((pool) => (
        <PoolRow key={pool.label} pool={pool} />
      ))}
    </ul>
  </li>
);

const USAGE_RETRIES = 5;
const USAGE_RETRY_MS = 4000;

const UsageSheet = () => {
  const [usage, setUsage] = useState(null);
  const [error, setError] = useState('');

  // An old reading comes back at once with `refreshing`; ask again until the
  // gateway's slow quota poll has landed (a few seconds), then stop.
  useEffect(() => {
    let timer;
    let tries = 0;
    let live = true;
    const load = () =>
      api
        .get(endpoints.settings.omnirouteUsage)
        .then((res) => {
          if (!live) return;
          setUsage(res.data);
          if (res.data.refreshing && ++tries <= USAGE_RETRIES) timer = setTimeout(load, USAGE_RETRY_MS);
        })
        .catch((err) => setError(err?.response?.data?.detail || 'Could not read usage from the gateway.'));
    load();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);

  return (
    <Sheet title="Usage" meta={usage?.key_name ? `Key · ${usage.key_name}` : 'OmniRoute'}>
      {error ? (
        <Empty title="Usage unavailable" detail={error} />
      ) : !usage ? (
        <Ruling rows={3} />
      ) : (
        <>
          <p className="text-[13px] font-medium text-[var(--text-muted)] mb-1">This month, this app's key</p>
          <p className="figure-md text-xl">{formatQuantity(usage.tokens.total)} tokens</p>
          <dl className="mt-2 grid grid-cols-3 gap-2">
            {[['Input', usage.tokens.input], ['Output', usage.tokens.output], ['Reasoning', usage.tokens.reasoning]].map(([label, value]) => (
              <div key={label}>
                <dt className="text-[13px] font-medium text-[var(--text-muted)]">{label}</dt>
                <dd className="figure-md text-[15px] tabular-nums">{formatQuantity(value)}</dd>
              </div>
            ))}
          </dl>
          <p className="text-[13px] text-[var(--text-muted)] mt-2">
            Cost ${Number(usage.cost.used_usd || 0).toFixed(2)}
            {usage.cost.limit_usd != null ? ` of $${Number(usage.cost.limit_usd).toFixed(2)}` : ' · no cost limit'}
            {usage.cost.reset_at ? ` · resets ${formatDateTime(usage.cost.reset_at)}` : ''}
          </p>
          {/* Served from the last reading while the gateway's slow quota poll refreshes it. */}
          {usage.as_of && (
            <p className="text-[13px] text-[var(--text-muted)]" aria-live="polite">
              Read {formatTimeAgo(usage.as_of)}{usage.refreshing ? ' · updating…' : ''}
            </p>
          )}

          <p className="text-[13px] font-medium text-[var(--text-muted)] mt-4 mb-1">Providers · quota left</p>
          <p className="text-[13px] text-[var(--text-muted)] mb-1">
            The gateway's shared accounts, not only this app's use. Models in one pool share its limit; tap a pool for its models.
          </p>
          <ul>
            {usage.providers
              .filter((provider) => provider.pools?.length)
              .map((provider) => (
                <ProviderRow key={provider.provider} provider={provider} />
              ))}
          </ul>
        </>
      )}
    </Sheet>
  );
};

export { ModelSheet, UsageSheet };
