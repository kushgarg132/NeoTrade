import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import SectionTabs from '../components/layout/SectionTabs';
import { PRACTICE_TABS } from '../components/layout/sections';
import { Sheet, Ruling, Tabs } from '../components/doc/Doc';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { recordLine, statusOf } from '../utils/library';

const STATUS = {
  'live-ready': { label: 'Can go live', variant: 'success' },
  paper: { label: 'Paper', variant: 'secondary' },
  untested: { label: 'Not backtested', variant: 'secondary' },
  paused: { label: 'Paused by learning', variant: 'destructive' },
};
const NAME = (name) => name.replace(/_/g, ' ');

/** Practice → Library: every strategy's card and its record in this account. */
const Library = () => {
  const [mode, setMode] = useState('INTRADAY');
  const [cards, setCards] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setCards(null);
    setFailed(false);
    api.get(endpoints.strategyLibrary(mode)).then((res) => setCards(res.data.strategies)).catch(() => setFailed(true));
  }, [mode]);

  return (
    <Layout>
      <div className="space-y-3 sm:space-y-4 max-w-3xl">
        <SectionTabs tabs={PRACTICE_TABS} label="Practice" />
        <Sheet title="Strategy library" meta="What each strategy is for, and how it is doing here"
               actions={<Link to="/settings" className="doc-meta normal-case underline min-h-11 inline-flex items-center">Live switches in Settings</Link>}>
          <Tabs tabs={[{ id: 'INTRADAY', label: 'Intraday' }, { id: 'LONGTERM', label: 'Long-term' }]}
                active={mode} onSelect={setMode} label="Strategy timeframe" className="static z-auto mb-2" />
          {failed ? <p className="text-sm">Couldn't load the strategy library.</p> : cards === null ? <Ruling rows={5} /> : (
            <ul className="divide-y divide-[var(--rule)]">
              {cards.map((card) => {
                const status = STATUS[statusOf(card)];
                return (
                  <li key={card.name} className="py-3 space-y-1">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <h3 className="figure-md text-sm capitalize">{NAME(card.name)}</h3>
                      <Badge variant={status.variant}>{status.label}</Badge>
                      <span className="doc-meta normal-case">
                        {card.card.style} · suits {card.card.regimes.join(', ').replace(/_/g, '-')}
                        {card.card.needs.length > 0 && ` · needs ${card.card.needs.join(', ').replace(/_/g, ' ')}`}
                      </span>
                    </div>
                    <p className="text-sm">{card.card.best_when}</p>
                    <p className="doc-meta normal-case">Avoid: {card.card.avoid_when}</p>
                    <p className="doc-meta normal-case">{recordLine(card)}</p>
                  </li>
                );
              })}
            </ul>
          )}
        </Sheet>
      </div>
    </Layout>
  );
};

export default Library;
