import React, { useEffect, useRef, useState } from 'react';
import anime from 'animejs';
import './OpeningAnimation.css';

interface OpeningAnimationProps {
  onComplete: () => void;
}

export const OpeningAnimation: React.FC<OpeningAnimationProps> = ({ onComplete }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [columns, setColumns] = useState(0);
  const [rows, setRows] = useState(0);

  useEffect(() => {
    if (!containerRef.current) return;

    const calculateGrid = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      // Slightly larger cells = fewer elements = smoother compositing
      const cellSize = 55;
      const cols = Math.max(Math.floor(w / cellSize), 1);
      const rws = Math.max(Math.floor(h / cellSize), 1);
      setColumns(cols);
      setRows(rws);
    };

    calculateGrid();
    window.addEventListener('resize', calculateGrid);
    return () => window.removeEventListener('resize', calculateGrid);
  }, []);

  useEffect(() => {
    if (columns === 0 || rows === 0) return;

    const timeline = anime.timeline({
      complete: onComplete,
    });

    // Phase 1 — cells bloom outward from center with a gentle ease
    timeline.add({
      targets: '.stagger-visualizer .cell',
      scale: [
        { value: 0.2, easing: 'easeOutExpo', duration: 600 },
        { value: 1, easing: 'easeOutSine', duration: 1400 },
      ],
      translateY: [
        { value: -30, easing: 'easeOutExpo', duration: 600 },
        { value: 0, easing: 'easeOutSine', duration: 1400 },
      ],
      opacity: [
        { value: 1, easing: 'easeOutExpo', duration: 600 },
        { value: 0.85, easing: 'easeOutSine', duration: 1400 },
      ],
      delay: anime.stagger(120, { grid: [columns, rows], from: 'center' }),
      backgroundColor: [
        { value: '#8b5cf6', easing: 'easeOutExpo', duration: 600 },
        { value: '#ec4899', easing: 'easeInOutSine', duration: 1400 },
      ],
    });

    // Phase 2 — brief breathing pause, then dissolve
    timeline.add({
      targets: '.stagger-visualizer .cell',
      scale: [1, 0],
      opacity: [0.85, 0],
      duration: 1000,
      delay: anime.stagger(30, { grid: [columns, rows], from: 'center' }),
      easing: 'easeInOutSine',
    }, '+=300'); // 300ms pause between phases for a "breathing" moment

    // Phase 3 — fade out the entire container
    timeline.add({
      targets: '.opening-container',
      opacity: 0,
      duration: 600,
      easing: 'easeInOutSine',
    }, '-=600');
  }, [columns, rows, onComplete]);

  const cells = Array.from({ length: columns * rows }).map((_, i) => (
    <div key={i} className="cell" />
  ));

  return (
    <div className="opening-container" ref={containerRef}>
      <div
        className="stagger-visualizer"
        style={{
          gridTemplateColumns: `repeat(${columns}, 1fr)`,
          gridTemplateRows: `repeat(${rows}, 1fr)`,
        }}
      >
        {cells}
      </div>
      <div className="hero-text-container">
        <h1 className="hero-title">PhoneAgent</h1>
        <p className="hero-subtitle">Autonomous Device Control</p>
      </div>
    </div>
  );
};
