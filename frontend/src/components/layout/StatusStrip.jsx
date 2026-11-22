import React from 'react';
import { Link } from 'react-router-dom';
import api, { endpoints } from '../../utils/api';

/** An expired-login alert goes straight to that broker's login, in this tab: iOS blocks a pop-up opened
 * after an await, and the broker's redirect lands on Settings -> Accounts, which finishes the connect.
 * If the URL cannot be built, the link's own target (Accounts) still opens. */
const openBrokerLogin = (e, a) => {
  e.preventDefault();
  api.get(endpoints.broker.loginUrl(a.login))
    .then((res) => window.location.assign(res.data.url))
    .catch(() => window.location.assign(a.to));
};

/**
 * The shell's danger line, on every page under the header (PRODUCT.md: live armed and the kill switch must
 * never be inferable only from one page). `items` is utils/home.js::alerts, most severe first; nothing renders
 * when it is empty. The kill switch is the one red strip; live armed and expired logins are amber.
 */
const StatusStrip = ({ items }) => items.length > 0 && (
  <div className="mx-auto max-w-5xl px-4 pt-3 space-y-2">
    {items.map((a) => (
      <Link key={a.id} to={a.to} role="alert" onClick={a.login ? (e) => openBrokerLogin(e, a) : undefined}
            style={{ background: `color-mix(in oklab, var(${a.danger ? '--loss' : '--warn'}) 14%, var(--surface))` }}
            className={`tap flex items-center justify-between gap-3 min-h-11 rounded-[12px] px-3 py-2 text-[14px] font-medium ${a.danger ? 'text-[var(--loss)]' : 'text-[var(--warn)]'} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]`}>
        <span>{a.text}</span>
        <span className="shrink-0 font-semibold underline">{a.action}</span>
      </Link>
    ))}
  </div>
);

export default StatusStrip;
