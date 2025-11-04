'use client';

import React, { useState, useEffect } from 'react';
import { Sun, Moon, Monitor } from 'lucide-react';

export function ThemeToggle() {
  const [mounted, setMounted] = useState(false);
  const [theme, setThemeState] = useState<'light' | 'dark' | 'system'>('light');

  useEffect(() => {
    setMounted(true);
    // Get stored theme or default to 'system'
    const storedTheme = localStorage.getItem('theme') as 'light' | 'dark' | 'system' || 'system';
    setThemeState(storedTheme);
  }, []);

  const setTheme = (newTheme: 'light' | 'dark' | 'system') => {
    setThemeState(newTheme);
    localStorage.setItem('theme', newTheme);
    
    // Update DOM directly
    const updateDOMTheme = () => {
      let effectiveTheme: 'light' | 'dark' = 'light';
      
      if (newTheme === 'dark') {
        effectiveTheme = 'dark';
      } else if (newTheme === 'system') {
        effectiveTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      }
      
      const root = document.documentElement;
      root.classList.remove('light', 'dark');
      root.classList.add(effectiveTheme);
    };
    
    updateDOMTheme();
  };

  if (!mounted) {
    return (
      <div className="w-10 h-10 rounded-lg bg-neutral-100 dark:bg-black-600 animate-pulse" />
    );
  }

  const themes = [
    { name: 'light', icon: Sun, label: 'Light' },
    { name: 'dark', icon: Moon, label: 'Dark' },
    { name: 'system', icon: Monitor, label: 'System' },
  ] as const;

  return (
    <div className="relative">
      <div className="flex items-center bg-neutral-100 dark:bg-black-600 rounded-lg p-1">
        {themes.map(({ name, icon: Icon, label }) => (
          <button
            key={name}
            onClick={() => setTheme(name)}
            className={`
              relative flex items-center justify-center w-8 h-8 rounded-md transition-all duration-200
              ${theme === name 
                ? 'bg-white dark:bg-black-500 text-neutral-900 dark:text-neutral-100 shadow-sm' 
                : 'text-neutral-600 dark:text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100'
              }
            `}
            title={label}
          >
            <Icon className="w-4 h-4" />
          </button>
        ))}
      </div>
    </div>
  );
} 