import React, { useEffect, useState } from 'react';
import { ThemeContext } from './themeContext';
import { safeGet, safeSet } from '../utils/storage';

/** Dark is the default; a stored choice wins. */
const STORAGE_KEY = 'asi_sheet';
const initialTheme = () => {
  const stored = safeGet(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return 'dark';
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
