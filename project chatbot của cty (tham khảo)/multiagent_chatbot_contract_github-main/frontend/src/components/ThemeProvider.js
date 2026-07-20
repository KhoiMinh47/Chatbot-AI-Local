'use client';
/* eslint-disable react-hooks/set-state-in-effect */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

const ThemeContext = createContext({
  theme: 'system',
  resolvedTheme: 'dark',
  setTheme: () => {},
  toggleTheme: () => {},
});

function getSystemTheme() {
  if (typeof window === 'undefined') return 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  const resolved = theme === 'system' ? getSystemTheme() : theme;
  const root = document.documentElement;
  root.classList.add('theme-transitioning');
  root.setAttribute('data-theme', resolved);
  window.setTimeout(() => {
    root.classList.remove('theme-transitioning');
  }, 520);
  return resolved;
}

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState('system');
  const [resolvedTheme, setResolvedTheme] = useState('dark');

  useEffect(() => {
    const stored = localStorage.getItem('theme');
    const next = stored || 'system';
    setTheme(next);
    setResolvedTheme(applyTheme(next));
  }, []);

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      if (theme === 'system') {
        setResolvedTheme(applyTheme('system'));
      }
    };
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [theme]);

  const setThemeSafe = useCallback((next) => {
    setTheme(next);
    localStorage.setItem('theme', next);
    setResolvedTheme(applyTheme(next));
  }, []);

  const toggleTheme = useCallback(() => {
    const current = theme === 'system' ? getSystemTheme() : theme;
    setThemeSafe(current === 'dark' ? 'light' : 'dark');
  }, [setThemeSafe, theme]);

  const value = useMemo(() => ({
    theme,
    resolvedTheme,
    setTheme: setThemeSafe,
    toggleTheme,
  }), [theme, resolvedTheme, setThemeSafe, toggleTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
