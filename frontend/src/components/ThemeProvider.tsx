import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';

export type ThemeName = 'midnight' | 'cyberpunk' | 'arctic';

export interface CustomPalette {
  name: string;
  vars: Record<string, string>;
}

interface ThemeContextType {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
  animationSpeed: 'normal' | 'reduced';
  setAnimationSpeed: (s: 'normal' | 'reduced') => void;
  showIntro: boolean;
  setShowIntro: (b: boolean) => void;
  // Custom palette (AI-generated "vibe")
  customOverrides: Record<string, string> | null;
  setCustomOverrides: (vars: Record<string, string> | null) => void;
  clearCustomOverrides: () => void;
  savedPalettes: CustomPalette[];
  savePalette: (name: string, vars: Record<string, string>) => void;
  deletePalette: (name: string) => void;
  applySavedPalette: (name: string) => void;
}

const ThemeContext = createContext<ThemeContextType>({
  theme: 'midnight',
  setTheme: () => {},
  animationSpeed: 'normal',
  setAnimationSpeed: () => {},
  showIntro: true,
  setShowIntro: () => {},
  customOverrides: null,
  setCustomOverrides: () => {},
  clearCustomOverrides: () => {},
  savedPalettes: [],
  savePalette: () => {},
  deletePalette: () => {},
  applySavedPalette: () => {},
});

export const useTheme = () => useContext(ThemeContext);

const THEMES: Record<ThemeName, Record<string, string>> = {
  midnight: {
    '--bg-primary': '#0a0a0f',
    '--bg-secondary': 'rgba(20, 20, 25, 0.7)',
    '--bg-tertiary': 'rgba(30, 30, 40, 0.5)',
    '--text-primary': '#f8f8f2',
    '--text-secondary': '#a0a0b0',
    '--text-tertiary': '#606070',
    '--accent-primary': '#8b5cf6',
    '--accent-secondary': '#ec4899',
    '--accent-tertiary': '#3b82f6',
    '--border-color': 'rgba(255, 255, 255, 0.08)',
    '--border-hover': 'rgba(255, 255, 255, 0.15)',
  },
  cyberpunk: {
    '--bg-primary': '#050505',
    '--bg-secondary': 'rgba(8, 18, 25, 0.85)',
    '--bg-tertiary': 'rgba(10, 25, 35, 0.6)',
    '--text-primary': '#e0f7fa',
    '--text-secondary': '#80cbc4',
    '--text-tertiary': '#4db6ac',
    '--accent-primary': '#00f0ff',
    '--accent-secondary': '#ff2d7c',
    '--accent-tertiary': '#39ff14',
    '--border-color': 'rgba(0, 240, 255, 0.12)',
    '--border-hover': 'rgba(0, 240, 255, 0.30)',
  },
  arctic: {
    '--bg-primary': '#eef2f7',
    '--bg-secondary': 'rgba(255, 255, 255, 0.88)',
    '--bg-tertiary': 'rgba(220, 230, 245, 0.65)',
    '--text-primary': '#0f172a',
    '--text-secondary': '#334155',
    '--text-tertiary': '#94a3b8',
    '--accent-primary': '#4f8af7',
    '--accent-secondary': '#e855b3',
    '--accent-tertiary': '#2563eb',
    '--border-color': 'rgba(30, 60, 120, 0.10)',
    '--border-hover': 'rgba(30, 60, 120, 0.20)',
  },
};

export const ThemeProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<ThemeName>(() => {
    const saved = localStorage.getItem('pa-theme') as ThemeName;
    return (THEMES[saved] ? saved : 'midnight');
  });
  const [animationSpeed, setAnimSpeed] = useState<'normal' | 'reduced'>(() => {
    return (localStorage.getItem('pa-anim-speed') as 'normal' | 'reduced') || 'normal';
  });
  const [showIntro, setShowIntroState] = useState(() => {
    return localStorage.getItem('pa-show-intro') !== 'false';
  });

  // Custom palette overrides (session-only unless saved)
  const [customOverrides, setCustomOverridesState] = useState<Record<string, string> | null>(null);

  // Saved palettes from localStorage
  const [savedPalettes, setSavedPalettes] = useState<CustomPalette[]>(() => {
    try {
      const raw = localStorage.getItem('pa-saved-palettes');
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  });

  const setTheme = (t: ThemeName) => {
    setThemeState(t);
    localStorage.setItem('pa-theme', t);
  };

  const setAnimationSpeed = (s: 'normal' | 'reduced') => {
    setAnimSpeed(s);
    localStorage.setItem('pa-anim-speed', s);
  };

  const setShowIntro = (b: boolean) => {
    setShowIntroState(b);
    localStorage.setItem('pa-show-intro', String(b));
  };

  const setCustomOverrides = useCallback((vars: Record<string, string> | null) => {
    setCustomOverridesState(vars);
  }, []);

  const clearCustomOverrides = useCallback(() => {
    setCustomOverridesState(null);
  }, []);

  const savePalette = useCallback((name: string, vars: Record<string, string>) => {
    setSavedPalettes(prev => {
      const filtered = prev.filter(p => p.name !== name);
      const updated = [...filtered, { name, vars }];
      localStorage.setItem('pa-saved-palettes', JSON.stringify(updated));
      return updated;
    });
  }, []);

  const deletePalette = useCallback((name: string) => {
    setSavedPalettes(prev => {
      const updated = prev.filter(p => p.name !== name);
      localStorage.setItem('pa-saved-palettes', JSON.stringify(updated));
      return updated;
    });
  }, []);

  const applySavedPalette = useCallback((name: string) => {
    const pal = savedPalettes.find(p => p.name === name);
    if (pal) setCustomOverridesState(pal.vars);
  }, [savedPalettes]);

  useEffect(() => {
    const root = document.documentElement;
    const vars = THEMES[theme];
    // Apply base theme
    for (const [prop, val] of Object.entries(vars)) {
      root.style.setProperty(prop, val);
    }
    // Apply custom overrides on top (if any)
    if (customOverrides) {
      for (const [prop, val] of Object.entries(customOverrides)) {
        root.style.setProperty(prop, val);
      }
    }

    root.setAttribute('data-theme', theme);
    if (customOverrides) {
      root.setAttribute('data-custom-vibe', 'true');
    } else {
      root.removeAttribute('data-custom-vibe');
    }

    if (animationSpeed === 'reduced') {
      root.style.setProperty('--transition-fast', '0ms');
      root.style.setProperty('--transition-normal', '0ms');
      root.style.setProperty('--transition-slow', '0ms');
    } else {
      root.style.setProperty('--transition-fast', '150ms cubic-bezier(0.4, 0, 0.2, 1)');
      root.style.setProperty('--transition-normal', '300ms cubic-bezier(0.4, 0, 0.2, 1)');
      root.style.setProperty('--transition-slow', '500ms cubic-bezier(0.4, 0, 0.2, 1)');
    }
  }, [theme, animationSpeed, customOverrides]);

  return (
    <ThemeContext.Provider value={{
      theme, setTheme,
      animationSpeed, setAnimationSpeed,
      showIntro, setShowIntro,
      customOverrides, setCustomOverrides, clearCustomOverrides,
      savedPalettes, savePalette, deletePalette, applySavedPalette,
    }}>
      {children}
    </ThemeContext.Provider>
  );
};
