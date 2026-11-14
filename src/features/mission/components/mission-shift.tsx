'use client';

import { useState } from 'react';
import type { ReferenceSite } from '@/domain/reference';
import type { ScenarioResult } from '@/features/analysis/types';
import { formatUtc } from '@/features/analysis/lib/timeline';
import { compareMissionShift, formatDifference } from '../lib/shift-comparison';
import { MotionValue } from './experience-motion';
import {
  missionShift,
  validateForm,
  type ReferenceScenarioForm,
} from '@/features/scenarios/lib/reference-scenario';

export function MissionShift({
  form,
  site,
  disabled,
  onApply,
  results,
  comparisonState,
}: {
  form: ReferenceScenarioForm;
  site: ReferenceSite;
  disabled: boolean;
  onApply: (forms: ReferenceScenarioForm[]) => void;
  results: ScenarioResult[];
  comparisonState: 'idle' | 'loading' | 'ready' | 'stale' | 'error';
}) {
  const [days, setDays] = useState(7);
  const [duration, setDuration] = useState(1);
  const datesValid =
    /^\d{4}-\d{2}-\d{2}$/.test(form.startDate) &&
    Number.isFinite(Date.parse(form.startDate));
  const pair = datesValid ? missionShift(form, days, duration) : null;
  const comparison = compareMissionShift(results);
  const comparisonMatches =
    comparison &&
    pair &&
    comparison.startOriginal.slice(0, 10) === pair.original.startDate &&
    comparison.startRevised.slice(0, 10) === pair.revised.startDate &&
    comparison.hours === duration * 24;
  const issues = pair
    ? [
        ...validateForm(pair.original, site),
        ...validateForm(pair.revised, site),
      ]
    : ['Select a valid original mission date.'];
  const unavailable = (offset: number) =>
    !datesValid ||
    validateForm(
      {
        ...missionShift(form, offset, duration).revised,
        horizonMode: 'geometric',
      },
      site,
    ).length > 0;
  return (
    <section
      className="shift-section"
      aria-labelledby="shift-heading"
      data-reveal
    >
      <div>
        <p className="eyebrow">A CHANGE OF PLANS</p>
        <h2 id="shift-heading">What if your mission shifts?</h2>
        <p className="section-copy">
          Same site. A different date. Compare two equal mission intervals using
          the archived observations.
        </p>
      </div>
      <div className="shift-console">
        <div className="shift-dates">
          <div>
            <span className="micro-label">ORIGINAL · SCENARIO A</span>
            <strong>{form.startDate || 'Choose a date'}</strong>
          </div>
          <span className="shift-arrow" aria-hidden="true">
            →
          </span>
          <div>
            <span className="micro-label">REVISED · SCENARIO B</span>
            <strong>
              <MotionValue>{pair?.revised.startDate ?? '—'}</MotionValue>
            </strong>
          </div>
        </div>
        <label>
          Mission duration
          <select
            value={duration}
            onChange={(event) => setDuration(Number(event.target.value))}
          >
            {[1, 3, 7].map((value) => (
              <option key={value} value={value}>
                {value * 24} hours
              </option>
            ))}
          </select>
        </label>
        <label>
          Shift mission date · +{days} days
          <input
            type="range"
            min={0}
            max={42}
            step={1}
            value={days}
            onChange={(event) => setDays(event.target.valueAsNumber)}
          />
        </label>
        <div className="shift-presets">
          {[7, 30, 42].map((value) => (
            <button
              type="button"
              className="quiet-button"
              key={value}
              disabled={unavailable(value)}
              title={
                unavailable(value) ? 'Outside the verified archive' : undefined
              }
              aria-describedby="shift-coverage"
              aria-pressed={days === value}
              onClick={() => setDays(value)}
            >
              {value === 42 ? '+6 WEEKS' : `+${value} DAYS`}
            </button>
          ))}
          <button
            className="quiet-button"
            type="button"
            onClick={() => setDays(0)}
          >
            RESET
          </button>
        </div>
        <p
          id="shift-coverage"
          className={issues.length ? 'issue' : 'hint'}
          role="status"
        >
          {issues.length
            ? `Comparison unavailable: ${[...new Set(issues)].join(' ')}`
            : `Compare ${duration * 24}-hour windows at ${site.name}. Applying replaces both scenarios.`}{' '}
          Coverage: {site.availability.startUtc.slice(0, 10)} to{' '}
          {site.availability.endUtc.slice(0, 10)} (end excluded). A six-week
          shift requires a longer archive.
        </p>
        <button
          type="button"
          disabled={disabled || !!issues.length}
          onClick={() => pair && onApply([pair.original, pair.revised])}
        >
          Simulate mission shift <span aria-hidden="true">↗</span>
        </button>
      </div>
      <div
        className="shift-result-region"
        aria-live="polite"
        aria-busy={comparisonState === 'loading'}
      >
        {comparisonState === 'ready' && comparisonMatches ? (
          <div className="shift-results">
            <div className="shift-result-heading">
              <div>
                <span className="micro-label">
                  THE DIFFERENCE / VERIFIED OBSERVATIONS
                </span>
                <h3>Your mission, before and after.</h3>
              </div>
              <span className="model-tag">
                {comparison.hours} h / SAME SITE
              </span>
            </div>
            <p className="hint">
              {comparison.site} · {formatUtc(comparison.startOriginal)} →{' '}
              {formatUtc(comparison.startRevised)}. Availability within each
              selected interval.
            </p>
            <dl>
              {comparison.metrics.map((metric) => (
                <div
                  key={metric.key}
                  className={`shift-metric ${metric.key}`}
                  data-metric={metric.key}
                >
                  <dt>{metric.label}</dt>
                  <dd>
                    <span className="metric-before">
                      {metric.original.toFixed(1)}%
                    </span>
                    <span className="metric-arrow" aria-hidden="true">
                      →
                    </span>
                    <strong className="metric-after">
                      <MotionValue>{`${metric.revised.toFixed(1)}%`}</MotionValue>
                    </strong>
                  </dd>
                  <p className="metric-difference">
                    <MotionValue>
                      {formatDifference(metric.differencePp)}
                    </MotionValue>
                    <span>percentage points</span>
                  </p>
                </div>
              ))}
            </dl>
            <p className="hint">
              Changes describe sample-based visibility, not power or link
              performance. Clipped-window durations remain lower bounds in the
              timeline.
            </p>
          </div>
        ) : comparisonState === 'loading' ? (
          <p className="shift-state">
            Comparing the original and revised observations…
          </p>
        ) : comparisonState === 'error' ? (
          <p className="issue">
            The comparison could not complete. Check the scenario errors and
            retry.
          </p>
        ) : comparisonState !== 'idle' ? (
          <p className="shift-state">
            Inputs changed. Simulate the shift again to refresh its comparison.
          </p>
        ) : (
          <p className="shift-state">
            Apply a supported shift to see the change in sunlight, Earth
            visibility, and joint availability.
          </p>
        )}
      </div>
    </section>
  );
}
