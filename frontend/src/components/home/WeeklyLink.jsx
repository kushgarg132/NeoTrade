import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { showWeekly } from '../../utils/home';

/** Sunday and Monday only: the way into last week's report. */
const WeeklyLink = () => (!showWeekly() ? null : (
  <Link to="/reports/weekly"
        className="flex items-center justify-between gap-3 min-h-11 px-4 rounded-[16px] border border-[var(--border)] bg-[var(--surface)] text-[15px] font-semibold text-[var(--accent)] active:bg-[var(--surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
    <span>Last week's report</span>
    <ChevronRight className="w-5 h-5" aria-hidden="true" />
  </Link>
));

export default WeeklyLink;
