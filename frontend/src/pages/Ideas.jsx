import React, { useCallback } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Button from '../components/ui/Button';
import HoldingActions from '../components/ideas/HoldingActions';
import IdeaRow from '../components/ideas/IdeaRow';
import { useLoad } from '../components/ideas/useLoad';
import { useAuth } from '../context/AuthContext';
import api, { endpoints } from '../utils/api';
import { fetchIdeas } from '../hooks/useNeedCount';

/** Ideas: what needs you on your holdings first, then new ideas (your suggestions, plus Picks for admins). */
const Ideas = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const acts = useLoad(useCallback(() => api.get(endpoints.mine.actions).then((r) => r.data), []));
  const fresh = useLoad(useCallback(() => fetchIdeas(isAdmin), [isAdmin]));

  return (
    <Layout>
      <PageHeader title="Ideas" right={<Link to="/ideas/history" className="inline-flex items-center min-h-11 px-2 text-[14px] font-semibold text-[var(--accent)]">History</Link>} />
      <div className="space-y-4">
        {acts.loading ? <Skeleton rows={2} />
          : acts.error ? <ErrorLine message="Could not load your holdings alerts." onRetry={acts.reload} />
          : <HoldingActions actions={acts.data} onChanged={() => { acts.reload(); fresh.reload(); }} />}

        <Card title="New ideas">
          {fresh.loading ? <Skeleton rows={4} />
            : fresh.error ? <ErrorLine message="Could not load ideas." onRetry={fresh.reload} />
            : fresh.data.length === 0 ? (
              <Empty title="No new ideas" body="Ideas appear after the daily scan. Past ones are in History."
                action={<Link to="/ideas/history"><Button variant="secondary">Open history</Button></Link>} />
            ) : fresh.data.map((i) => <IdeaRow key={i.id} idea={i} />)}
        </Card>
      </div>
    </Layout>
  );
};

export default Ideas;
