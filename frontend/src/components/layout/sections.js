import {
  FileText,
  Stamp,
  Wallet,
  Activity,
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
  { icon: Stamp, label: 'Decisions', short: 'Decide', path: '/suggestions', primary: true, counter: true },
  { icon: Wallet, label: 'Holdings', short: 'Book', path: '/portfolio', primary: true },
  { icon: Activity, label: 'Engine', short: 'Engine', path: '/trading', primary: true },
  { icon: NotebookPen, label: 'Journal', path: '/journal' },
  { icon: ScanLine, label: 'Scanner', path: '/scanner' },
  { icon: BookMarked, label: 'Watchlist', path: '/watchlist' },
  { icon: Network, label: 'Architecture', path: '/system' },
  { icon: Settings, label: 'Settings', short: 'More', path: '/settings', primary: true },
];
