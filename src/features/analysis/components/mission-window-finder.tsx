'use client';

import { useState } from 'react';
import { HOUR_MS, formatHours, formatUtc } from '../lib/timeline';
import {
  findMissionWindows,
  type MissionWindowSort,
} from '../lib/window-finder';
import type { ScenarioResult } from '../types';

type Props = {
  results: ScenarioResult[];
  onJump: (hours: number) => void;
};

/** Periods with the Sun and Earth both visible: candidate surface-operation windows. */
export function MissionWindowFinder({ results, onJump }: Props) {
  const [minHours, setMinHours] = useState(24);
  const [sort, setSort] = useState<MissionWindowSort>('longest');
  return (
    <section className="analysis" aria-labelledby="finder-heading" data-reveal>
      <div className="section-heading">
        <h2 id="finder-heading">Mission window finder</h2>
        <span className="hint">
          Sun and Earth visible together, from the backend&apos;s windows
        </span>
      </div>
      <div className="finder-controls">
        <label>
          Minimum duration (hours)
          <input
            type="number"
            min={0}
            step={1}
            value={Number.isNaN(minHours) ? '' : minHours}
            onChange={(event) => setMinHours(event.target.valueAsNumber)}
          />
        </label>
        <label>
          Order
          <select
            value={sort}
            onChange={(event) =>
              setSort(event.target.value as MissionWindowSort)
            }
          >
            <option value="longest">Longest first</option>
            <option value="earliest">Earliest first</option>
          </select>
        </label>
      </div>
      <div className="finder-grid">
        {results.map(({ slot, data, stale }) => {
          const rows = findMissionWindows(
            data.windows.both,
            data.metrics.longestBothHrs,
            Number.isNaN(minHours) ? 0 : minHours,
            sort,
          );
          const start = Date.parse(data.provenance.ephemeris.startUtc);
          return (
            <article className={`panel${stale ? ' is-stale' : ''}`} key={slot}>
              <h3>
                <span className="slot">{slot}</span> {data.site}
              </h3>
              <p className="hint">
                {rows.length} of {data.windows.both.length} window
                {data.windows.both.length === 1 ? '' : 's'} last at least{' '}
                {Number.isNaN(minHours) ? 0 : minHours} h · longest{' '}
                {formatHours(data.metrics.longestBothHrs)}
              </p>
              {rows.length === 0 ? (
                <p className="empty">
                  No window meets this duration. Lower the minimum or choose
                  other dates.
                </p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Opens</th>
                      <th scope="col">Closes</th>
                      <th scope="col">Duration</th>
                      <th scope="col">
                        <span className="visually-hidden">
                          Show on timeline
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr
                        key={row.startUtc}
                        className={row.isLongest ? 'longest' : undefined}
                      >
                        <td>
                          {formatUtc(row.startUtc)}
                          {row.startTruncated && (
                            <small>open at period start</small>
                          )}
                        </td>
                        <td>
                          {formatUtc(row.endUtc)}
                          {row.endTruncated && (
                            <small>still open at period end</small>
                          )}
                        </td>
                        <td>
                          {formatHours(row.durationHrs, row.atLeast)}
                          {row.isLongest && <small>longest</small>}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="link-button"
                            onClick={() =>
                              onJump(
                                (Date.parse(row.startUtc) - start) / HOUR_MS,
                              )
                            }
                          >
                            Show
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </article>
          );
        })}
      </div>
      <p className="hint">
        Edges are bracketed by the sampling interval: the actual opening and
        closing can each be up to one step earlier than shown. &quot;≥&quot;
        marks windows cut by the selected period, whose true length is unknown.
      </p>
    </section>
  );
}
