import React, { useState } from 'react';
import { Building2, BookmarkPlus, Check, Loader2 } from 'lucide-react';
import api, { endpoints } from '../utils/api';
import { Badge } from './common/Badge';
import { Button } from './common/Button';
import { Sheet, Empty } from './doc/Doc';
import {
  formatCurrency,
  formatSignedPercent,
} from '../utils/formatters';
import { cn } from '../utils/cn';

import TradingChart from './stock/TradingChart';
import SentimentPanel from './analysis/SentimentPanel';
import StockFlags from './analysis/StockFlags';
import TradingLevels from './analysis/TradingLevels';
import Fundamentals from './analysis/Fundamentals';
import NewsFeed from './analysis/NewsFeed';
import EventsList from './analysis/EventsList';

/** Return windows the snapshot carries (backend/research/quick.py). */
const RETURNS = [
  ['1w', '1W'],
  ['1m', '1M'],
  ['3m', '3M'],
  ['6m', '6M'],
  ['1y', '1Y'],
];

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'ai', label: 'AI Analysis' },
];

/**
 * A scrip enquiry, printed as a section of the note: the quotation at the
 * head, then a tab split -- Overview is the quote, fundamentals and
 * technicals (`quick`, no LLM call, renders as soon as the click lands), AI
 * Analysis is the news/sentiment/thesis report (`ai`), which the parent only
 * starts fetching the first time this tab is opened. Splitting them is the
 * whole point: the AI pipeline makes several sequential LLM calls and used
 * to sit in front of everything else a stock click needed to show.
 */
const AnalysisCard = ({ quick, ai, aiLoading, aiError, aiRequested, onOpenAiTab }) => {
  const [tab, setTab] = useState('overview');
  const [watched, setWatched] = useState(false);
  const [watchError, setWatchError] = useState(null);
  const [failedLogoUrl, setFailedLogoUrl] = useState(null);

  if (!quick) return null;

  const company = quick.company_info;
  const technicals = quick.technical_analysis;
  const change = company?.day_change_percent || 0;
  const currency = company?.currency || 'INR';

  const openTab = (id) => {
    setTab(id);
    if (id === 'ai' && !aiRequested) onOpenAiTab();
  };

  const addToWatchlist = async () => {
    setWatchError(null);
    try {
      await api.post(endpoints.watchlist.add(company?.symbol));
      setWatched(true);
    } catch (err) {
      setWatchError(err?.response?.data?.detail || 'Could not add to the watchlist');
    }
  };


  return (
    <div className="space-y-4">
      <Sheet bodyClassName="p-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-11 h-11 shrink-0 border border-[var(--rule-strong)] bg-[var(--paper-sunk)] flex items-center justify-center overflow-hidden">
              {company?.logo_url && company.logo_url !== failedLogoUrl ? (
                <img
                  src={company.logo_url}
                  alt=""
                  onError={() => setFailedLogoUrl(company.logo_url)}
                  className="w-full h-full object-contain p-1"
                />
              ) : (
                <Building2 className="w-5 h-5 text-[var(--ink-faint)]" aria-hidden="true" />
              )}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="figure-md text-xl">{company?.symbol}</h2>
                {company?.sector && <Badge variant="outline">{company.sector}</Badge>}
                {company?.industry && <Badge variant="outline">{company.industry}</Badge>}
              </div>
              <p className="text-sm text-[var(--ink-soft)] truncate">{company?.name}</p>
            </div>
          </div>

          <div className="text-right">
            <p className="figure-md text-2xl">
              {formatCurrency(company?.current_price, currency)}
            </p>
            <p className={cn('figure-md text-sm', change >= 0 ? 'text-up' : 'text-down')}>
              {formatSignedPercent(change)}{' '}
              <span className="text-[var(--ink-faint)]">today</span>
            </p>
            {company?.previous_close != null && (
              <p className="doc-meta normal-case">prev close {formatCurrency(company.previous_close, currency)}</p>
            )}
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-[var(--rule)] flex items-center justify-between gap-3">
          <span className="doc-meta">Enquiry</span>
          <Button variant="secondary" size="sm" onClick={addToWatchlist} disabled={watched}>
            {watched ? <Check className="w-3.5 h-3.5" /> : <BookmarkPlus className="w-3.5 h-3.5" />}
            {watched ? 'On watchlist' : 'Watch'}
          </Button>
        </div>
        {watchError && <p className="mt-2 text-sm text-[var(--loss)]">{watchError}</p>}
      </Sheet>

      <div className="flex border-b border-[var(--rule-strong)]" role="tablist" aria-label="Enquiry">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => openTab(item.id)}
            className={cn(
              'flex-1 sm:flex-none px-4 py-3 font-[family-name:var(--font-narrow)] text-xs font-semibold uppercase tracking-[0.11em] border-b-2 -mb-px transition-colors',
              tab === item.id
                ? 'border-[var(--stamp)] text-[var(--ink)]'
                : 'border-transparent text-[var(--ink-soft)] hover:text-[var(--ink)]'
            )}
          >
            {item.label}
            {item.id === 'ai' && aiLoading && (
              <Loader2 className="inline w-3 h-3 ml-1.5 animate-spin align-[-1px]" />
            )}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="space-y-4">
          <StockFlags flags={quick.flags} />
          <Sheet title="Price">
            <TradingChart data={quick.price_data} technicals={technicals} currency={currency} />
            <dl className="mt-3 grid grid-cols-5 border-t border-[var(--rule)] pt-3" aria-label="Returns">
              {RETURNS.map(([key, label]) => {
                const value = technicals?.returns?.[key];
                return (
                  <div key={key} className="text-center">
                    <dt className="field-label">{label}</dt>
                    <dd className={cn('figure-md text-xs sm:text-sm', value > 0 && 'text-up', value < 0 && 'text-down')}>
                      {formatSignedPercent(value)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </Sheet>
          <TradingLevels t={technicals} currency={currency} />
          <Fundamentals company={company} currency={currency} />
        </div>
      )}

      {tab === 'ai' && (
        <div className="space-y-4">
          {aiLoading && (
            <Sheet>
              <div className="flex items-center gap-3 py-6 justify-center text-[var(--ink-soft)]">
                <Loader2 className="w-4 h-4 animate-spin text-[var(--stamp)]" />
                <span className="text-sm">Reading news and sentiment…</span>
              </div>
            </Sheet>
          )}

          {aiError && !aiLoading && (
            <Sheet>
              <Empty
                title="Could not load the AI analysis"
                detail={aiError}
                action={
                  <Button variant="secondary" size="sm" onClick={onOpenAiTab}>
                    Retry
                  </Button>
                }
              />
            </Sheet>
          )}

          {ai && !aiLoading && !aiError && (
            <>
              <SentimentPanel
                score={ai.sentiment?.score ?? ai.sentiment_score}
                summary={ai.analyst_summary}
                sentiment={ai.sentiment}
                thesis={ai.thesis}
              />
              <div className="grid gap-4 lg:grid-cols-2">
                <NewsFeed articles={ai.news_articles} />
                <EventsList events={ai.events} />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default AnalysisCard;
