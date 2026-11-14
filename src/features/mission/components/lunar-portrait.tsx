'use client';

import Image from 'next/image';

/** Attributed photographic artwork, deliberately separate from calculated geometry. */
export function LunarPortrait() {
  return (
    <div
      className="lunar-portrait"
      onPointerMove={(event) => {
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches)
          return;
        const bounds = event.currentTarget.getBoundingClientRect();
        event.currentTarget.style.setProperty(
          '--pointer-x',
          `${(event.clientX - bounds.left - bounds.width / 2) / 60}px`,
        );
        event.currentTarget.style.setProperty(
          '--pointer-y',
          `${(event.clientY - bounds.top - bounds.height / 2) / 60}px`,
        );
      }}
      onPointerLeave={(event) => {
        event.currentTarget.style.setProperty('--pointer-x', '0px');
        event.currentTarget.style.setProperty('--pointer-y', '0px');
      }}
    >
      <div className="orbital-guide orbit-one" />
      <div className="orbital-guide orbit-two" />
      <span className="portrait-coordinate">
        SELENOGRAPHIC REFERENCE / LUNA
      </span>
      <div className="moon-object">
        <Image
          src="/images/moon-portrait.jpg"
          alt="NASA Scientific Visualization Studio full-Moon rendering based on Lunar Reconnaissance Orbiter data"
          width={1024}
          height={1024}
          preload
          sizes="(max-width: 700px) 85vw, 520px"
        />
        <div className="moon-shade" />
      </div>
      <div className="moon-crosshair" aria-hidden="true">
        +
      </div>
      <div className="portrait-panel">
        <span className="micro-label">A DIFFERENT PERSPECTIVE</span>
        <strong>The lunar south pole.</strong>
        <p>
          One horizon.
          <br />
          Two essential connections.
        </p>
        <div>
          <span>
            <i className="sun-dot" />
            Sunlight
          </span>
          <span>
            <i className="earth-dot" />
            Earth visibility
          </span>
        </div>
      </div>
      <p className="portrait-credit">
        LRO-based visualization · NASA SVS
        <br />
        Illustrative lighting, not the selected mission geometry
      </p>
    </div>
  );
}
