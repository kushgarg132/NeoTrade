import { useEffect, useState } from 'react';
import api, { endpoints } from '../utils/api';
import { FALLBACK_SCHEDULE, clockTimes } from '../utils/schedule';

let cached = null;

/** Job times from the backend constants: `t` = 12-hour strings ("4:00 PM"), `raw` = the payload. */
export default function useSchedule() {
  const [raw, setRaw] = useState(cached || FALLBACK_SCHEDULE);
  useEffect(() => {
    if (cached) return undefined;
    let live = true;
    api.get(endpoints.system.schedule)
      .then((res) => { cached = res.data; if (live) setRaw(res.data); })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  return { t: clockTimes(raw), raw };
}
