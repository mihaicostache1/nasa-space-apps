'use client';

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type PointerEvent,
} from 'react';
import type { CustomEvaluation } from '@/domain/custom-evaluation';
import { ApiError, evaluateCustom } from '@/lib/api-client';
import {
  domainOf,
  formatHours,
  formatPercent,
  formatSetting,
  formatUtc,
  HOUR_MS,
  longestOf,
  sampleAt,
  segments,
} from '@/features/analysis/lib/timeline';
import {
  customErrorTitle,
  customRequest,
  defaultCustomForm,
  type CustomForm,
} from '../lib/form';

export function CustomEvaluationWorkspace() {
  const [form, setForm] = useState<CustomForm>(defaultCustomForm);
  const [issues, setIssues] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState('');
  const [completed, setCompleted] = useState<{
    data: CustomEvaluation;
    key: string;
  } | null>(null);
  const [cursor, setCursor] = useState(0);
  const inFlight = useRef<AbortController | null>(null);
  useEffect(() => () => inFlight.current?.abort(), []);
  const key = JSON.stringify(customRequest(form).request ?? form);
  const stale = Boolean(completed && completed.key !== key);

  function change(next: Partial<CustomForm>) {
    if (inFlight.current) {
      inFlight.current.abort();
      inFlight.current = null;
      setPending(false);
    }
    setForm((current) => ({ ...current, ...next }));
    setIssues([]);
    setError(null);
    setNotice('');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const selected = customRequest(form);
    setIssues(selected.issues);
    if (!selected.request) return;
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setPending(true);
    setError(null);
    setNotice('');
    const requestKey = JSON.stringify(selected.request);
    try {
      const data = await evaluateCustom(selected.request, controller.signal);
      if (controller.signal.aborted) return;
      setCompleted({ data, key: requestKey });
      setCursor(0);
      setNotice('Evaluation complete. Results match this observer and period.');
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(
        cause instanceof ApiError
          ? cause
          : new ApiError('Unexpected evaluation failure. Please retry.', 0),
      );
    } finally {
      if (!controller.signal.aborted) {
        setPending(false);
        inFlight.current = null;
      }
    }
  }

  const field = (
    name: keyof Pick<
      CustomForm,
      'latitude' | 'longitude' | 'height' | 'ground' | 'start' | 'end' | 'step'
    >,
    label: string,
    props: {
      type?: string;
      min?: number | string;
      max?: number | string;
      step?: string;
      required?: boolean;
    } = {},
  ) => (
    <label htmlFor={`custom-${name}`}>
      {label}
      <input
        id={`custom-${name}`}
        name={name}
        type={props.type ?? 'number'}
        value={form[name]}
        step={props.step ?? (props.type === 'datetime-local' ? '60' : 'any')}
        {...props}
        onChange={(event) => change({ [name]: event.target.value })}
        aria-describedby="custom-form-issues"
      />
    </label>
  );

  return (
    <section
      className="custom-evaluation"
      id="evaluate"
      aria-labelledby="custom-heading"
    >
      <header className="section-heading">
        <div>
          <p className="eyebrow">Evaluate / Your coordinates</p>
          <h2 id="custom-heading">A specific place. Your perspective.</h2>
          <p className="section-copy">
            Evaluate sunlight and Earth visibility for an exact lunar observer.
          </p>
        </div>
        <span className="custom-source-label">
          NASA/JPL Horizons · On request
        </span>
      </header>
      <div className="custom-evaluation-grid">
        <form
          className="custom-configuration"
          onSubmit={(event) => void submit(event)}
          noValidate
          aria-describedby="custom-form-description"
        >
          <div
            className="custom-mode"
            role="group"
            aria-label="Custom evaluation mode"
          >
            <button
              type="button"
              aria-pressed={form.mode === 'geometric'}
              onClick={() => change({ mode: 'geometric', accepted: false })}
            >
              Geometric
            </button>
            <button
              type="button"
              aria-pressed={form.mode === 'terrain'}
              onClick={() => change({ mode: 'terrain', accepted: false })}
            >
              Terrain-aware
            </button>
          </div>
          <p id="custom-form-description" className="hint">
            {form.mode === 'geometric'
              ? 'Evaluate Sun and Earth visibility using celestial geometry and a flat horizon.'
              : 'Include local horizon obstruction using available elevation data.'}
          </p>
          <div className="custom-fields">
            {field('latitude', 'Lunar latitude (°)', {
              min: -90,
              max: 90,
              required: true,
            })}
            {field('longitude', 'East longitude (°)', {
              min: -180,
              max: 180,
              required: true,
            })}
          </div>
          {field('height', 'Observer height above ground (m)', {
            min: 0,
            max: 1000,
            required: true,
          })}
          <p className="custom-input-note">
            Use negative latitude for south and negative east longitude for
            west.
          </p>
          {form.mode === 'geometric' ? (
            <>
              {field('ground', 'Ground elevation above reference sphere (m)', {
                min: -20000,
                max: 20000,
                required: true,
              })}
              <p className="custom-input-note">
                Required to locate the observer above the 1737.4 km lunar
                sphere. Enter a known elevation; this mode does not verify local
                terrain.
              </p>
            </>
          ) : (
            <div className="custom-terrain-note">
              <strong>Coverage checked on evaluation</strong>
              <p>
                South-polar DEMs support locations within 60–90°S where every
                horizon ray has data. Your deployment must have terrain enabled.
                No geometric fallback is used.
              </p>
              <p>
                Ground elevation is derived from the DEM. Generated terrain is
                preliminary.
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.accepted}
                  onChange={(event) =>
                    change({ accepted: event.target.checked })
                  }
                />
                <span>
                  I accept the approximate DE421 MOON_ME / Horizons Mean Earth
                  pairing. No frame transformation is applied.
                </span>
              </label>
            </div>
          )}
          <div className="custom-fields">
            {field('start', 'Start (UTC)', {
              type: 'datetime-local',
              min: '2000-01-01T00:00',
              max: '2039-12-31T23:59',
              required: true,
            })}
            {field('end', 'End (UTC, excluded)', {
              type: 'datetime-local',
              min: '2000-01-01T00:01',
              max: '2040-01-01T00:00',
              required: true,
            })}
          </div>
          <label htmlFor="custom-step">
            Sample interval
            <select
              id="custom-step"
              value={form.step}
              onChange={(event) => change({ step: event.target.value })}
            >
              {[15, 30, 60, 120, 360, 720, 1440].map((value) => (
                <option key={value} value={value}>
                  {value < 60
                    ? `${value} minutes`
                    : `${value / 60} ${value === 60 ? 'hour' : 'hours'}`}
                </option>
              ))}
            </select>
          </label>
          <p className="custom-input-note">
            Up to 31 days and 744 samples. Visibility uses the any-disc rule.
            All dates and observations are UTC.
          </p>
          <div id="custom-form-issues" aria-live="polite">
            {issues.length > 0 && (
              <ul className="custom-issues">
                {issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="custom-submit-row">
            <button type="submit" disabled={pending}>
              {pending ? 'Evaluating observer…' : 'Evaluate coordinates'}
              <span aria-hidden="true"> →</span>
            </button>
            {pending && (
              <button
                type="button"
                onClick={() => {
                  inFlight.current?.abort();
                  inFlight.current = null;
                  setPending(false);
                  setNotice('Request cancelled. No new result has been shown.');
                }}
              >
                Cancel request
              </button>
            )}
          </div>
          <p className="custom-service-note">
            Custom acquisition may be disabled on this deployment. The verified
            reference explorer remains available.
          </p>
        </form>
        <div className="custom-result-area" aria-busy={pending}>
          <div aria-live="polite" className="custom-evaluation-status">
            {pending
              ? 'Retrieving or verifying Horizons samples for this observer. Terrain requests also verify elevation data and trace the horizon.'
              : notice}
          </div>
          {error && (
            <div className="custom-error" role="alert">
              <h3>{customErrorTitle(error)}</h3>
              <p>{error.message}</p>
              <p>
                {error.code === 'custom_disabled' || error.status === 404
                  ? 'Use a verified reference location, or ask the deployment owner to enable custom evaluation.'
                  : 'Your selected evaluation mode is unchanged. Review the inputs or retry when the service is available.'}
              </p>
              <a href="#explore">Explore reference locations →</a>
            </div>
          )}
          {stale && (
            <p className="custom-stale" role="status">
              Inputs changed. The previous result below belongs to its recorded
              observer and period. Evaluate again to update it.
            </p>
          )}
          {!completed && !pending && !error && (
            <div className="custom-empty">
              <span className="custom-observer-diagram" aria-hidden="true">
                <i />
                <b />
              </span>
              <p className="eyebrow">Your observer, precisely defined</p>
              <h3>Start with a place on the Moon.</h3>
              <p>
                Enter coordinates and observer height. After evaluation, inspect
                visibility, shared Sun–Earth windows, and every source behind
                the result.
              </p>
              <span>No evaluation runs until you submit.</span>
            </div>
          )}
          {!completed && pending && (
            <div className="custom-empty">
              <span className="custom-loading-mark" aria-hidden="true" />
              <h3>Following two lines of sight.</h3>
              <p>
                Waiting for verified Sun and Earth observations. No result is
                estimated while the request is in progress.
              </p>
            </div>
          )}
          {completed && (
            <CustomResults
              data={completed.data}
              stale={stale}
              cursor={cursor}
              onCursor={setCursor}
            />
          )}
        </div>
      </div>
    </section>
  );
}

const lanes = [
  { key: 'sunlit', label: 'Sun visible', tone: 'sun' },
  { key: 'earthVisible', label: 'Earth visible', tone: 'earth' },
  { key: 'both', label: 'Sun + Earth', tone: 'both' },
] as const;

function CustomResults({
  data,
  stale,
  cursor,
  onCursor,
}: {
  data: CustomEvaluation;
  stale: boolean;
  cursor: number;
  onCursor: (value: number) => void;
}) {
  const source = data.provenance.ephemeris;
  const domain = domainOf(source.startUtc, source.endUtc);
  const hours = data.metrics.evaluatedHrs;
  const stepHours = data.calculation.stepMinutes / 60;
  const max = Math.max(0, (data.series.length - 1) * stepHours);
  const selected = sampleAt(
    data.series,
    domain.startMs + cursor * HOUR_MS,
    data.calculation.stepMinutes,
  );
  const longest = longestOf(data.windows.both, data.metrics.longestBothHrs);
  const sunset = formatSetting(
    data.metrics.nextSunsetBracket,
    data.metrics.asOfUtc,
  );
  const earthset = formatSetting(
    data.metrics.nextEarthsetBracket,
    data.metrics.asOfUtc,
  );
  function scrub(event: PointerEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const next =
      Math.floor(
        (Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)) *
          hours) /
          stepHours,
      ) * stepHours;
    onCursor(Math.min(max, Math.max(0, next)));
  }
  return (
    <article
      className={`custom-completed${stale ? ' is-stale' : ''}`}
      aria-label="Custom observer results"
    >
      <header className="custom-result-header">
        <span>
          {data.horizonMode === 'terrain'
            ? 'Preliminary terrain evaluation'
            : 'Geometric evaluation'}
        </span>
        <p>
          {data.observer.lat.toFixed(5)}° latitude ·{' '}
          {data.observer.lon.toFixed(5)}° east longitude ·{' '}
          {data.observer.mastHeightM} m above ground
        </p>
        <p>
          {formatUtc(source.startUtc)} → {formatUtc(source.endUtc)}
        </p>
      </header>
      <dl className="custom-primary-metrics">
        <div className="custom-sun">
          <dt>Sun visibility</dt>
          <dd>{formatPercent(data.metrics.pctSun)}</dd>
        </div>
        <div className="custom-earth">
          <dt>Earth visibility</dt>
          <dd>{formatPercent(data.metrics.pctEarth)}</dd>
        </div>
        <div>
          <dt>Sun + Earth visibility</dt>
          <dd>{formatPercent(data.metrics.pctBoth)}</dd>
        </div>
        <div>
          <dt>Longest joint window</dt>
          <dd>{formatHours(longest.hours, longest.atLeast)}</dd>
        </div>
      </dl>
      <section
        className="custom-timeline"
        aria-labelledby="custom-timeline-heading"
      >
        <h3 id="custom-timeline-heading">Visibility through your period</h3>
        <p className="hint">
          Selected observations use sample-and-hold. Event times are bounded by
          the {source.stepMinutes}-minute cadence.
        </p>
        <div className="custom-timeline-rows">
          {lanes.map((lane) => (
            <div className="custom-timeline-row" key={lane.key}>
              <span>{lane.label}</span>
              <div
                className="custom-track"
                onPointerDown={(event) => {
                  event.currentTarget.setPointerCapture(event.pointerId);
                  scrub(event);
                }}
                onPointerMove={(event) => {
                  if (event.currentTarget.hasPointerCapture(event.pointerId))
                    scrub(event);
                }}
                role="img"
                aria-label={`${lane.label}: ${data.windows[lane.key].length} observed windows`}
              >
                {segments(data.windows[lane.key], domain).map((item) => (
                  <span
                    className={`custom-track-fill custom-${lane.tone}`}
                    key={item.window.startUtc}
                    style={{ left: `${item.left}%`, width: `${item.width}%` }}
                    title={`${formatUtc(item.window.startUtc)} → ${formatUtc(item.window.endUtc)}; ${formatHours(item.window.durationHrs, item.window.startTruncated || item.window.endTruncated)}`}
                  />
                ))}
                <i
                  className="custom-playhead"
                  style={{ left: `${(cursor / hours) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
        <label className="custom-cursor">
          Inspect time · T+{cursor.toFixed(1)} h
          <input
            type="range"
            min={0}
            max={max}
            step={stepHours}
            value={cursor}
            onChange={(event) => onCursor(event.target.valueAsNumber)}
            aria-label="Custom observer timeline cursor"
          />
        </label>
        <div className="custom-time-readout">
          <strong>
            {selected ? formatUtc(selected.t) : 'Outside the observed period'}
          </strong>
          {selected && (
            <>
              <span className="custom-sun">
                Sun {selected.sunEl.toFixed(2)}° elevation ·{' '}
                {selected.sunLit ? 'visible' : 'hidden'} (
                {selected.sunVisibility} disc)
              </span>
              <span className="custom-earth">
                Earth {selected.earthEl.toFixed(2)}° elevation ·{' '}
                {selected.earthVis ? 'visible' : 'hidden'} (
                {selected.earthVisibility} disc)
              </span>
            </>
          )}
        </div>
        <p className="hint">
          Hatched overlap means Sun and Earth are visible together. Grey tracks
          mean no visible interval under the selected rule.
        </p>
      </section>
      <section className="custom-windows">
        <h3>Time with Sun and Earth</h3>
        {data.windows.both.length ? (
          <ol>
            {data.windows.both.slice(0, 4).map((window) => (
              <li key={window.startUtc}>
                <span>
                  {formatUtc(window.startUtc)} → {formatUtc(window.endUtc)}
                </span>
                <strong>
                  {formatHours(
                    window.durationHrs,
                    window.startTruncated || window.endTruncated,
                  )}
                </strong>
                {(window.startTruncated || window.endTruncated) && (
                  <small>
                    Clipped by the evaluation period; actual duration may be
                    longer.
                  </small>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p>No joint visibility window was observed in this period.</p>
        )}
        {data.windows.both.length > 4 && (
          <p className="hint">
            Showing the first 4 of {data.windows.both.length} windows.
          </p>
        )}
      </section>
      <details className="custom-technical">
        <summary>Observer, sources & scientific detail</summary>
        <dl>
          <div>
            <dt>Ground elevation / reference sphere</dt>
            <dd>{data.observer.surfaceElevationM} m / 1737.4 km radius</dd>
          </div>
          <div>
            <dt>Total observer altitude</dt>
            <dd>{data.observer.altitudeKm} km</dd>
          </div>
          <div>
            <dt>Longest darkness</dt>
            <dd>
              {formatHours(
                data.metrics.longestDarkHrs,
                longestOf(data.windows.darkness, data.metrics.longestDarkHrs)
                  .atLeast,
              )}
            </dd>
          </div>
          <div>
            <dt>Longest Earth blackout</dt>
            <dd>
              {formatHours(
                data.metrics.longestEarthBlackoutHrs,
                longestOf(
                  data.windows.earthBlackout,
                  data.metrics.longestEarthBlackoutHrs,
                ).atLeast,
              )}
            </dd>
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
        <p>{data.observer.coordinateSource}</p>
        <p>{data.provenance.warning}</p>
        <p className="custom-source-hash">
          Ephemeris SHA-256 <code>{data.provenance.ephemerisSha256}</code>
        </p>
        {data.provenance.terrain && (
          <>
            <p>{data.provenance.terrain.compatibility.limitation}</p>
            <p>
              Generated mask: <code>{data.provenance.terrain.mask.maskId}</code>
            </p>
            <p className="custom-source-hash">
              Mask SHA-256 <code>{data.provenance.terrain.maskSha256}</code>
            </p>
            <p className="custom-source-hash">
              Profile SHA-256{' '}
              <code>{data.provenance.terrain.profileSha256}</code>
            </p>
            <ul>
              {data.provenance.terrain.mask.provenance.sources.map((item) => (
                <li key={item.productId}>
                  <a href={item.sourceUrl} target="_blank" rel="noreferrer">
                    {item.productId}
                  </a>{' '}
                  · {item.resolutionM} m resolution
                  <code className="custom-source-hash">
                    {item.sourceSha256}
                  </code>
                </li>
              ))}
            </ul>
          </>
        )}
        <ul>
          {source.requests.map((item, index) => (
            <li key={`${item.target}-${index}`}>
              <a href={item.sourceUrl} target="_blank" rel="noreferrer">
                {item.target === 'sun' ? 'Sun' : 'Earth'} · original Horizons
                request
              </a>
              <span>Retrieved {item.retrievedAtUtc}</span>
              <code className="custom-source-hash">{item.responseSha256}</code>
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}
