'use client';

import Image from 'next/image';
import { useState } from 'react';

/** Attributed photographic artwork, deliberately separate from calculated geometry. */
export function LunarPortrait() {
  const [rotationPaused, setRotationPaused] = useState(false);
  return (
    <figure
      className="lunar-portrait"
      data-rotation-paused={rotationPaused}
      onPointerMove={(event) => {
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches)
          return;
        const bounds = event.currentTarget.getBoundingClientRect();
        event.currentTarget.style.setProperty(
          '--pointer-x',
          `${(event.clientX - bounds.left - bounds.width / 2) / 90}px`,
        );
        event.currentTarget.style.setProperty(
          '--pointer-y',
          `${(event.clientY - bounds.top - bounds.height / 2) / 90}px`,
        );
      }}
      onPointerLeave={(event) => {
        event.currentTarget.style.setProperty('--pointer-x', '0px');
        event.currentTarget.style.setProperty('--pointer-y', '0px');
      }}
    >
      <div className="moon-object">
        <Image
          src="/images/moon-portrait.jpg"
          alt="NASA Scientific Visualization Studio full-Moon rendering based on Lunar Reconnaissance Orbiter data"
          width={1024}
          height={1024}
          preload
          sizes="(max-width: 700px) 85vw, (max-width: 1100px) 45vw, 580px"
        />
        <div className="moon-shade" aria-hidden="true" />
      </div>
      <aside
        className="portrait-panel"
        aria-label="Lunar south pole introduction"
      >
        <header className="portrait-panel-heading">
          <span className="micro-label">A different perspective</span>
          <button
            type="button"
            className="portrait-motion-control"
            aria-label={
              rotationPaused ? 'Resume Moon rotation' : 'Pause Moon rotation'
            }
            title={
              rotationPaused ? 'Resume Moon rotation' : 'Pause Moon rotation'
            }
            onClick={() => setRotationPaused((paused) => !paused)}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="currentColor"
              aria-hidden="true"
              focusable="false"
            >
              {rotationPaused ? (
                <path d="M6 3 13 8 6 13Z" />
              ) : (
                <>
                  <rect x="4" y="3" width="3" height="10" rx="0.5" />
                  <rect x="9" y="3" width="3" height="10" rx="0.5" />
                </>
              )}
            </svg>
          </button>
        </header>
        <strong>The lunar south pole.</strong>
        <p>
          One horizon.
          <br />
          Two essential connections.
        </p>
        <div className="portrait-panel-legend">
          <span>
            <i className="sun-dot" aria-hidden="true" /> Sunlight
          </span>
          <span>
            <i className="earth-dot" aria-hidden="true" /> Earth visibility
          </span>
        </div>
      </aside>
      <figcaption className="portrait-credit">
        NASA SVS / LRO-based artwork
        <span>
          Decorative rotation and lighting · independent of the selected date
        </span>
      </figcaption>
    </figure>
  );
}
