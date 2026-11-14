import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type {
  ReferenceEvaluationDataset,
  VisibilitySample,
  VisibilityWindow,
} from '@/domain/evaluation';
import {
  dayTicks,
  domainOf,
  formatHours,
  longestOf,
  sampleAt,
  segments,
} from '@/features/analysis/lib/timeline';
import { findMissionWindows } from '@/features/analysis/lib/window-finder';
import {
  elevationBounds,
  trackSegments,
  visibilityRuns,
} from '@/features/analysis/lib/sky';

// A real POST /api/reference/evaluations response for Site01 (30 days, hourly).
const site01: ReferenceEvaluationDataset = JSON.parse(
  readFileSync(
    new URL('./fixtures/reference-evaluation-site01.json', import.meta.url),
    'utf8',
  ),
);

const window = (
  startUtc: string,
  endUtc: string,
  durationHrs: number,
  startTruncated = false,
  endTruncated = false,
): VisibilityWindow => ({
  startUtc,
  endUtc,
  durationHrs,
  startTruncated,
  endTruncated,
});

describe('timeline geometry', () => {
  const domain = domainOf('2026-11-14T00:00:00Z', '2026-11-15T00:00:00Z');

  it('places windows as clipped percentages of the period', () => {
    const result = segments(
      [
        window('2026-11-14T06:00:00Z', '2026-11-14T12:00:00Z', 6),
        window('2026-11-14T18:00:00Z', '2026-11-15T06:00:00Z', 12, false, true),
      ],
      domain,
    );
    expect(result.map(({ left, width }) => [left, width])).toEqual([
      [25, 25],
      [75, 25],
    ]);
  });

  it('matches the backend windows for real Site01 data', () => {
    const real = domainOf(
      site01.provenance.ephemeris.startUtc,
      site01.provenance.ephemeris.endUtc,
    );
    const [both] = segments(site01.windows.both, real);
    expect(both.window.durationHrs).toBe(site01.metrics.longestBothHrs);
    expect(both.width).toBeCloseTo((312 / 720) * 100, 6);
  });

  it('holds each observation until the next sample (sample-and-hold)', () => {
    const series = site01.series as VisibilitySample[];
    const start = Date.parse(series[0].t);
    expect(sampleAt(series, start, 60)?.t).toBe(series[0].t);
    expect(sampleAt(series, start + 59 * 60_000, 60)?.t).toBe(series[0].t);
    expect(sampleAt(series, start + 60 * 60_000, 60)?.t).toBe(series[1].t);
    expect(sampleAt(series, start - 1, 60)).toBeNull();
    expect(sampleAt(series, start + 720 * 3_600_000, 60)).toBeNull();
  });

  it('marks a longest interval cut by the period as "at least"', () => {
    const outage = longestOf(
      site01.windows.earthBlackout,
      site01.metrics.longestEarthBlackoutHrs,
    );
    expect(outage).toEqual({ hours: 328, atLeast: true });
    expect(formatHours(outage.hours, outage.atLeast)).toBe('≥ 328 h (13.7 d)');
    const both = longestOf(site01.windows.both, site01.metrics.longestBothHrs);
    expect(both.atLeast).toBe(false);
    expect(formatHours(0)).toBe('0 h');
    expect(formatHours(6.25)).toBe('6.3 h');
  });

  it('thins day ticks to a readable count', () => {
    const month = domainOf('2026-11-14T00:00:00Z', '2026-12-14T00:00:00Z');
    const ticks = dayTicks(month, 8);
    expect(ticks.length).toBeLessThanOrEqual(8);
    expect(ticks[0]).toEqual({ left: 0, label: '11-14', minor: false });
  });
});

describe('mission window finder', () => {
  const both = [
    window('2026-11-14T00:00:00Z', '2026-11-15T00:00:00Z', 24, true),
    window('2026-11-16T00:00:00Z', '2026-11-19T00:00:00Z', 72),
    window('2026-11-20T00:00:00Z', '2026-11-20T10:00:00Z', 10),
  ];

  it('filters by minimum duration and ranks the longest first', () => {
    const rows = findMissionWindows(both, 72, 24);
    expect(rows.map((r) => r.durationHrs)).toEqual([72, 24]);
    expect(rows[0].isLongest).toBe(true);
    expect(rows[1].atLeast).toBe(true);
  });

  it('can list chronologically and returns nothing when none qualify', () => {
    expect(
      findMissionWindows(both, 72, 0, 'earliest').map((r) => r.startUtc),
    ).toEqual(both.map((w) => w.startUtc));
    expect(findMissionWindows(both, 72, 100)).toEqual([]);
  });

  it('uses the backend windows directly for real data', () => {
    const rows = findMissionWindows(
      site01.windows.both,
      site01.metrics.longestBothHrs,
      24,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      startUtc: '2026-11-17T08:00:00Z',
      endUtc: '2026-11-30T08:00:00Z',
      durationHrs: 312,
      isLongest: true,
      atLeast: false,
    });
  });
});

describe('sky explorer geometry', () => {
  const sample = (sunAz: number, sunLit = true): VisibilitySample => ({
    t: '2026-11-14T00:00:00Z',
    sunAz,
    sunEl: 1,
    earthAz: 0,
    earthEl: -1,
    sunAngularRadiusDeg: 0.27,
    earthAngularRadiusDeg: 0.9,
    sunHorizonEl: 0,
    earthHorizonEl: 0,
    sunVisibility: sunLit ? 'full' : 'hidden',
    earthVisibility: 'hidden',
    sunLit,
    earthVis: false,
  });

  it('splits a track where it crosses north instead of drawing across the chart', () => {
    const tracks = trackSegments(
      [sample(350), sample(355), sample(2), sample(8)],
      'sun',
    );
    expect(tracks.map((t) => t.map((p) => p.az))).toEqual([
      [350, 355],
      [2, 8],
    ]);
  });

  it('keeps a real month-long Sun track continuous apart from north crossings', () => {
    const tracks = trackSegments(site01.series, 'sun');
    const points = tracks.reduce((n, t) => n + t.length, 0);
    expect(points).toBe(site01.series.length);
    // The Sun circles the sky about once per 29.5-day synodic month.
    expect(tracks.length).toBeGreaterThanOrEqual(2);
    expect(tracks.length).toBeLessThanOrEqual(3);
  });

  it('splits runs by visibility with a shared boundary point', () => {
    const runs = visibilityRuns(
      trackSegments(
        [sample(10), sample(20, false), sample(30, false), sample(40)],
        'sun',
      )[0],
    );
    expect(runs.map((r) => [r.visible, r.points.map((p) => p.az)])).toEqual([
      [true, [10]],
      [false, [10, 20, 30]],
      [true, [30, 40]],
    ]);
  });

  it('covers the tracks and the horizon in the elevation range', () => {
    const [low, high] = elevationBounds(site01.series, site01.horizon);
    const els = site01.series.flatMap((s) => [s.sunEl, s.earthEl]);
    expect(low).toBeLessThan(Math.min(...els));
    expect(high).toBeGreaterThan(Math.max(...els));
    expect(low).toBeLessThanOrEqual(0);
  });
});
