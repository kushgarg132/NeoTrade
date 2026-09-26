/**
 * The socket pushes the whole position book, both venues together; a paper
 * page keeps only its own. Positions without a venue predate the tag and were
 * all paper.
 */
export const paperPositions = (positions = {}) =>
  Object.fromEntries(Object.entries(positions).filter(([, position]) => position?.venue !== 'live'));
