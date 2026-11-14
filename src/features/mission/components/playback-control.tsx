'use client';

import { useEffect, useState } from 'react';

export function PlaybackControl({
  hours,
  max,
  step,
  disabled,
  onChange,
}: {
  hours: number;
  max: number;
  step: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  const [playing, setPlaying] = useState(false);
  const running = playing && !disabled && hours < max;
  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(
      () => onChange(Math.min(max, hours + step)),
      700,
    );
    return () => window.clearTimeout(timer);
  }, [hours, max, onChange, running, step]);
  return (
    <div className="playback-control">
      <button
        className="quiet-button"
        type="button"
        disabled={disabled}
        aria-label={
          running ? 'Pause archived samples' : 'Play archived samples'
        }
        onClick={() => {
          if (!running && hours >= max) onChange(0);
          setPlaying(!running);
        }}
      >
        {running ? 'Ⅱ Pause' : '▷ Play'}
      </button>
      <span className="micro-label">ONE ARCHIVED SAMPLE / STEP</span>
    </div>
  );
}
