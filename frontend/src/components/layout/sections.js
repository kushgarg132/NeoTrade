import {
  FileText,
  Stamp,
  ScanLine,
  Layers,
  BookMarked,
  NotebookPen,
  PieChart,
  Network,
  Settings,
} from 'lucide-react';

/**
 * The sections of the note, shared by the desktop index and the phone's bottom
 * bar. `primary` marks the five that are thumb-reachable on a phone; the rest are
 * listed at the top of Settings, which the phone labels More.
 */
export const SECTIONS = [
  { icon: FileText, label: 'Statement', short: 'Note', path: '/', primary: true },
  { icon: NotebookPen, label: 'Journal', path: '/journal', primary: true },
  { icon: PieChart, label: 'Portfolio', path: '/portfolio', primary: true },
  { icon: BookMarked, label: 'Watchlist', short: 'Watch', path: '/watchlist' },
  { icon: ScanLine, label: 'Scanner', path: '/scanner' },
  { icon: Layers, label: 'Option chain', path: '/options' },
  // Everything the engine does with practice money lives under one section,
  // apart from the real-money pages above it.
  { icon: Stamp, label: 'Paper trading', short: 'Paper', path: '/paper', primary: true, counter: true, divider: true },
  { icon: Network, label: 'Architecture', path: '/system' },
  { icon: Settings, label: 'Settings', short: 'More', path: '/settings', primary: true },
];
