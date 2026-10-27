import React, { useEffect, useState } from 'react';
import ListRow from '../ui/ListRow';
import Group from './Group';
import api, { endpoints } from '../../utils/api';
import {
  strategiesState, runsState, forwardState, newsAccuracyState, handbookState, backlogState, betaState,
} from '../../utils/lab';

const get = (url, config) => api.get(url, config).then((r) => r.data).catch(() => undefined);

/** Admin only: frozen and experimental features, grouped, one state line each. */
const Lab = () => {
  const [d, setD] = useState({});

  useEffect(() => {
    let live = true;
    // 404 = no report built yet (null); any other failure stays undefined.
    const news = api.get(endpoints.newsAccuracy).then((r) => r.data).catch((e) => (e?.response?.status === 404 ? null : undefined));
    Promise.all([
      get(endpoints.strategyLibrary()), get(endpoints.labRuns.list, { params: { limit: 1 } }), get(endpoints.forward.scorecard),
      news, get(endpoints.system.status), get(endpoints.system.backlog), get(endpoints.journal.betaMetrics),
    ]).then(([strategies, runs, forward, newsAcc, status, backlog, beta]) => {
      if (live) setD({ strategies, runs, forward, news: newsAcc, status, backlog, beta });
    });
    return () => { live = false; };
  }, []);

  const row = (page, title, state) => <ListRow to={`/settings/lab/${page}`} title={title} right={state} privateValue={false} />;
  return (
    <div className="space-y-4">
      <Group title="Evidence">
        {row('strategies', 'Strategies', strategiesState(d.strategies))}
        {row('runs', 'Runs', runsState(d.runs))}
        {row('forward', 'Forward', forwardState(d.forward))}
        {row('news', 'News accuracy', newsAccuracyState(d.news))}
      </Group>
      <Group title="Tools">
        {row('options', 'Option chain', 'NIFTY · BANK NIFTY')}
      </Group>
      <Group title="System">
        {row('handbook', 'Handbook', handbookState(d.status))}
        {row('backlog', 'Backlog', backlogState(d.backlog))}
        {row('beta', 'Beta', betaState(d.beta))}
      </Group>
    </div>
  );
};

export default Lab;
