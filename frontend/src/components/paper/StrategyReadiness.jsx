import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Ruling } from '../doc/Doc';
import { Row } from '../settings/Fields';
import api, { endpoints } from '../../utils/api';
import { readiness } from '../../utils/promotion';

/**
 * Is it working: per strategy, whether it has earned real money yet and,
 * if not, what it still needs. Each fetch fails on its own.
 */
const StrategyReadiness = () => {
  const [names, setNames] = useState(null);
  const [promotion, setPromotion] = useState(null);
  const [live, setLive] = useState([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    api
      .get(endpoints.settings.strategies)
      .then((res) => setNames(res.data))
      .catch(() => setError(true));
    api
      .get(endpoints.settings.promotion)
      .then((res) => setPromotion(Object.fromEntries(res.data.map((row) => [row.name, row]))))
      .catch(() => setError(true));
    api
      .get(endpoints.settings.preferences)
      .then((res) => setLive(res.data.live_strategies || []))
      .catch(() => setLive([]));
  }, []);

  return (
    <Sheet
      title="Is it working"
      meta="Paper record per strategy"
      actions={
        <Link to="/ai/practice/settings" className="field-label text-[var(--stamp)] hover:underline">
          Change in Settings ›
        </Link>
      }
    >
      {error ? (
        <p className="doc-meta normal-case">Couldn’t load strategy readiness.</p>
      ) : !names || !promotion ? (
        <Ruling rows={3} />
      ) : (
        names.map((name) => (
          <Row key={name} label={name} hint={readiness(promotion[name], live.includes(name))} />
        ))
      )}
    </Sheet>
  );
};

export default StrategyReadiness;
