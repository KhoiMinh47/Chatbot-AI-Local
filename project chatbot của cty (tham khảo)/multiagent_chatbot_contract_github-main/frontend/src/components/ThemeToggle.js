'use client';

import React from 'react';
import { useTheme } from './ThemeProvider';

export default function ThemeToggle() {
  const { resolvedTheme, toggleTheme } = useTheme();
  const dark = resolvedTheme === 'dark';

  return (
    <button
      type="button"
      className="themeToggle"
      onClick={toggleTheme}
      aria-label="Toggle color theme"
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      <span className="themeToggleInner" aria-hidden="true">
        {dark ? (
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M21 12.79A9 9 0 1 1 11.21 3c-.1.58-.15 1.18-.15 1.79a9 9 0 0 0 9.94 8z" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="12" r="4.5" />
            <path d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" />
          </svg>
        )}
      </span>
      <span className="themeToggleLabel">{dark ? 'Dark' : 'Light'}</span>
    </button>
  );
}
