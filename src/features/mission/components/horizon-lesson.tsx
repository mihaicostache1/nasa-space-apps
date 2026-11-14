'use client';

import { useId, useState } from 'react';
import { MotionValue } from './experience-motion';

/** An intentionally illustrative disc/horizon lesson, separate from all API data. */
export function HorizonLesson() {
  const [height, setHeight] = useState(1);
  const id = useId();
  const sunElevation = 2;
  const radius = 0.27;
  const status =
    height < sunElevation - radius
      ? 'Fully visible'
      : height < sunElevation + radius
        ? 'Partly visible'
        : 'Occluded';
  const y = (elevation: number) => 170 - elevation * 25;
  return (
    <section
      className="horizon-lesson"
      aria-labelledby="horizon-lesson-heading"
      data-reveal
    >
      <div className="lesson-explanation">
        <span className="micro-label">TRY THE GEOMETRY · ILLUSTRATIVE</span>
        <h3 id="horizon-lesson-heading">
          A small ridge.
          <br />A different outcome.
        </h3>
        <p>
          Leave the Sun at 2° elevation. Raise the local horizon and see how a
          disc can go from fully visible to hidden.
        </p>
        <label>
          Illustrative horizon elevation
          <input
            type="range"
            min={0}
            max={5}
            step={0.1}
            value={height}
            onChange={(event) => setHeight(event.target.valueAsNumber)}
          />
        </label>
        <p className="lesson-values">
          <span>
            Horizon <MotionValue>{`${height.toFixed(1)}°`}</MotionValue>
          </span>
          <span role="status">
            <MotionValue>{status}</MotionValue>
          </span>
        </p>
      </div>
      <div className="lesson-canvas">
        <svg
          viewBox="0 0 500 210"
          role="img"
          aria-label={`Illustrative Sun at 2 degrees; horizon ${height.toFixed(1)} degrees; ${status.toLowerCase()}`}
        >
          <defs>
            <clipPath id={id}>
              <rect x="40" y="0" width="420" height={y(height)} />
            </clipPath>
          </defs>
          {[0, 2, 4].map((el) => (
            <g key={el}>
              <line x1="40" x2="460" y1={y(el)} y2={y(el)} className="grid" />
              <text x="24" y={y(el) + 4} textAnchor="end">
                {el}°
              </text>
            </g>
          ))}
          <circle
            cx="170"
            cy={y(sunElevation)}
            r={radius * 25}
            className="lesson-sun-shadow"
          />
          <g clipPath={`url(#${id})`}>
            <circle
              cx="170"
              cy={y(sunElevation)}
              r={radius * 25}
              className="lesson-sun"
            />
            <line
              x1="190"
              x2="420"
              y1={y(sunElevation)}
              y2={y(sunElevation)}
              className="lesson-sightline"
            />
          </g>
          <rect
            x="40"
            y={y(height)}
            width="420"
            height={190 - y(height)}
            className="lesson-terrain"
          />
          <line
            x1="40"
            x2="460"
            y1={y(height)}
            y2={y(height)}
            className="lesson-horizon"
          />
          <text x="450" y={y(height) - 10} textAnchor="end">
            LOCAL HORIZON
          </text>
          <text x="170" y="200" textAnchor="middle">
            SUN CENTRE 2° / RADIUS 0.27°
          </text>
        </svg>
        <p>
          Concept diagram with chosen angles. This is not a NASA prediction for
          the selected site.
        </p>
      </div>
    </section>
  );
}
