import React, { useCallback } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import PageHeader from '../components/ui/PageHeader';
import Card from '../components/ui/Card';
import Empty from '../components/ui/Empty';
import Skeleton from '../components/ui/Skeleton';
import ErrorLine from '../components/ui/ErrorLine';
import Button from '../components/ui/Button';
import ExitAlerts from '../components/ideas/ExitAlerts';
import IdeaRow from '../components/ideas/IdeaRow';
import { useLoad } from '../components/ideas/useLoad';
import { useAuth } from '../context/AuthContext';
import api, { endpoints } from '../utils/api';
import { ideaFromSuggestion, ideaFromPick } from '../utils/ideas';

/** Ideas: exit alerts first, then new ideas (your suggestions, plus Picks for admins). */
const Ideas = () => {
  const isAdmin = useAuth().user?.role === 'admin';
  const exits = useLoad(useCallback(
    () => api.get(endpoints.mine.actions).then((r) => r.data.filter((a) => a.action?.type === 'ticket')), []));
  const fresh = useLoad(useCallback(async () => {
    const sug = await api.get(endpoints.suggestions.list({ status: 'PENDING' })).then((r) => r.data.map(ideaFromSuggestion));
    // Picks are admin-only; a failure there must not hide the suggestions.
    const picks = isAdmin
      ? await api.get(endpoints.picks.today).then((r) => r.data.picks.map((p) => ideaFromPick(p, r.data.setups.find((s) => s.setup === p.setup)))).catch(() => [])
      : [];
    return [...sug, ...picks];
  }, [isAdmin]));

  return (
    <Layout>
      <PageHeader title="Ideas" right={<Link to="/ideas/history" className="inline-flex items-center min-h-11 px-2 text-[14px] font-semibold text-[var(--accent)]">History</Link>} />
      <div className="space-y-4">
        {exits.loading ? <Skeleton rows={2} />
          : exits.error ? <ErrorLine message="Could not load exit alerts." onRetry={exits.reload} />
          : exits.data.length > 0 && <ExitAlerts actions={exits.data} onChanged={() => { exits.reload(); fresh.reload(); }} />}

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
