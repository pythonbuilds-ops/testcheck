import React, { useState } from 'react';
import type { ThemeName } from './ThemeProvider';
import { useTheme } from './ThemeProvider';
import { Palette, Zap, Play, X, Sparkles, Trash2, Save, RotateCcw, Loader2 } from 'lucide-react';
import { getApiUrl } from '../lib/runtime';
import './ThemeSettings.css';

interface ThemeSettingsProps {
  onClose: () => void;
}

const themeCards: { id: ThemeName; label: string; desc: string; colors: string[] }[] = [
  { id: 'midnight', label: 'Midnight', desc: 'Deep dark with purple accents', colors: ['#0a0a0f', '#8b5cf6', '#ec4899'] },
  { id: 'cyberpunk', label: 'Cyberpunk', desc: 'Neon cyan & electric magenta', colors: ['#050505', '#00f0ff', '#ff2d7c'] },
  { id: 'arctic', label: 'Arctic', desc: 'Frosted ice with aurora blue', colors: ['#eef2f7', '#4f8af7', '#e855b3'] },
];

export const ThemeSettings: React.FC<ThemeSettingsProps> = ({ onClose }) => {
  const {
    theme, setTheme,
    animationSpeed, setAnimationSpeed,
    showIntro, setShowIntro,
    customOverrides, setCustomOverrides, clearCustomOverrides,
    savedPalettes, savePalette, deletePalette, applySavedPalette,
  } = useTheme();

  const [vibeInput, setVibeInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [pendingPalette, setPendingPalette] = useState<Record<string, string> | null>(null);
  const [vibeError, setVibeError] = useState('');
  const [saveName, setSaveName] = useState('');

  const generatePalette = async () => {
    if (!vibeInput.trim()) return;
    setIsGenerating(true);
    setVibeError('');
    setPendingPalette(null);
    try {
      const res = await fetch(getApiUrl('/api/generate-palette'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: vibeInput.trim() }),
      });
      if (!res.ok) throw new Error('Failed to generate palette');
      const data = await res.json();
      if (data.palette) {
        setPendingPalette(data.palette);
      } else {
        setVibeError('Invalid response from server');
      }
    } catch (err: any) {
      setVibeError(err.message || 'Failed to generate palette');
    } finally {
      setIsGenerating(false);
    }
  };

  const applyPendingPalette = () => {
    if (pendingPalette) {
      setCustomOverrides(pendingPalette);
      setSaveName(vibeInput.trim());
    }
  };

  const handleSavePalette = () => {
    const name = saveName.trim() || vibeInput.trim();
    if (name && customOverrides) {
      savePalette(name, customOverrides);
    }
  };

  const previewColors = pendingPalette
    ? [
        pendingPalette['--bg-primary'],
        pendingPalette['--accent-primary'],
        pendingPalette['--accent-secondary'],
        pendingPalette['--accent-tertiary'],
        pendingPalette['--text-primary'],
      ].filter(Boolean)
    : [];

  return (
    <div className="theme-settings-overlay" onClick={onClose}>
      <div className="theme-settings-panel glass-panel" onClick={e => e.stopPropagation()}>
        <div className="theme-settings-header">
          <div className="theme-settings-title">
            <Palette size={20} />
            <h3>Appearance</h3>
          </div>
          <button className="theme-close-btn" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="theme-section">
          <h4>Theme</h4>
          <div className="theme-cards-grid">
            {themeCards.map(t => (
              <button
                key={t.id}
                className={`theme-card ${theme === t.id ? 'active' : ''}`}
                onClick={() => { setTheme(t.id); clearCustomOverrides(); }}
              >
                <div className="theme-color-preview">
                  {t.colors.map((c, i) => (
                    <div key={i} className="theme-color-dot" style={{ background: c }} />
                  ))}
                </div>
                <span className="theme-card-label">{t.label}</span>
                <span className="theme-card-desc">{t.desc}</span>
              </button>
            ))}
          </div>
        </div>

        {/* AI Vibe Generator */}
        <div className="theme-section">
          <h4><Sparkles size={12} style={{ display: 'inline', marginRight: 4 }} />AI Vibe</h4>
          <p className="vibe-desc">Type a mood or phrase to generate a custom color palette</p>
          <div className="vibe-input-row">
            <input
              type="text"
              className="vibe-input"
              value={vibeInput}
              onChange={e => setVibeInput(e.target.value)}
              placeholder='e.g., "Chocolate Strawberry"'
              onKeyDown={e => e.key === 'Enter' && generatePalette()}
              disabled={isGenerating}
            />
            <button
              className="vibe-generate-btn"
              onClick={generatePalette}
              disabled={!vibeInput.trim() || isGenerating}
            >
              {isGenerating ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
            </button>
          </div>

          {vibeError && <p className="vibe-error">{vibeError}</p>}

          {previewColors.length > 0 && (
            <div className="vibe-preview">
              <div className="vibe-preview-dots">
                {previewColors.map((c, i) => (
                  <div key={i} className="vibe-dot" style={{ background: c }} />
                ))}
              </div>
              <div className="vibe-actions">
                <button className="vibe-apply-btn" onClick={applyPendingPalette}>Apply</button>
              </div>
            </div>
          )}

          {customOverrides && (
            <div className="vibe-active-bar">
              <span className="vibe-active-label">Custom vibe active</span>
              <div className="vibe-active-actions">
                <button className="vibe-save-btn" onClick={handleSavePalette} title="Save this palette">
                  <Save size={14} />
                </button>
                <button className="vibe-clear-btn" onClick={clearCustomOverrides} title="Clear & revert">
                  <RotateCcw size={14} />
                </button>
              </div>
            </div>
          )}

          {savedPalettes.length > 0 && (
            <div className="saved-palettes">
              <h5>Saved Vibes</h5>
              {savedPalettes.map(p => (
                <div key={p.name} className="saved-palette-row">
                  <button className="saved-palette-name" onClick={() => applySavedPalette(p.name)}>
                    {p.name}
                  </button>
                  <button className="saved-palette-delete" onClick={() => deletePalette(p.name)}>
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="theme-section">
          <h4>Animations</h4>
          <div className="theme-toggle-row">
            <div className="theme-toggle-info">
              <Zap size={16} />
              <span>Animation Speed</span>
            </div>
            <div className="theme-toggle-pills">
              <button
                className={`pill ${animationSpeed === 'normal' ? 'active' : ''}`}
                onClick={() => setAnimationSpeed('normal')}
              >Normal</button>
              <button
                className={`pill ${animationSpeed === 'reduced' ? 'active' : ''}`}
                onClick={() => setAnimationSpeed('reduced')}
              >Reduced</button>
            </div>
          </div>
          <div className="theme-toggle-row">
            <div className="theme-toggle-info">
              <Play size={16} />
              <span>Intro Animation</span>
            </div>
            <div className="theme-toggle-pills">
              <button
                className={`pill ${showIntro ? 'active' : ''}`}
                onClick={() => setShowIntro(true)}
              >On</button>
              <button
                className={`pill ${!showIntro ? 'active' : ''}`}
                onClick={() => setShowIntro(false)}
              >Off</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
