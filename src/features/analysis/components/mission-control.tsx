'use client';

import { useState } from 'react';
import type { ReferenceSite } from '@/domain/reference';
import type { ScenarioResult, Slot } from '../types';
import {
  formatHours,
  formatPercent,
  formatUtc,
  HOUR_MS,
  longestOf,
  sampleAt,
} from '../lib/timeline';

type Props = {
  sites: ReferenceSite[];
  selections: { slot: Slot; siteId: string }[];
  results: ScenarioResult[];
  cursorHours: number;
  onSelectSite: (slot: Slot, site: ReferenceSite) => void;
  onJump: (hours: number) => void;
};

/** South-pole azimuthal-equidistant location diagram, not a terrain raster. */
export function MissionControl({
  sites,
  selections,
  results,
  cursorHours,
  onSelectSite,
  onJump,
}: Props) {
  const [target, setTarget] = useState<Slot>('A');
  const radiusDegrees =
    Math.max(5, ...sites.map((site) => 90 + site.lat)) * 1.15;
  const point = (site: ReferenceSite) => {
    const r = ((90 + site.lat) / radiusDegrees) * 145;
    const angle = (site.lon * Math.PI) / 180;
    return { x: 180 + r * Math.sin(angle), y: 180 - r * Math.cos(angle) };
  };
  const [a, b] = ['A', 'B'].map((slot) =>
    results.find((result) => result.slot === slot),
  );
  const comparable = a && b && !a.stale && !b.stale;
  const delta = comparable
    ? b.data.metrics.bothHrs - a.data.metrics.bothHrs
    : null;

  return (
    <section
      className="mission-control analysis"
      aria-labelledby="operations-heading"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">MISSION CONTROL / T+{cursorHours} H</p>
          <h2 id="operations-heading">Operational overview</h2>
        </div>
        <span className="badge">
          {results.some((result) => result.stale)
            ? 'INPUTS CHANGED · UPDATE REQUIRED'
            : 'ARCHIVE SIMULATION · UTC'}
        </span>
      </div>
      <div className="operations-grid">
        <article className="panel polar-panel">
          <div className="section-heading">
            <h3>South-pole sites</h3>
            <div
              className="toggle"
              role="group"
              aria-label="Assign map selection to scenario"
            >
              {(['A', 'B'] as const).map((slot) => (
                <button
                  key={slot}
                  type="button"
                  aria-pressed={target === slot}
                  onClick={() => setTarget(slot)}
                >
                  Assign {slot}
                </button>
              ))}
            </div>
          </div>
          <svg
            className="polar-map"
            viewBox="0 0 360 360"
            role="group"
            aria-label="Selectable lunar south-pole reference sites"
          >
            <defs>
              <radialGradient id="polar-shade">
                <stop stopColor="#23364a" />
                <stop offset="1" stopColor="#0b1420" />
              </radialGradient>
            </defs>
            <circle cx="180" cy="180" r="155" fill="url(#polar-shade)" />
            {[45, 90, 145].map((r) => (
              <circle key={r} cx="180" cy="180" r={r} className="polar-grid" />
            ))}
            {[0, 45, 90, 135].map((angle) => (
              <path
                key={angle}
                d="M180 25V335"
                transform={`rotate(${angle} 180 180)`}
                className="polar-grid"
              />
            ))}
            <text x="180" y="16" textAnchor="middle">
              0° E
            </text>
            <text x="180" y="353" textAnchor="middle">
              180° E
            </text>
            <text x="14" y="184" textAnchor="middle">
              W
            </text>
            <text x="346" y="184" textAnchor="middle">
              E
            </text>
            <text x="190" y="196" className="pole-label">
              90° S
            </text>
            <path d="M175 180h10m-5-5v10" stroke="#a8b6c6" />
            {sites.map((site, i) => {
              const p = point(site);
              const assigned = selections
                .filter((selection) => selection.siteId === site.id)
                .map((selection) => selection.slot)
                .join('/');
              return (
                <g
                  key={site.id}
                  className={`map-site${assigned ? ' selected' : ''}`}
                  role="button"
                  tabIndex={0}
                  aria-label={`Assign ${site.name} to scenario ${target}`}
                  onClick={() => onSelectSite(target, site)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelectSite(target, site);
                    }
                  }}
                >
                  <title>
                    {site.name} · {site.lat.toFixed(4)}°, {site.lon.toFixed(4)}°
                    E
                  </title>
                  <circle cx={p.x} cy={p.y} r="17" className="site-hit" />
                  <circle cx={p.x} cy={p.y} r="7" className="site-dot" />
                  <text x={p.x + 12} y={p.y - 11}>
                    {assigned || `0${i + 1}`}
                  </text>
                </g>
              );
            })}
          </svg>
          <p className="hint">
            Select a marker to assign scenario {target}, then update the
            comparison. Position diagram; terrain is not shown.
          </p>
          <ul className="map-key">
            {sites.map((site, i) => (
              <li key={site.id}>
                <button
                  type="button"
                  onClick={() => onSelectSite(target, site)}
                >
                  <span>0{i + 1}</span>
                  {site.name.replace(' DEM reference point', '')}
                </button>
              </li>
            ))}
          </ul>
        </article>
        <div className="operation-cards">
          {results.map(({ slot, data, stale }) => {
            const time =
              Date.parse(data.provenance.ephemeris.startUtc) +
              cursorHours * HOUR_MS;
            const sample =
              time < Date.parse(data.provenance.ephemeris.endUtc)
                ? sampleAt(data.series, time, data.calculation.stepMinutes)
                : null;
            const longest = longestOf(
              data.windows.both,
              data.metrics.longestBothHrs,
            );
            const next = data.windows.both.find(
              (window) => Date.parse(window.endUtc) > time,
            );
            return (
              <article
                className={`panel operation-card${stale ? ' is-stale' : ''}`}
                key={slot}
              >
                <div className="section-heading">
                  <h3>
                    <span className="slot">{slot}</span>
                    {data.site.replace(' DEM reference point', '')}
                  </h3>
                  <span className="operation-model">{data.horizonMode}</span>
                </div>
                <p className="hint">
                  {formatUtc(time)}
                  {stale ? ' · previous result, update required' : ''}
                </p>
                <div className="body-indicators">
                  <div className="body-indicator sun">
                    <span className={`signal${sample?.sunLit ? ' on' : ''}`} />
                    <strong>
                      Sun{' '}
                      {sample
                        ? sample.sunLit
                          ? 'visible'
                          : 'hidden'
                        : 'outside range'}
                    </strong>
                    <small>
                      {sample ? `${sample.sunEl.toFixed(2)}° elevation` : '—'}
                    </small>
                  </div>
                  <div className="body-indicator earth">
                    <span
                      className={`signal${sample?.earthVis ? ' on' : ''}`}
                    />
                    <strong>
                      Earth{' '}
                      {sample
                        ? sample.earthVis
                          ? 'visible'
                          : 'hidden'
                        : 'outside range'}
                    </strong>
                    <small>
                      {sample ? `${sample.earthEl.toFixed(2)}° elevation` : '—'}
                    </small>
                  </div>
                </div>
                <div className="operation-metric">
                  <span>Longest combined window</span>
                  <strong>{formatHours(longest.hours, longest.atLeast)}</strong>
                </div>
                <div
                  className="availability-bar"
                  role="img"
                  aria-label={`${formatPercent(data.metrics.pctBoth)} simultaneous visibility`}
                >
                  <span style={{ width: `${data.metrics.pctBoth}%` }} />
                </div>
                <p className="hint">
                  {formatPercent(data.metrics.pctBoth)} of the selected period
                  with Sun + Earth visible
                </p>
                <button
                  type="button"
                  className="link-button"
                  disabled={!next || !sample}
                  onClick={() =>
                    next &&
                    onJump(
                      Math.max(
                        0,
                        (Date.parse(next.startUtc) -
                          Date.parse(data.provenance.ephemeris.startUtc)) /
                          HOUR_MS,
                      ),
                    )
                  }
                >
                  {next && Date.parse(next.startUtc) <= time
                    ? 'Show current operating window'
                    : next
                      ? 'Show next operating window'
                      : 'No remaining combined window'}
                </button>
              </article>
            );
          })}
          <div className="comparison-verdict" role="status">
            <span className="eyebrow">WINDOW COMPARISON</span>
            <p>
              {delta === null
                ? 'Update both scenarios to compare their operating time.'
                : Math.abs(delta) < 0.01
                  ? 'Both scenarios offer the same total combined visibility.'
                  : `Scenario ${delta > 0 ? 'B' : 'A'} offers ${formatHours(Math.abs(delta))} more combined visibility in the selected periods.`}
            </p>
            <small>
              Total hours, not a landing recommendation. Different period
              lengths and horizon models can affect the comparison.
            </small>
          </div>
        </div>
      </div>
    </section>
  );
}
