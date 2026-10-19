import React, { useEffect, useState } from 'react';
import { secondsLeft } from '../../utils/liveConfirm';

/** "Ns left" until `until` (ms); calls onExpire once when it runs out. */
const Countdown = ({ until, onExpire, className }) => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(tick);
  }, []);
  const left = secondsLeft(until, now);
  useEffect(() => {
    if (left === 0) onExpire();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [left === 0]);
  return <span className={className} role="timer">{left}s left</span>;
};

export default Countdown;
