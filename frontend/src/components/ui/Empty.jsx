import React from 'react';

/** What this section is and the one action that fills it. */
const Empty = ({ title, body, action }) => (
  <div className="rounded-[16px] border border-dashed border-[var(--border)] px-4 py-8 text-center">
    <p className="text-[15px] font-semibold text-[var(--text)]">{title}</p>
    {body && <p className="mt-1 text-[14px] text-[var(--text-muted)]">{body}</p>}
    {action && <div className="mt-3 flex justify-center">{action}</div>}
  </div>
);

export default Empty;
