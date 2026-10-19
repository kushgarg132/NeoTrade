import React from 'react';
import Badge from '../ui/Badge';
import { useForward } from '../ForwardBadge';
import { badgeFor } from '../../utils/forward';

/** Proven / Unproven n/100 from the forward scorecard; nothing for non-admins or unscored names. */
const IdeaBadge = ({ badge }) => {
  const rows = useForward();
  const b = badge ? badgeFor(rows, badge.source, badge.name) : null;
  return b ? <Badge kind={b.tone === 'success' ? 'proven' : 'unproven'}>{b.text}</Badge> : null;
};

export default IdeaBadge;
