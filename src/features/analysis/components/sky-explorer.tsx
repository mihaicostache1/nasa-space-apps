'use client';

import { useState, type PointerEvent } from 'react';
import { skyPosition } from '@/features/mission/lib/projections';
import { visibilityRuns, type Body } from '../lib/sky';
import { HOUR_MS, formatUtc, sampleAt } from '../lib/timeline';
import type { ScenarioResult } from '../types';

export function SkyExplorer({
  result,
  cursorHours,
  onCursorChange,
}: {
  result: ScenarioResult;
  cursorHours: number;
  onCursorChange: (hours: number) => void;
}) {
  const [hover, setHover] = useState<{ index: number; body: Body } | null>(
    null,
  );
  const { data } = result;
  const low = Math.min(
    -10,
    Math.floor(
      Math.min(
        ...data.series.flatMap((s) => [s.sunEl, s.earthEl]),
        ...data.horizon.map((p) => p.el),
      ),
    ) - 1,
  );
  const position = (az: number, el: number) => skyPosition(az, el, low);
  const line = (points: { az: number; el: number }[]) =>
    points
      .map((p, i) => {
        const { x, y } = position(p.az, p.el);
        return `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join('');
  const horizon = line(data.horizon) + 'Z';
  const start = Date.parse(data.provenance.ephemeris.startUtc);
  const selected = sampleAt(
    data.series,
    start + cursorHours * HOUR_MS,
    data.calculation.stepMinutes,
  );
  const inspected = hover ? (data.series[hover.index] ?? selected) : selected;

  function inspect(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - box.left) * 480) / box.width;
    const y = ((event.clientY - box.top) * 480) / box.height;
    let nearest: { index: number; body: Body } | null = null;
    let distance = 24;
    data.series.forEach((sample, index) => {
      for (const body of ['sun', 'earth'] as Body[]) {
        const point = position(
          body === 'sun' ? sample.sunAz : sample.earthAz,
          body === 'sun' ? sample.sunEl : sample.earthEl,
        );
        const d = Math.hypot(point.x - x, point.y - y);
        if (d < distance) {
          distance = d;
          nearest = { index, body };
        }
      }
    });
    const candidate = nearest as { index: number; body: Body } | null;
    setHover((previous) =>
      previous?.index === candidate?.index && previous?.body === candidate?.body
        ? previous
        : candidate,
    );
    if (nearest && event.buttons === 1) {
      const point = nearest as { index: number; body: Body };
      onCursorChange(
        (Date.parse(data.series[point.index].t) - start) / HOUR_MS,
      );
    }
  }

  return (
    <figure
      className={`sky-dome${result.stale ? ' is-stale' : ''}`}
      aria-labelledby="dome-caption"
    >
      <div className="dome-heading">
        <span className="micro-label">LOCAL SKY / SCENARIO {result.slot}</span>
        <span className="model-tag">
          {data.horizonMode === 'terrain' ? 'LOLA TERRAIN' : 'GEOMETRIC'}
        </span>
      </div>
      <svg
        viewBox="0 0 480 480"
        role="img"
        aria-label="Interactive sky dome: north up, east right, zenith at centre"
        onPointerMove={inspect}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          inspect(event);
        }}
        onPointerLeave={() => setHover(null)}
      >
        <circle cx="240" cy="240" r="185" className="dome-disc" />
        <path
          d={`M240 55a185 185 0 1 0 0 370a185 185 0 1 0 0-370Z${horizon}`}
          fillRule="evenodd"
          className="dome-ground"
        />
        {[0, 30, 60].map((el) => (
          <g key={el}>
            <circle
              cx="240"
              cy="240"
              r={Math.hypot(position(0, el).x - 240, position(0, el).y - 240)}
              className={el === 0 ? 'dome-zero' : 'grid'}
            />
            <text x="246" y={position(0, el).y + 14}>
              {el}°
            </text>
          </g>
        ))}
        {[0, 45, 90, 135, 180, 225, 270, 315].map((az) => {
          const p = position(az, low);
          return (
            <line
              key={az}
              x1="240"
              y1="240"
              x2={p.x}
              y2={p.y}
              className="grid"
            />
          );
        })}
        <text x="240" y="32" textAnchor="middle" className="compass-major">
          N <tspan>000°</tspan>
        </text>
        <text x="455" y="244" textAnchor="middle" className="compass-major">
          E
        </text>
        <text x="240" y="463" textAnchor="middle" className="compass-major">
          S 180°
        </text>
        <text x="25" y="244" textAnchor="middle" className="compass-major">
          W
        </text>
        <circle cx="240" cy="240" r="2" className="zenith-dot" />
        <text x="240" y="260" textAnchor="middle">
          ZENITH 90°
        </text>
        <path d={horizon} className="dome-horizon" />
        {(['sun', 'earth'] as Body[]).map((body) =>
          visibilityRuns(
            data.series.map((s) => ({
              az: body === 'sun' ? s.sunAz : s.earthAz,
              el: body === 'sun' ? s.sunEl : s.earthEl,
              visible: body === 'sun' ? s.sunLit : s.earthVis,
            })),
          ).map((run, index) => (
            <path
              key={`${body}-${index}`}
              d={line(run.points)}
              pathLength={run.visible ? 1 : undefined}
              className={`dome-track ${body}${run.visible ? '' : ' occluded'}`}
            />
          )),
        )}
        {selected &&
          (['sun', 'earth'] as Body[]).map((body) => {
            const p = position(
              body === 'sun' ? selected.sunAz : selected.earthAz,
              body === 'sun' ? selected.sunEl : selected.earthEl,
            );
            const visible =
              body === 'sun' ? selected.sunLit : selected.earthVis;
            return (
              <g
                key={body}
                className={`dome-marker-position ${body}`}
                style={{ transform: `translate(${p.x}px, ${p.y}px)` }}
              >
                <circle
                  cx="0"
                  cy="0"
                  r="12"
                  className={`marker-ring ${body}`}
                />
                <circle
                  cx="0"
                  cy="0"
                  r="5"
                  className={`dome-marker ${body}${visible ? '' : ' occluded'}`}
                />
              </g>
            );
          })}
      </svg>
      <div className="dome-legend">
        <span>
          <i className="sun-dot" />
          Sun
        </span>
        <span>
          <i className="earth-dot" />
          Earth
        </span>
        <span>
          <i className="hidden-dash" />
          Occluded
        </span>
        <span>
          <i className="horizon-dash" />
          Horizon
        </span>
      </div>
      <div className="dome-readout" aria-live="polite">
        <span className="micro-label">
          {hover ? 'INSPECTED OBSERVATION' : 'SELECTED OBSERVATION'}
        </span>
        <strong>
          {inspected
            ? formatUtc(inspected.t)
            : 'Outside this scenario’s period'}
        </strong>
        {inspected && (
          <dl>
            {(['sun', 'earth'] as Body[]).map((body) => (
              <div key={body} className={body}>
                <dt>
                  {body === 'sun' ? 'Sun' : 'Earth'} ·{' '}
                  {body === 'sun'
                    ? inspected.sunLit
                      ? 'visible'
                      : 'occluded'
                    : inspected.earthVis
                      ? 'visible'
                      : 'occluded'}
                </dt>
                <dd>
                  {(body === 'sun'
                    ? inspected.sunAz
                    : inspected.earthAz
                  ).toFixed(1)}
                  ° az /{' '}
                  {(body === 'sun'
                    ? inspected.sunEl
                    : inspected.earthEl
                  ).toFixed(2)}
                  ° el
                  <br />
                  <span>
                    Horizon{' '}
                    {(body === 'sun'
                      ? inspected.sunHorizonEl
                      : inspected.earthHorizonEl
                    ).toFixed(2)}
                    °
                  </span>
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <figcaption id="dome-caption">
        Azimuthal equidistant sky: north up, azimuth clockwise, 90° at centre,
        0° on the reference ring. Outer edge {low}°. Hover to inspect; drag a
        path to select an archived sample. Markers are symbolic; paths join
        samples without adding timing precision. Marker transitions are visual
        only; readouts use the selected archived sample.
      </figcaption>
    </figure>
  );
}
