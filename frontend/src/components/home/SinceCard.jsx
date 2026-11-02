import React from 'react';
import Card from '../ui/Card';
import ListRow from '../ui/ListRow';
import { changeRows, sinceWord } from '../../utils/home';

/** What changed since the last trading day, so the morning needs no trip through four pages. Absent on a quiet day. */
const SinceCard = ({ changes, headline, phase }) => {
  const rows = changeRows(changes, headline, phase);
  if (!rows.length) return null;
  return (
    <Card title={`Since ${sinceWord(changes.since)}`}>
      <ul>
        {rows.map(({ id, ...row }) => <li key={id}><ListRow dense chevron={Boolean(row.to)} {...row} /></li>)}
      </ul>
    </Card>
  );
};

export default SinceCard;
