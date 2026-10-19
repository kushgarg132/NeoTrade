import React from 'react';
import Card from '../ui/Card';
import Empty from '../ui/Empty';
import ListRow from '../ui/ListRow';
import { inr } from '../ui/format';
import { formatCurrency } from '../../utils/formatters';
import { day } from './common';

const name = (e) => String(e.label || e.type || e.kind || 'Event').replace(/_/g, ' ');

/** What is coming up, dividends you received, and the AI's notable events once that has run. */
const EventsTab = ({ mine, ai }) => {
  const upcoming = mine?.events || [];
  const divs = mine?.dividends || [];
  const notable = ai?.data?.events || [];
  if (!upcoming.length && !divs.length && !notable.length)
    return <Empty title="Nothing scheduled" body="Results, dividends and board meetings show here when they are announced." />;
  return (
    <div className="space-y-3">
      {upcoming.length > 0 && (
        <Card title="Coming up">
          {upcoming.map((e, i) => (
            <ListRow key={i} title={name(e)} sub={[day(e.date), e.amount != null && `${formatCurrency(e.amount)} a share`].filter(Boolean).join(' · ')} chevron={false} />
          ))}
        </Card>
      )}
      {notable.length > 0 && (
        <Card title="Notable">
          {notable.map((e, i) => (
            <ListRow key={i} title={e.event_type} sub={[e.date && day(e.date), e.description].filter(Boolean).join(' · ')} chevron={false} />
          ))}
        </Card>
      )}
      {divs.length > 0 && (
        <Card title="Dividends you received">
          {divs.map((d, i) => (
            <ListRow key={i} title={day(d.date)} right={inr(d.total ?? d.amount)} chevron={false} />
          ))}
        </Card>
      )}
    </div>
  );
};

export default EventsTab;
