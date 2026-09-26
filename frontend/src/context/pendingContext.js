import { createContext, useContext } from 'react';

/**
 * How many paper proposals await a decision. Layout owns the number (it is
 * the one place that loads it and follows the socket), and anything inside
 * the shell -- the nav, the Paper tab's own sub-tabs -- reads it from here.
 */
export const PendingContext = createContext(0);

export const usePendingCount = () => useContext(PendingContext);
