'use client';

import type { PointerEvent } from 'react';
import type { VisibilityWindow } from '@/domain/evaluation';
import { MotionValue } from '@/features/mission/components/experience-motion';
import { comparisonInsight } from '../lib/comparison-insight';
import { describeModel } from '../lib/model';
import {
  HOUR_MS,
  domainHours,
  domainOf,
  formatHours,
  formatPercent,
  formatSetting,
  formatUtc,
  longestOf,
  sampleAt,
  segments,
} from '../lib/timeline';
import type { ScenarioResult } from '../types';

type Props = {
  results: ScenarioResult[];
  cursorHours: number;
  onCursorChange: (hours: number) => void;
};
const LANES = [
  { key: 'sunlit', label: 'Sun', className: 'sun' },
  { key: 'earthVisible', label: 'Earth', className: 'earth' },
  { key: 'both', label: 'Sun + Earth', className: 'both' },
] as const;

export function ComparisonTimeline({
  results,
  cursorHours,
  onCursorChange,
}: Props) {
  if (!results.length) return null;
  const maxHours = Math.max(
    ...results.map(({ data }) => data.metrics.evaluatedHrs),
  );
  const step =
    Math.min(...results.map(({ data }) => data.calculation.stepMinutes)) / 60;
  const maxCursor = Math.max(0, maxHours - Math.min(step, maxHours));
  const insight = comparisonInsight(results);
  function moveTo(event: PointerEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    if (!box.width) return;
    const fraction = Math.min(
      1,
      Math.max(0, (event.clientX - box.left) / box.width),
    );
    onCursorChange(
      Math.min(maxCursor, Math.floor((fraction * maxHours) / step) * step),
    );
  }
  return (
    <section
      className="analysis comparison-experience"
      aria-label="Scenario comparison"
      data-reveal
    >
      <div className="comparison-summaries">
        {results.map((result) => (
          <ScenarioSummary
            key={result.slot}
            result={result}
            differences={insight.differences}
          />
        ))}
      </div>
      <aside
        className={`comparison-insight${insight.comparable ? '' : ' is-contextual'}`}
      >
        <span className="comparison-insight-mark" aria-hidden="true">
          ↔
        </span>
        <div>
          <h3>{insight.title}</h3>
          <p>{insight.description}</p>
        </div>
      </aside>
      <div className="comparison-chart">
        <header className="comparison-chart-heading">
          <div>
            <h3 id="timeline-heading">One timeline. Two perspectives.</h3>
            <p>
              Hours elapsed from each scenario’s start. UTC timestamps are shown
              separately below.
            </p>
          </div>
          <span className="comparison-elapsed">
            T+{Number(cursorHours.toFixed(2))} h
          </span>
        </header>
        <label className="comparison-scrubber cursor-control">
          <span>Shared timeline cursor</span>
          <input
            type="range"
            aria-label="Shared timeline cursor"
            min={0}
            max={maxCursor}
            step={step}
            value={Math.min(cursorHours, maxCursor)}
            onChange={(event) => onCursorChange(event.target.valueAsNumber)}
          />
        </label>
        <div className="comparison-time-grid">
          {results.map((result) => {
            const { data, slot } = result;
            const domain = domainOf(
              data.provenance.ephemeris.startUtc,
              data.provenance.ephemeris.endUtc,
            );
            const hours = domainHours(domain);
            return (
              <div
                className={`comparison-track-group${result.stale ? ' is-stale' : ''}`}
                key={slot}
              >
                <div className="comparison-track-name">
                  <span className="comparison-slot">{slot}</span>
                  <span>{data.site}</span>
                  <small>{describeModel(data).label}</small>
                </div>
                <div className="comparison-track-layout">
                  <div className="comparison-lane-labels" aria-hidden="true">
                    {LANES.map((lane) => (
                      <span key={lane.key}>{lane.label}</span>
                    ))}
                  </div>
                  <div
                    className="comparison-tracks"
                    onPointerDown={(event) => {
                      event.currentTarget.setPointerCapture(event.pointerId);
                      moveTo(event);
                    }}
                    onPointerMove={(event) => {
                      if (
                        event.currentTarget.hasPointerCapture(event.pointerId)
                      )
                        moveTo(event);
                    }}
                  >
                    {LANES.map((lane) => (
                      <Lane
                        key={lane.key}
                        label={`Scenario ${slot}: ${lane.label}`}
                        className={lane.className}
                        windows={data.windows[lane.key]}
                        domain={domain}
                        maxHours={maxHours}
                      />
                    ))}
                    {hours < maxHours && (
                      <span
                        className="comparison-outside"
                        style={{ left: `${(hours / maxHours) * 100}%` }}
                        aria-hidden="true"
                      />
                    )}
                    <span
                      className="comparison-shared-cursor"
                      style={{
                        left: `${(Math.min(cursorHours, maxHours) / maxHours) * 100}%`,
                      }}
                      aria-hidden="true"
                    >
                      <i />
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
          <div className="comparison-axis" aria-hidden="true">
            <span />{' '}
            <div>
              {Array.from({ length: 5 }, (_, index) => (
                <span key={index} style={{ left: `${index * 25}%` }}>
                  T+{Number(((maxHours * index) / 4).toFixed(1))} h
                </span>
              ))}
            </div>
          </div>
        </div>
        <p className="comparison-legend">
          <span>
            <i className="sun" />
            Sun visible
          </span>
          <span>
            <i className="earth" />
            Earth visible
          </span>
          <span>
            <i className="both" />
            Sun + Earth visible together
          </span>
          <span>≥ Lower-bound duration at an observation boundary</span>
        </p>
        <div className="comparison-observations">
          {results.map((result) => (
            <CursorReadout
              key={result.slot}
              result={result}
              cursorHours={cursorHours}
            />
          ))}
        </div>
      </div>
      <details className="comparison-advanced">
        <summary>
          Operational metrics &amp; scientific details{' '}
          <span>Inspect the observations ↗</span>
        </summary>
        <div className="comparison-detail-columns">
          {results.map((result) => (
            <AdvancedDetails key={result.slot} result={result} />
          ))}
        </div>
      </details>
    </section>
  );
}

function ScenarioSummary({
  result,
  differences,
}: {
  result: ScenarioResult;
  differences: ReturnType<typeof comparisonInsight>['differences'];
}) {
  const { data, slot, stale } = result;
  const longest = longestOf(data.windows.both, data.metrics.longestBothHrs);
  const metrics = [
    {
      label: 'Sun visibility',
      value: formatPercent(data.metrics.pctSun),
      semantic: 'sun',
      delta: differences?.sun,
    },
    {
      label: 'Earth visibility',
      value: formatPercent(data.metrics.pctEarth),
      semantic: 'earth',
      delta: differences?.earth,
    },
    {
      label: 'Sun + Earth visibility',
      value: formatPercent(data.metrics.pctBoth),
      semantic: 'joint',
      delta: differences?.both,
    },
    {
      label: 'Longest continuous operational window',
      value: formatHours(longest.hours, longest.atLeast),
      semantic: 'duration',
      delta: undefined,
    },
  ];
  return (
    <article className={`comparison-summary${stale ? ' is-stale' : ''}`}>
      <header>
        <div>
          <span className="comparison-slot">{slot}</span>
          <span className="comparison-model">{describeModel(data).label}</span>
        </div>
        <h3>{data.site}</h3>
        <p>
          {data.lat.toFixed(4)}° lat · {data.lon.toFixed(4)}° E ·{' '}
          {formatUtc(data.provenance.ephemeris.startUtc)} –{' '}
          {formatUtc(data.provenance.ephemeris.endUtc)}
        </p>
        {stale && (
          <p className="comparison-stale-note">
            Inputs changed · update results
          </p>
        )}
      </header>
      <dl className="comparison-primary-metrics">
        {metrics.map((metric) => (
          <div
            className={`comparison-primary-metric ${metric.semantic}`}
            key={metric.label}
          >
            <dt>{metric.label}</dt>
            <dd>
              <MotionValue>{metric.value}</MotionValue>
            </dd>
            {metric.delta !== undefined && (
              <small>
                {deltaLabel(
                  slot === 'A' ? metric.delta : -metric.delta,
                  slot === 'A' ? 'B' : 'A',
                )}
              </small>
            )}
          </div>
        ))}
      </dl>
    </article>
  );
}

function deltaLabel(value: number, other: string) {
  if (Math.abs(value) < 1e-6) return `Same share as ${other}`;
  const amount = Math.abs(value) < 0.1 ? '<0.1' : Math.abs(value).toFixed(1);
  return `${value > 0 ? '+' : '−'}${amount} pp vs ${other}`;
}

function Lane({
  label,
  className,
  windows,
  domain,
  maxHours,
}: {
  label: string;
  className: string;
  windows: VisibilityWindow[];
  domain: ReturnType<typeof domainOf>;
  maxHours: number;
}) {
  const scale = domainHours(domain) / maxHours;
  const summary = windows.length
    ? windows
        .map(
          (window) =>
            `${formatUtc(window.startUtc)} to ${formatUtc(window.endUtc)}, ${formatHours(window.durationHrs, window.startTruncated || window.endTruncated)}`,
        )
        .join('; ')
    : 'none in this period';
  return (
    <div
      className="comparison-lane"
      role="img"
      aria-label={`${label}: ${summary}`}
    >
      {segments(windows, domain).map(({ left, width, window }) => (
        <span
          key={window.startUtc}
          className={`comparison-segment ${className}${window.startTruncated ? ' cut-start' : ''}${window.endTruncated ? ' cut-end' : ''}`}
          style={{ left: `${left * scale}%`, width: `${width * scale}%` }}
          title={`${label}: ${formatUtc(window.startUtc)} → ${formatUtc(window.endUtc)} · ${formatHours(window.durationHrs, window.startTruncated || window.endTruncated)}`}
        />
      ))}
    </div>
  );
}

function CursorReadout({
  result,
  cursorHours,
}: {
  result: ScenarioResult;
  cursorHours: number;
}) {
  const { data, slot } = result;
  const cursorMs =
    Date.parse(data.provenance.ephemeris.startUtc) + cursorHours * HOUR_MS;
  const sample =
    cursorMs < Date.parse(data.provenance.ephemeris.endUtc)
      ? sampleAt(data.series, cursorMs, data.calculation.stepMinutes)
      : null;
  return (
    <article className="comparison-observation">
      <header>
        <span className="comparison-slot">{slot}</span>
        <strong>{formatUtc(cursorMs)}</strong>
        <span>{describeModel(data).label}</span>
      </header>
      {sample ? (
        <>
          <p className="comparison-sample-time">
            Observation: {formatUtc(sample.t)} · held for{' '}
            {data.calculation.stepMinutes} min
            {data.horizonMode === 'terrain' &&
              ` · ${data.provenance.terrain.mask.observer.mastHeightM} m mast`}
          </p>
          <div className="comparison-body-readings">
            <p className="sun">
              <span>Sun elevation</span>
              <strong>{sample.sunEl.toFixed(2)}°</strong>
              <span>
                {sample.sunLit ? 'Visible' : 'Hidden'} · disc{' '}
                {sample.sunVisibility}
              </span>
            </p>
            <p className="earth">
              <span>Earth elevation</span>
              <strong>{sample.earthEl.toFixed(2)}°</strong>
              <span>
                {sample.earthVis ? 'Visible' : 'Hidden'} · disc{' '}
                {sample.earthVisibility}
              </span>
            </p>
          </div>
          <details className="comparison-angle-detail">
            <summary>Azimuth &amp; local horizon</summary>
            <p>
              Sun: {sample.sunAz.toFixed(2)}° azimuth,{' '}
              {sample.sunHorizonEl.toFixed(2)}° horizon. Earth:{' '}
              {sample.earthAz.toFixed(2)}° azimuth,{' '}
              {sample.earthHorizonEl.toFixed(2)}° horizon.
            </p>
          </details>
        </>
      ) : (
        <p className="comparison-sample-time">
          Cursor is outside this scenario’s period. No observation is
          extrapolated.
        </p>
      )}
    </article>
  );
}

function AdvancedDetails({ result }: { result: ScenarioResult }) {
  const { data, slot } = result;
  const dark = longestOf(data.windows.darkness, data.metrics.longestDarkHrs);
  const outage = longestOf(
    data.windows.earthBlackout,
    data.metrics.longestEarthBlackoutHrs,
  );
  const sunset = formatSetting(
    data.metrics.nextSunsetBracket,
    data.metrics.asOfUtc,
  );
  const earthset = formatSetting(
    data.metrics.nextEarthsetBracket,
    data.metrics.asOfUtc,
  );
  return (
    <article>
      <h3>
        Scenario {slot} · {data.site}
      </h3>
      <dl className="comparison-secondary-metrics">
        <div>
          <dt>Longest communication outage</dt>
          <dd>{formatHours(outage.hours, outage.atLeast)}</dd>
        </div>
        <div>
          <dt>Longest darkness</dt>
          <dd>{formatHours(dark.hours, dark.atLeast)}</dd>
        </div>
        <div>
          <dt>Next sunset</dt>
          <dd>
            {sunset.value}
            <small>{sunset.detail}</small>
          </dd>
        </div>
        <div>
          <dt>Next Earthset</dt>
          <dd>
            {earthset.value}
            <small>{earthset.detail}</small>
          </dd>
        </div>
      </dl>
      <dl className="comparison-source-list">
        <div>
          <dt>Observer</dt>
          <dd>
            {data.lat}° lat, {data.lon}° E · {data.altitudeKm} km above
            reference sphere
          </dd>
        </div>
        <div>
          <dt>Sampling</dt>
          <dd>
            Every {data.calculation.stepMinutes} minutes · {data.series.length}{' '}
            samples · {data.calculation.visibilityRule}
          </dd>
        </div>
        <div>
          <dt>Horizon</dt>
          <dd>{describeModel(data).detail}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{data.coordinateSource}</dd>
        </div>
      </dl>
      <p className="comparison-method-note">{data.provenance.warning}</p>
      <p className="comparison-method-note">
        Durations use sample-and-hold. Setting brackets are observations, not
        exact event predictions. Visibility does not establish power generation
        or radio-link performance.
      </p>
      {data.horizonMode === 'terrain' && (
        <details className="comparison-source-detail">
          <summary>Mask &amp; DEM provenance</summary>
          <p>{data.provenance.terrain.mask.maskId}</p>
          <p>SHA-256: {data.provenance.terrain.artifactSha256}</p>
          {data.provenance.terrain.mask.provenance.sources.map((source) => (
            <p key={source.productId}>
              {source.productId} · {source.resolutionM} m ·{' '}
              {source.sourceSha256}
            </p>
          ))}
          <p>{data.provenance.terrain.compatibility.limitation}</p>
        </details>
      )}
    </article>
  );
}
