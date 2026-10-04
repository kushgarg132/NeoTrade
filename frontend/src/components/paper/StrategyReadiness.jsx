import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sheet, Ruling } from '../doc/Doc';
import StrategyRow, { GO_LIVE_RULE, StrategyFold } from './StrategyRow';
import api, { endpoints } from '../../utils/api';
import { useTopic } from '../../hooks/useStream';
import { readiness, shortStatus } from '../../utils/promotion';

/**
 * Is it working: per strategy, whether it has earned real money yet and,
 * if not, what it still needs. The names and the readiness load apart: with
 * readiness down, the strategies are still listed. Refreshed as trades close.
 * `liveStrategies` comes from the overview's one preferences fetch.
 */
const StrategyReadiness = ({ liveStrategies }) => {
  const [names, setNames] = useState(null);
  const [namesError, setNamesError] = useState(false);
  const [promotion, setPromotion] = useState(null);
  const [promotionError, setPromotionError] = useState(false);
  const [open, setOpen] = useState(null);
  const [listOpen, setListOpen] = useState(false);

  const loadPromotion = () =>
    api
      .get(endpoints.settings.promotion)
      .then((res) => {
        setPromotion(Object.fromEntries(res.data.map((row) => [row.name, row])));
        setPromotionError(false);
      })
      .catch(() => setPromotionError(true));

  useEffect(() => {
    api
      .get(endpoints.settings.strategies)
      .then((res) => setNames(res.data))
      .catch(() => setNamesError(true));
    loadPromotion();
  }, []);

  useTopic('trades', loadPromotion);

  const detail = (name) => {
    if (promotion) return readiness(promotion[name], liveStrategies.includes(name));
    return promotionError ? undefined : '…';
  };
  const status = (name) => (promotion ? shortStatus(promotion[name]) : promotionError ? '' : '…');

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
      {promotionError && !promotion && (
        <p className="doc-meta normal-case pb-2">Couldn’t load strategy readiness.</p>
      )}
      {namesError ? (
        <p className="doc-meta normal-case">Couldn’t load the strategies.</p>
      ) : !names ? (
        <Ruling rows={3} />
      ) : (
        <>
          <StrategyFold
            count={names.length}
            ready={promotion ? names.filter((n) => promotion[n]?.eligible).length : 0}
            open={listOpen}
            onToggle={() => setListOpen((value) => !value)}
          />
          {listOpen && <p className="doc-meta normal-case py-2 border-y border-[var(--rule)]">{GO_LIVE_RULE}</p>}
          {listOpen && names.map((name) => (
            <StrategyRow
              key={name}
              name={name}
              status={status(name)}
              detail={detail(name)}
              open={open === name}
              onToggle={() => setOpen((current) => (current === name ? null : name))}
            />
          ))}
        </>
      )}
    </Sheet>
  );
};

export default StrategyReadiness;
