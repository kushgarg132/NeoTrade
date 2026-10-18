import React, { useEffect, useState } from 'react';
import { ThemeContext } from './themeContext';
import { safeGet, safeSet } from '../utils/storage';

/**
 * Light is the original note; dark is its carbon copy. The scene decides the
 * default: a phone in Indian daylight during the session, so light unless the
 * operating system says otherwise.
 */
const STORAGE_KEY = 'asi_sheet';
const initialTheme = () => {
  const stored = safeGet(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

export const ThemeProvider = ({ children }) => {
  const [theme, setTheme] = useState(initialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    safeSet(STORAGE_KEY, theme);
  }, [theme]);

  return (
    <ThemeContext.Provider
      value={{ theme, setTheme, toggle: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) }}
    >
      {children}
    </ThemeContext.Provider>
  );
};
