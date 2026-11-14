'use client';

import { useRef, type PointerEvent } from 'react';
import type { VisibilitySample, VisibilityWindow } from '@/domain/evaluation';
import {
  HOUR_MS,
  dayTicks,
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
  { key: 'sunlit', label: 'Sun visible', className: 'sun' },
  { key: 'earthVisible', label: 'Earth visible', className: 'earth' },
  { key: 'both', label: 'Both visible', className: 'both' },
] as const;

export function ComparisonTimeline({
  results,
  cursorHours,
  onCursorChange,
}: Props) {
  const maxHours = Math.max(
    ...results.map(({ data }) =>
      domainHours(
        domainOf(
          data.provenance.ephemeris.startUtc,
          data.provenance.ephemeris.endUtc,
        ),
      ),
    ),
  );
  const step =
    Math.min(...results.map(({ data }) => data.calculation.stepMinutes)) / 60;
  return (
    <section className="analysis" aria-labelledby="timeline-heading">
      <div className="section-heading">
        <h2 id="timeline-heading">Visibility timeline</h2>
        <span className="hint">
          Shared cursor: hours elapsed from each scenario&apos;s start
        </span>
      </div>
      <label className="cursor-control">
        Cursor T+{cursorHours} h
        <input
          type="range"
          min={0}
          max={Math.max(0, maxHours - step)}
          step={step}
          value={cursorHours}
          onChange={(event) => onCursorChange(event.target.valueAsNumber)}
        />
      </label>
      {results.map((result) => (
        <ScenarioTimeline
          key={result.slot}
          result={result}
          cursorHours={cursorHours}
          onCursorChange={onCursorChange}
        />
      ))}
      <p className="legend">
        <span className="swatch sun" /> Sun visible{' '}
        <span className="swatch earth" /> Earth visible{' '}
        <span className="swatch both" /> Both (power and direct-to-Earth link
        geometry) <span className="swatch truncated" /> continues beyond the
        selected period
      </p>
    </section>
  );
}

function ScenarioTimeline({
  result,
  cursorHours,
  onCursorChange,
}: {
  result: ScenarioResult;
  cursorHours: number;
  onCursorChange: (hours: number) => void;
}) {
  const { data, slot, stale } = result;
  const { startUtc, endUtc } = data.provenance.ephemeris;
  const domain = domainOf(startUtc, endUtc);
  const hours = domainHours(domain);
  const stepHours = data.calculation.stepMinutes / 60;
  const tracks = useRef<HTMLDivElement>(null);
  const cursorMs = domain.startMs + cursorHours * HOUR_MS;
  const inRange = cursorMs < domain.endMs;
  const sample = inRange
    ? sampleAt(data.series, cursorMs, data.calculation.stepMinutes)
    : null;
  const longestBoth = longestOf(data.windows.both, data.metrics.longestBothHrs);
  const longestOutage = longestOf(
    data.windows.earthBlackout,
    data.metrics.longestEarthBlackoutHrs,
  );
  const longestDark = longestOf(
    data.windows.darkness,
    data.metrics.longestDarkHrs,
  );
  const sunset = formatSetting(
    data.metrics.nextSunsetBracket,
    data.metrics.asOfUtc,
  );
  const earthset = formatSetting(
    data.metrics.nextEarthsetBracket,
    data.metrics.asOfUtc,
  );

  function moveTo(event: PointerEvent<HTMLDivElement>) {
    const box = tracks.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const fraction = Math.min(
      Math.max((event.clientX - box.left) / box.width, 0),
      1,
    );
    const snapped = Math.floor((fraction * hours) / stepHours) * stepHours;
    onCursorChange(Math.min(snapped, hours - stepHours));
  }

  return (
    <article className={`timeline panel${stale ? ' is-stale' : ''}`}>
      <header>
        <h3>
          <span className="slot">{slot}</span> {data.site}
        </h3>
        <p className="hint">
          {formatUtc(startUtc)} – {formatUtc(endUtc)} · every {stepHours} h
          {stale && ' · inputs changed, results not updated'}
        </p>
      </header>
      <dl className="stats">
        <Stat label="Sun visible" value={formatPercent(data.metrics.pctSun)} />
        <Stat
          label="Earth visible"
          value={formatPercent(data.metrics.pctEarth)}
        />
        <Stat label="Both" value={formatPercent(data.metrics.pctBoth)} />
        <Stat
          label="Longest simultaneous operation"
          value={formatHours(longestBoth.hours, longestBoth.atLeast)}
          accent
        />
        <Stat
          label="Longest communication outage"
          value={formatHours(longestOutage.hours, longestOutage.atLeast)}
        />
        <Stat
          label="Longest darkness"
          value={formatHours(longestDark.hours, longestDark.atLeast)}
        />
        <Stat label="Next sunset" {...sunset} />
        <Stat label="Next Earthset" {...earthset} />
      </dl>
      <div className="lanes">
        <div className="lane-labels" aria-hidden="true">
          {LANES.map((lane) => (
            <span key={lane.key}>{lane.label}</span>
          ))}
        </div>
        <div
          className="lane-tracks"
          ref={tracks}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            moveTo(event);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              moveTo(event);
          }}
        >
          {LANES.map((lane) => (
            <Lane
              key={lane.key}
              label={lane.label}
              className={lane.className}
              windows={data.windows[lane.key]}
              domain={domain}
            />
          ))}
          {inRange && (
            <div
              className="cursor"
              style={{ left: `${(cursorHours / hours) * 100}%` }}
              aria-hidden="true"
            />
          )}
          <div className="ticks" aria-hidden="true">
            {dayTicks(domain).map((tick) => (
              <span
                key={tick.label}
                className={tick.minor ? 'minor' : undefined}
                style={{ left: `${tick.left}%` }}
              >
                {tick.label}
              </span>
            ))}
          </div>
        </div>
      </div>
      <CursorReadout sample={sample} cursorMs={cursorMs} inRange={inRange} />
    </article>
  );
}

function Lane({
  label,
  className,
  windows,
  domain,
}: {
  label: string;
  className: string;
  windows: VisibilityWindow[];
  domain: ReturnType<typeof domainOf>;
}) {
  const summary = windows.length
    ? windows
        .map(
          (w) =>
            `${formatUtc(w.startUtc)} to ${formatUtc(w.endUtc)} (${formatHours(w.durationHrs, w.startTruncated || w.endTruncated)})`,
        )
        .join('; ')
    : 'none in this period';
  return (
    <div className="lane" role="img" aria-label={`${label}: ${summary}`}>
      {segments(windows, domain).map(({ left, width, window }) => (
        <span
          key={window.startUtc}
          className={`segment ${className}${window.startTruncated ? ' cut-start' : ''}${window.endTruncated ? ' cut-end' : ''}`}
          style={{ left: `${left}%`, width: `${width}%` }}
          title={`${formatUtc(window.startUtc)} → ${formatUtc(window.endUtc)} · ${formatHours(window.durationHrs, window.startTruncated || window.endTruncated)}`}
        />
      ))}
    </div>
  );
}

function CursorReadout({
  sample,
  cursorMs,
  inRange,
}: {
  sample: VisibilitySample | null;
  cursorMs: number;
  inRange: boolean;
}) {
  if (!inRange || !sample) {
    return (
      <p className="readout hint">
        Cursor is outside this scenario&apos;s period.
      </p>
    );
  }
  return (
    <p className="readout" aria-live="polite">
      <strong>{formatUtc(cursorMs)}</strong>
      <span>
        Sun {sample.sunEl.toFixed(2)}° elev, {sample.sunAz.toFixed(1)}° az ·{' '}
        {sample.sunLit ? 'visible' : 'hidden'}
      </span>
      <span>
        Earth {sample.earthEl.toFixed(2)}° elev, {sample.earthAz.toFixed(1)}° az
        · {sample.earthVis ? 'visible' : 'hidden'}
      </span>
    </p>
  );
}

function Stat({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: string;
  /** Smaller second line, e.g. the UTC bracket behind a countdown. */
  detail?: string;
  accent?: boolean;
}) {
  return (
    <div className={accent ? 'accent' : undefined}>
      <dt>{label}</dt>
      <dd>
        {value}
        {detail && <small>{detail}</small>}
      </dd>
    </div>
  );
}
