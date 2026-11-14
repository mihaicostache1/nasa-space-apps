import {
  formatHours,
  formatPercent,
  HOUR_MS,
  longestOf,
  sampleAt,
} from '@/features/analysis/lib/timeline';
import type { ScenarioResult } from '@/features/analysis/types';
import { MotionValue } from './experience-motion';

export function MissionInsights({
  result,
  cursorHours,
}: {
  result?: ScenarioResult;
  cursorHours: number;
}) {
  if (!result)
    return (
      <aside className="mission-insights">
        <p className="eyebrow">MISSION INSIGHTS</p>
        <p className="hint">
          Verified results will appear here after evaluation.
        </p>
      </aside>
    );
  const { data } = result;
  const sample = sampleAt(
    data.series,
    Date.parse(data.provenance.ephemeris.startUtc) + cursorHours * HOUR_MS,
    data.calculation.stepMinutes,
  );
  const both = longestOf(data.windows.both, data.metrics.longestBothHrs);
  return (
    <aside
      className={`mission-insights${result.stale ? ' is-stale' : ''}`}
      aria-label="Selected mission insights"
    >
      <p className="eyebrow">MISSION INSIGHTS / {result.slot}</p>
      <h3>
        Your window,
        <br />
        at a glance.
      </h3>
      <div className="insight-feature">
        <span className="micro-label">LONGEST JOINT WINDOW</span>
        <strong>
          <MotionValue>{formatHours(both.hours, both.atLeast)}</MotionValue>
        </strong>
        <p>
          Sun and Earth visible together
          {both.atLeast ? ' · clipped by this period' : ''}.
        </p>
      </div>
      <dl className="insight-stats">
        <div className="sun">
          <dt>Sun visible</dt>
          <dd>
            <MotionValue>{formatPercent(data.metrics.pctSun)}</MotionValue>
          </dd>
        </div>
        <div className="earth">
          <dt>Earth visible</dt>
          <dd>
            <MotionValue>{formatPercent(data.metrics.pctEarth)}</MotionValue>
          </dd>
        </div>
        <div>
          <dt>Joint availability</dt>
          <dd>
            <MotionValue>{formatPercent(data.metrics.pctBoth)}</MotionValue>
          </dd>
        </div>
      </dl>
      <div className="instant-status">
        <span className="micro-label">AT THE PLAYHEAD</span>
        <p>
          <i className={sample?.sunLit ? 'sun-dot' : 'off-dot'} />
          Sun{' '}
          {sample ? (sample.sunLit ? 'visible' : 'occluded') : 'outside period'}
        </p>
        <p>
          <i className={sample?.earthVis ? 'earth-dot' : 'off-dot'} />
          Earth{' '}
          {sample
            ? sample.earthVis
              ? 'visible'
              : 'occluded'
            : 'outside period'}
        </p>
      </div>
      <p className="instrument-note">
        {data.calculation.stepMinutes}-minute observations. Visibility is
        geometry; it does not establish power output or radio-link performance.
      </p>
      {data.horizonMode === 'terrain' && (
        <p className="instrument-note warning-text">
          0 m reference mast · approximate Mean Earth frame pairing. No frame
          transformation applied.
        </p>
      )}
      {result.stale && (
        <p className="issue">
          Inputs changed. Apply the controls to refresh these results.
        </p>
      )}
    </aside>
  );
}
