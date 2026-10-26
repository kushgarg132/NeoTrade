import React from 'react';
import Card from '../ui/Card';
import ListRow from '../ui/ListRow';
import { inr, pct, tone } from '../ui/format';
import { bareSymbol } from '../../utils/formatters';
import { newsWhy } from '../../utils/home';

/** "What news moved your money": the account's big moves today (pulse.news_moves, backend/portfolio/news_moves.py),
 * each with the headline before it; a tap opens the headline. Hidden when nothing moved. */
const NewsMoves = ({ moves }) => (!moves?.length ? null : (
  <Card title="What news moved your money">
    <ul>
      {moves.map((m) => (
        <li key={m.symbol}>
          <ListRow dense title={`${bareSymbol(m.symbol)} ${pct(m.move_pct / 100, { sign: true, dp: 1 })}`}
            sub={newsWhy(m)} right={inr(m.rupees, { sign: true })} rightTone={tone(m.rupees)}
            onClick={m.cause?.url ? () => window.open(m.cause.url, '_blank', 'noopener,noreferrer') : undefined} />
        </li>
      ))}
    </ul>
  </Card>
));

export default NewsMoves;
