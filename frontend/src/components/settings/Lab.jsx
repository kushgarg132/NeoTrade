import React from 'react';
import ListRow from '../ui/ListRow';
import Card from '../ui/Card';
import BetaSheet from './Beta';

const LINKS = [
  ['strategies', 'Strategies', 'the strategy library and paper / live switches'],
  ['options', 'Options', 'the option chain'],
  ['runs', 'Runs', 'backtest runs'],
  ['forward', 'Forward', 'forward tests'],
  ['handbook', 'Handbook', 'how every part works, with live status'],
  ['backlog', 'Backlog', 'what comes next'],
];

/** Admin only: frozen and experimental features, and beta metrics. */
const Lab = () => (
  <div className="space-y-3">
    <Card title="Lab">
      {LINKS.map(([page, title, sub]) => <ListRow key={page} to={`/settings/lab/${page}`} title={title} sub={sub} />)}
    </Card>
    <BetaSheet />
  </div>
);

export default Lab;
