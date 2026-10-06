import React from 'react';
import { Sheet, Statement, Row, Cell } from '../doc/Doc';
import { formatDateTime, formatQuantity, formatTimeAgo } from '../../utils/formatters';

/**
 * The handbook's live panels, one per `<!-- live:x -->` marker, fed by
 * GET /system/status. A block the backend could not build says why.
 */

const TITLES = { deploy: 'Deployed now', jobs: 'Jobs now', news: 'News now', data: 'Data now', ai: 'AI now' };
const FRONTEND_SHA = import.meta.env.VITE_GIT_SHA || '';

const sha = (value) => (value ? value.slice(0, 7) : 'unknown (built without GIT_SHA)');
const run = (record) => (record ? `${formatTimeAgo(record.at)} · ${record.ok ? 'ok' : 'failed'}` : 'never recorded');
const mb = (bytes) => (bytes == null ? '—' : `${(bytes / 1048576).toFixed(1)} MB`);

const summary = (note) => {
  try {
    return Object.entries(JSON.parse(note)).map(([key, value]) => `${key.replace(/_/g, ' ')} ${value}`).join(' · ');
  } catch {
    return note;
  }
};

const ROWS = {
  deploy: (b) => [
    ['Backend commit', sha(b.backend_sha)],
    ['Backend started', formatTimeAgo(b.backend_started_at)],
    ['Frontend commit', sha(FRONTEND_SHA)],
  ],
  jobs: (b) => [
    ['Daily pass', run(b.daily_pass)],
    ...(b.daily_pass?.note ? [['Last pass did', summary(b.daily_pass.note)]] : []),
    ['Next daily pass', formatDateTime(b.next_daily_pass_at)],
    ...Object.entries(b.loops).map(([name, record]) => [name.replace(/_/g, ' '), run(record)]),
    ...Object.entries(b.ingest).map(([name, age]) => [`ingest ${name.replace(/_/g, ' ')}`, `${age}s ago`]),
    ['API workers alive', b.workers_alive],
  ],
  news: (b) => [
    ...Object.entries(b.last_24h).map(([status, n]) => [`${status.toLowerCase()} · 24h`, n]),
    ['Newest item', formatTimeAgo(b.newest_at) || '—'],
    ['Waiting to be scored', b.unscored],
    ['Last material', b.last_material ? `${b.last_material.title} · ${formatTimeAgo(b.last_material.at)}` : '—'],
  ],
  data: (b) => [
    ...Object.entries(b.collections).map(([name, n]) => [name, formatQuantity(n)]),
    ['Atlas data', b.atlas.error ? b.atlas.error : `${mb(b.atlas.data_bytes)} (${mb(b.atlas.storage_bytes)} on disk)`],
    ['Redis', b.redis.error ? b.redis.error : `${formatQuantity(b.redis.keys)} keys · ${b.redis.memory}`],
    ...Object.entries(b.broker_sessions).map(([broker, n]) => [`${broker.replace(/_/g, ' ')} sessions`, n]),
    ['Instruments', `${formatQuantity(b.instruments.count)}${b.instruments.last_added_at ? ` · last added ${formatTimeAgo(b.instruments.last_added_at)}` : ''}`],
  ],
  ai: (b) => [
    ['News scoring calls today', `${b.news_calls_today} of ${b.news_calls_limit}`],
    ['Plan calls today', `${b.plan_calls_today} of ${b.plan_calls_limit}`],
    ['Gateway this month', b.usage.error ? b.usage.error : `${formatQuantity(b.usage.tokens.total)} tokens · $${Number(b.usage.cost.used_usd || 0).toFixed(2)}`],
  ],
};

const LivePanel = ({ name, status }) => {
  const block = status?.[name] || (status?.error ? { error: status.error } : null);
  let body;
  if (!status) body = <p className="doc-meta normal-case">Reading…</p>;
  else if (!block || block.error) body = <p className="text-sm">Unavailable: {block?.error || 'no data'}</p>;
  else {
    body = (
      <Statement inline columns={[{ key: 'item', label: 'Item' }, { key: 'value', label: 'Now', align: 'right' }]}>
        {ROWS[name](block).map(([label, value]) => (
          <Row key={label}>
            <Cell className="text-[var(--ink-soft)]">{label}</Cell>
            <Cell align="right" mono className="whitespace-normal [overflow-wrap:anywhere]">{value}</Cell>
          </Row>
        ))}
      </Statement>
    );
  }
  return (
    <Sheet title={TITLES[name]} meta={status ? `as of ${formatTimeAgo(status.as_of)}` : 'live'} className="my-3">
      {body}
    </Sheet>
  );
};
export default LivePanel;
