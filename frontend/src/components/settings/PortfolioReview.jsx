import React, { useEffect, useState } from 'react';
import { Sheet } from './Panel';
import api, { endpoints, getPreferences } from '../../utils/api';
import { Row, NumberField, Segmented } from './Fields';

const PortfolioSheet = ({ isAdmin }) => {
  const [prefs, setPrefs] = useState(null);
  const [draft, setDraft] = useState({});
  const [audience, setAudience] = useState(null);

  useEffect(() => {
    getPreferences()
      .then((res) => {
        setPrefs(res.data);
        setDraft({
          portfolio_max_loss_pct: res.data.portfolio_max_loss_pct,
          portfolio_max_weight_pct: res.data.portfolio_max_weight_pct,
        });
      })
      .catch(() => setPrefs(null));
    if (isAdmin) {
      api
        .get(endpoints.settings.portfolioVerdicts)
        .then((res) => setAudience(res.data.audience))
        .catch(() => setAudience(null));
    }
  }, [isAdmin]);

  if (!prefs) return null;

  const commit = (key) => {
    const value = Math.min(100, Math.max(1, Number(draft[key]) || prefs[key]));
    api
      .put(endpoints.settings.preferences, { [key]: value })
      .then((res) => setPrefs(res.data))
      .catch(() => setDraft((d) => ({ ...d, [key]: prefs[key] })));
  };

  const setVerdicts = (next) => {
    if (
      next === 'all' &&
      !window.confirm(
        'Show SELL / HOLD / ADD to every user? Giving stock verdicts to users needs SEBI Research Analyst registration.'
      )
    ) {
      return;
    }
    api
      .put(endpoints.settings.portfolioVerdicts, { audience: next })
      .then((res) => setAudience(res.data.audience))
      .catch((err) => window.alert(err?.response?.data?.detail || 'That was not saved.'));
  };

  return (
    <Sheet title="Portfolio review">
      <p className="text-[13px] text-[var(--text-muted)] pb-3 border-b border-[var(--border)]">
        Your own limits for the Portfolio page's review: a holding past either one counts against it.
      </p>
      {[
        ['portfolio_max_loss_pct', 'Loss limit, below cost', 'A holding this far under its average cost.'],
        ['portfolio_max_weight_pct', 'Size limit, of portfolio', 'A holding larger than this share of the whole.'],
      ].map(([key, label, hint]) => (
        <Row key={key} label={label} hint={hint}>
          <NumberField
            label={label}
            suffix="%"
            value={draft[key] ?? ''}
            onChange={(value) => setDraft((d) => ({ ...d, [key]: value }))}
            onCommit={() => commit(key)}
          />
        </Row>
      ))}
      {isAdmin && audience && (
        <Row
          label="Who sees verdicts"
          hint="Deployment-wide. Everyone else sees the facts with serious holdings marked Review first. Verdicts for all users need SEBI RA registration."
        >
          <Segmented
            label="Who sees verdicts"
            options={[['admin', 'Admins only'], ['all', 'All users']]}
            value={audience}
            dangerValue="all"
            onChange={(v) => v !== audience && setVerdicts(v)}
          />
        </Row>
      )}
    </Sheet>
  );
};

export default PortfolioSheet;
