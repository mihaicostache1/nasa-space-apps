'use client';

import { useState } from 'react';
import {
  COMPASS,
  elevationBounds,
  elevationStep,
  trackSegments,
  visibilityRuns,
  type Body,
  type SkyPoint,
} from '../lib/sky';
import { HOUR_MS, formatUtc, sampleAt } from '../lib/timeline';
import type { ScenarioResult, Slot } from '../types';

const W = 760;
const H = 320;
const PAD = { left: 44, right: 14, top: 14, bottom: 34 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

type Props = { results: ScenarioResult[]; cursorHours: number };

/** Accurate 2D sky: azimuth clockwise from local north vs elevation above the local horizontal. */
export function AzimuthElevationChart({ results, cursorHours }: Props) {
  // Default to A regardless of which evaluation finished first.
  const [selected, setSelected] = useState<Slot>('A');
  const result = results.find((r) => r.slot === selected) ?? results[0];
  const { data } = result;
  const [low, high] = elevationBounds(data.series, data.horizon);
  const x = (az: number) => PAD.left + (az / 360) * PLOT_W;
  const y = (el: number) => PAD.top + ((high - el) / (high - low)) * PLOT_H;
  const path = (points: SkyPoint[]) =>
    points
      .map(
        (p, i) => `${i ? 'L' : 'M'}${x(p.az).toFixed(1)},${y(p.el).toFixed(1)}`,
      )
      .join('');
  const horizon = [...data.horizon, { az: 360, el: data.horizon[0].el }];
  const horizonLine = horizon
    .map((p, i) => `${i ? 'L' : 'M'}${x(p.az)},${y(p.el)}`)
    .join('');
  const ground = `${horizonLine}L${x(360)},${y(low)}L${x(0)},${y(low)}Z`;
  const cursorMs =
    Date.parse(data.provenance.ephemeris.startUtc) + cursorHours * HOUR_MS;
  const sample = sampleAt(data.series, cursorMs, data.calculation.stepMinutes);
  const tickStep = elevationStep(low, high);
  const ticks: number[] = [];
  for (
    let el = Math.ceil(low / tickStep) * tickStep;
    el <= high;
    el += tickStep
  )
    ticks.push(el);

  return (
    <section className="analysis" aria-labelledby="elevation-heading">
      <div className="section-heading">
        <h2 id="elevation-heading">Elevation detail</h2>
        {results.length > 1 && (
          <div className="toggle" role="group" aria-label="Scenario">
            {results.map((r) => (
              <button
                key={r.slot}
                type="button"
                aria-pressed={r.slot === selected}
                onClick={() => setSelected(r.slot)}
              >
                {r.slot}
              </button>
            ))}
          </div>
        )}
      </div>
      <figure className="panel sky">
        <div className="sky-scroll">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-labelledby="elevation-caption"
          >
            <path d={ground} className="ground" />
            {ticks.map((el) => (
              <g key={el}>
                <line
                  x1={PAD.left}
                  x2={W - PAD.right}
                  y1={y(el)}
                  y2={y(el)}
                  className={el === 0 ? 'zero' : 'grid'}
                />
                <text x={PAD.left - 8} y={y(el) + 4} textAnchor="end">
                  {el}°
                </text>
              </g>
            ))}
            {COMPASS.map(({ az, label }) => (
              <g key={az}>
                <line
                  x1={x(az)}
                  x2={x(az)}
                  y1={PAD.top}
                  y2={H - PAD.bottom}
                  className="grid"
                />
                <text x={x(az)} y={H - PAD.bottom + 18} textAnchor="middle">
                  {label} {az < 360 ? `${az}°` : ''}
                </text>
              </g>
            ))}
            <path d={horizonLine} className="horizon" />
            {(['sun', 'earth'] as Body[]).map((body) =>
              trackSegments(data.series, body).flatMap((segment, s) =>
                visibilityRuns(segment).map((run, r) => (
                  <path
                    key={`${body}-${s}-${r}`}
                    d={path(run.points)}
                    className={`track ${body}${run.visible ? '' : ' hidden-run'}`}
                  />
                )),
              ),
            )}
            {sample && (
              <>
                <circle
                  cx={x(sample.sunAz)}
                  cy={y(sample.sunEl)}
                  r={7}
                  className="marker sun"
                />
                <circle
                  cx={x(sample.earthAz)}
                  cy={y(sample.earthEl)}
                  r={7}
                  className="marker earth"
                />
              </>
            )}
          </svg>
        </div>
        <figcaption id="elevation-caption">
          <span className="slot">{result.slot}</span> {data.site}: Sun (amber)
          and Earth (blue) paths over the selected period; solid where visible,
          dashed where hidden. The shaded area is below the{' '}
          {data.horizonMode === 'geometric' ? 'flat 0° geometric' : 'terrain'}{' '}
          horizon. Azimuth runs clockwise from local north.
          {sample
            ? ` At ${formatUtc(cursorMs)} the Sun is at ${sample.sunAz.toFixed(1)}° az, ${sample.sunEl.toFixed(2)}° elev and the Earth at ${sample.earthAz.toFixed(1)}° az, ${sample.earthEl.toFixed(2)}° elev.`
            : ' The cursor is outside this scenario’s period.'}
        </figcaption>
      </figure>
    </section>
  );
}
