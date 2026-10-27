import React from 'react';

const Group = ({ title, children }) => (
  <section aria-label={title}>
    <h2 className="px-1 pb-1.5 text-[13px] font-medium text-[var(--text-muted)]">{title}</h2>
    <div className="rounded-[20px] border border-[var(--border)] bg-[var(--surface)] px-4">{children}</div>
  </section>
);

export default Group;
