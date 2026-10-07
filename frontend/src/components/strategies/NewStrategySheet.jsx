import React, { useEffect, useState } from 'react';
import { Row } from '../settings/Fields';
import api, { endpoints } from '../../utils/api';
import { cn } from '../../utils/cn';

/**
 * The New strategy form. Every block, parameter and range comes from
 * GET /strategies/vocabulary (backend/strategies/blocks/vocab.py), so the form
 * can't drift from the validator; the preview line is the server's own
 * description of the spec, or why it was refused.
 */

const MAX_FILTERS = 3;
const FIELD = 'bg-transparent border-b border-[var(--rule-strong)] py-1 text-sm focus:outline-none focus:border-[var(--stamp)] min-h-11 sm:min-h-0';
const label = (code) => code.replace(/_/g, ' ');

/** A starting value for one parameter: the first choice, else the low end of its range — or the high end
 *  for the top of a range filter (time_window end, atr_pct max), so a new filter is valid at once. */
const startValue = (key, spec) => {
  if (spec.choices) return key === 'regimes' ? [spec.choices[0]] : spec.choices[0];
  const high = key === 'end' || key === 'max';
  return spec.time ? spec.time[high ? 1 : 0] : high ? spec.max : spec.min;
};

const startParams = (block) => Object.fromEntries(Object.entries(block).filter(([, s]) => !s.flag).map(([k, s]) => [k, startValue(k, s)]));

/** One parameter's input, by the shape of its vocabulary spec. */
const Param = ({ name, spec, value, onChange, required }) => {
  if (spec.choices && name === 'regimes') { // the one multi-choice parameter
    return (
      <span className="flex flex-wrap gap-x-3">
        {spec.choices.map((c) => (
          <label key={c} className="inline-flex items-center gap-1.5 text-sm min-h-11 sm:min-h-8">
            <input type="checkbox" checked={value.includes(c)}
                   onChange={(e) => onChange(e.target.checked ? [...value, c] : value.filter((v) => v !== c))} />
            {label(c)}
          </label>
        ))}
      </span>
    );
  }
  if (spec.choices) {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label(name)} className={FIELD}>
        {spec.choices.map((c) => <option key={c} value={c}>{label(c)}</option>)}
      </select>
    );
  }
  if (spec.time) {
    return <input type="time" value={value} min={spec.time[0]} max={spec.time[1]} step={300}
                  onChange={(e) => onChange(e.target.value)} aria-label={label(name)} className={FIELD} />;
  }
  return <input type="number" inputMode="decimal" required={required} value={value} min={spec.min} max={spec.max} step={spec.step}
                onChange={(e) => onChange(e.target.value)} aria-label={label(name)} className={cn(FIELD, 'w-24 text-right figure-md')} />;
};

/** A block's parameters as rows; a block with none (a flag) shows nothing. */
const Params = ({ block, params, onChange }) =>
  Object.entries(block).filter(([, s]) => !s.flag).map(([k, s]) => (
    <Row key={k} label={label(k)}>
      <Param name={k} spec={s} value={params[k]} onChange={(v) => onChange({ ...params, [k]: v })} />
    </Row>
  ));

const clean = (params) => Object.fromEntries(Object.entries(params).map(([k, v]) => [k, typeof v === 'string' && v !== '' && !isNaN(v) ? Number(v) : v]));

const HorizonForm = ({ horizon, vocab, onSubmitted }) => {
  const swing = horizon === 'swing';
  const firstSetup = Object.keys(vocab.setups)[0];
  const [setup, setSetup] = useState(firstSetup);
  const [setupParams, setSetupParams] = useState(startParams(vocab.setups[firstSetup]));
  const [filters, setFilters] = useState({}); // block -> params, in the order added
  const [side, setSide] = useState('long');
  const [stopKind, setStopKind] = useState('atr');
  const [atr, setAtr] = useState(vocab.exits.stop.atr_multiple.min);
  const [target, setTarget] = useState(vocab.exits.target.r_multiple.min);
  const [maxHold, setMaxHold] = useState(''); // swing only, required
  const [trail, setTrail] = useState(''); // swing only, optional
  const [name, setName] = useState('');
  const [thesis, setThesis] = useState('');
  const [preview, setPreview] = useState({ text: '…' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const spec = {
    ...(swing && { horizon: 'swing' }),
    setup: { [setup]: clean(setupParams) },
    filters: Object.fromEntries(Object.entries(filters).map(([b, p]) => [b, clean(p)])),
    side: swing ? 'long' : side,
    stop: stopKind === 'atr' ? { atr_multiple: Number(atr) } : swing ? { swing_low: true } : { setup_bar: true },
    target: { r_multiple: Number(target) },
    ...(swing && maxHold !== '' && { max_hold_days: { days: Number(maxHold) } }),
    ...(swing && trail !== '' && { trail_atr: { multiple: Number(trail) } }),
  };
  const specKey = JSON.stringify(spec);

  useEffect(() => {
    let stale = false;
    const timer = setTimeout(() => {
      api.post(endpoints.describeStrategy, { spec: JSON.parse(specKey) })
        .then((res) => !stale && setPreview({ text: res.data.description }))
        .catch((err) => !stale && setPreview({ text: err?.response?.data?.detail || 'Could not check this.', bad: true }));
    }, 400);
    return () => { stale = true; clearTimeout(timer); };
  }, [specKey]);

  const pickSetup = (next) => { setSetup(next); setSetupParams(startParams(vocab.setups[next])); };
  const addFilter = (block) => block && setFilters((f) => ({ ...f, [block]: startParams(vocab.filters[block]) }));
  const dropFilter = (block) => setFilters((f) => Object.fromEntries(Object.entries(f).filter(([b]) => b !== block)));
  const free = Object.keys(vocab.filters).filter((b) => !(b in filters));

  const submit = (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api.post(endpoints.builtStrategies, { name: name.trim(), thesis: thesis.trim(), spec: JSON.parse(specKey) })
      .then(() => onSubmitted())
      .catch((err) => setError(err?.response?.data?.detail || 'Could not submit.'))
      .finally(() => setBusy(false));
  };

  return (
    <form onSubmit={submit} className="space-y-1 mb-3">
      <Row label="Setup">
        <select value={setup} onChange={(e) => pickSetup(e.target.value)} aria-label="Setup" className={FIELD}>
          {Object.keys(vocab.setups).map((b) => <option key={b} value={b}>{label(b)}</option>)}
        </select>
      </Row>
      <Params block={vocab.setups[setup]} params={setupParams} onChange={setSetupParams} />

      <Row label={`Filters (up to ${MAX_FILTERS})`}>
        {Object.keys(filters).length < MAX_FILTERS && free.length > 0 && (
          <select value="" onChange={(e) => addFilter(e.target.value)} aria-label="Add a filter" className={FIELD}>
            <option value="">Add…</option>
            {free.map((b) => <option key={b} value={b}>{label(b)}</option>)}
          </select>
        )}
      </Row>
      {Object.entries(filters).map(([block, params]) => (
        <div key={block} className="pl-3 border-l border-[var(--rule-strong)]">
          <div className="flex items-center justify-between pt-2">
            <span className="field-label">{label(block)}</span>
            <button type="button" onClick={() => dropFilter(block)} className="text-xs underline min-h-11 sm:min-h-8 px-2">Remove</button>
          </div>
          <Params block={vocab.filters[block]} params={params} onChange={(p) => setFilters((f) => ({ ...f, [block]: p }))} />
        </div>
      ))}

      {!swing && <Row label="Side">
        <span className="inline-flex" role="radiogroup" aria-label="Side">
          {[['long', 'Long'], ['short', 'Short']].map(([key, text]) => (
            <button key={key} type="button" role="radio" aria-checked={side === key} onClick={() => setSide(key)}
                    className={cn('h-11 sm:h-8 px-4 text-xs border border-[var(--rule-strong)] -ml-px first:ml-0',
                      side === key && 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]')}>
              {text}
            </button>
          ))}
        </span>
      </Row>}

      <Row label="Stop">
        <span className="flex flex-wrap items-center justify-end gap-2">
          <span className="inline-flex" role="radiogroup" aria-label="Stop">
            {[['atr', 'ATR × n'], swing ? ['low', 'Swing low'] : ['bar', 'Setup bar']].map(([key, text]) => (
              <button key={key} type="button" role="radio" aria-checked={stopKind === key} onClick={() => setStopKind(key)}
                      className={cn('h-11 sm:h-8 px-3 text-xs border border-[var(--rule-strong)] -ml-px first:ml-0',
                        stopKind === key && 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]')}>
                {text}
              </button>
            ))}
          </span>
          {stopKind === 'atr' && <Param name="atr multiple" spec={vocab.exits.stop.atr_multiple} value={atr} onChange={setAtr} />}
        </span>
      </Row>
      <Row label="Target" hint="In multiples of the risk (R).">
        <Param name="r multiple" spec={vocab.exits.target.r_multiple} value={target} onChange={setTarget} />
      </Row>

      {swing && (
        <>
          <Row label="Max hold (days)" hint="Sold at the close after this many days if neither stop nor target hit.">
            <Param name="max hold days" spec={vocab.exits.max_hold_days.days} value={maxHold} onChange={setMaxHold} required />
          </Row>
          <Row label="Trailing stop (× ATR)" hint="Optional. Leave empty for none.">
            <Param name="trailing stop atr" spec={vocab.exits.trail_atr.multiple} value={trail} onChange={setTrail} />
          </Row>
        </>
      )}

      <Row label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} required aria-label="Name"
               className={cn(FIELD, 'w-44 max-w-full')} />
      </Row>
      <Row label="Thesis">
        <input value={thesis} onChange={(e) => setThesis(e.target.value)} maxLength={200} aria-label="Thesis"
               className={cn(FIELD, 'w-44 max-w-full')} />
      </Row>

      <p className={cn('text-sm py-2', preview.bad && 'text-[var(--loss)]')} aria-live="polite">{preview.text}</p>
      {error && <p className="text-sm text-[var(--loss)]" role="alert">{error}</p>}
      <button type="submit" disabled={busy || !name.trim() || preview.bad}
              className="h-11 sm:h-9 px-4 text-xs bg-[var(--ink)] text-[var(--paper)] disabled:opacity-40">
        Test it
      </button>
    </form>
  );
};

/** Horizon first; switching remounts the form so the spec starts over. */
const NewStrategySheet = ({ vocab, onSubmitted }) => {
  const [horizon, setHorizon] = useState('intraday');
  return (
    <div>
      <Row label="Horizon">
        <span className="inline-flex" role="radiogroup" aria-label="Horizon">
          {[['intraday', 'Intraday'], ['swing', 'Swing']].map(([key, text]) => (
            <button key={key} type="button" role="radio" aria-checked={horizon === key} onClick={() => setHorizon(key)}
                    className={cn('h-11 sm:h-8 px-4 text-xs border border-[var(--rule-strong)] -ml-px first:ml-0',
                      horizon === key && 'bg-[var(--ink)] text-[var(--paper)] border-[var(--ink)]')}>
              {text}
            </button>
          ))}
        </span>
      </Row>
      <HorizonForm key={horizon} horizon={horizon} vocab={vocab[horizon]} onSubmitted={onSubmitted} />
    </div>
  );
};

export default NewStrategySheet;
