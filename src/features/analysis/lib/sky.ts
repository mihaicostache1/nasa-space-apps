import type { VisibilitySample } from '@/domain/evaluation';

export type Body = 'sun' | 'earth';
export type SkyPoint = { az: number; el: number; visible: boolean };

/**
 * A body's track as polylines in azimuth/elevation. Azimuth runs clockwise from
 * local north; a jump of more than 180° means the track crossed north (360 → 0),
 * so the line is split there instead of being drawn across the whole chart.
 */
export function trackSegments(
  series: VisibilitySample[],
  body: Body,
): SkyPoint[][] {
  const result: SkyPoint[][] = [];
  let current: SkyPoint[] = [];
  let previous: SkyPoint | null = null;
  for (const sample of series) {
    const point: SkyPoint =
      body === 'sun'
        ? { az: sample.sunAz, el: sample.sunEl, visible: sample.sunLit }
        : { az: sample.earthAz, el: sample.earthEl, visible: sample.earthVis };
    if (previous && Math.abs(point.az - previous.az) > 180) {
      result.push(current);
      current = [];
    }
    current.push(point);
    previous = point;
  }
  if (current.length) result.push(current);
  return result;
}

/** Elevation axis bounds covering tracks and horizon, padded to whole degrees. */
export function elevationBounds(
  series: VisibilitySample[],
  horizon: { el: number }[],
): [number, number] {
  const values = [
    ...series.flatMap((s) => [s.sunEl, s.earthEl]),
    ...horizon.map((point) => point.el),
    0,
  ];
  const low = Math.floor(Math.min(...values) - 1);
  const high = Math.ceil(Math.max(...values) + 1);
  return [low, Math.max(high, low + 2)];
}

export const COMPASS = [
  { az: 0, label: 'N' },
  { az: 90, label: 'E' },
  { az: 180, label: 'S' },
  { az: 270, label: 'W' },
  { az: 360, label: 'N' },
];

/**
 * Split a track into consecutive runs of equal visibility. Each run repeats the
 * previous run's last point so the drawn line stays continuous.
 */
export function visibilityRuns(
  points: SkyPoint[],
): { visible: boolean; points: SkyPoint[] }[] {
  const runs: { visible: boolean; points: SkyPoint[] }[] = [];
  for (const point of points) {
    const last = runs.at(-1);
    if (last && last.visible === point.visible) {
      last.points.push(point);
    } else {
      const bridge = last ? [last.points.at(-1)!] : [];
      runs.push({ visible: point.visible, points: [...bridge, point] });
    }
  }
  return runs;
}

/** A readable elevation tick spacing for the given range. */
export function elevationStep(low: number, high: number): number {
  const span = high - low;
  return span <= 8 ? 1 : span <= 20 ? 2 : span <= 50 ? 5 : 10;
}
