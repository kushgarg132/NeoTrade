import {
  FileText,
  Stamp,
  ScanLine,
  BookMarked,
  NotebookPen,
  Network,
  Settings,
} from 'lucide-react';

/**
 * The sections of the note, shared by the desktop index and the phone's bottom
 * bar. `primary` marks the five that are thumb-reachable on a phone.
 */
export const SECTIONS = [
  { icon: FileText, label: 'Statement', short: 'Note', path: '/', primary: true },
  { icon: NotebookPen, label: 'Journal', path: '/journal', primary: true },
  { icon: BookMarked, label: 'Watchlist', short: 'Watch', path: '/watchlist', primary: true },
  { icon: ScanLine, label: 'Scanner', path: '/scanner' },
  // Everything the engine does with practice money lives under one section,
  // apart from the real-money pages above it.
  { icon: Stamp, label: 'Paper trading', short: 'Paper', path: '/paper', primary: true, counter: true, divider: true },
  { icon: Network, label: 'Architecture', path: '/system' },
  { icon: Settings, label: 'Settings', short: 'More', path: '/settings', primary: true },
];
