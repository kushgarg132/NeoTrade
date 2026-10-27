const MIN = 60000;

/** How long a round trip was (or has been) held: "3 days", "2 h", "20 min"; open trips read "Open · 5 days". */
export const holdTime = (openedAt, closedAt, now = new Date()) => {
  const ms = Math.max(0, new Date(closedAt || now) - new Date(openedAt));
  const days = Math.floor(ms / (1440 * MIN));
  const hours = Math.floor(ms / (60 * MIN));
  let text;
  if (days >= 1) text = `${days} ${days === 1 ? 'day' : 'days'}`;
  else if (hours >= 1) text = `${hours} h`;
  else text = `${Math.floor(ms / MIN)} min`;
  return closedAt ? text : `Open · ${text}`;
};
