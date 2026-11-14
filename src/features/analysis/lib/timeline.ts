import type { VisibilitySample, VisibilityWindow } from '@/domain/evaluation';

export const HOUR_MS = 3_600_000;

export type Domain = { startMs: number; endMs: number };

export function domainOf(startUtc: string, endUtc: string): Domain {
  return { startMs: Date.parse(startUtc), endMs: Date.parse(endUtc) };
}

export function domainHours(domain: Domain): number {
  return (domain.endMs - domain.startMs) / HOUR_MS;
}

export type Segment = {
  left: number;
  width: number;
  window: VisibilityWindow;
};

/** Window positions as percentages of the domain, clipped to it. */
export function segments(
  windows: VisibilityWindow[],
  domain: Domain,
): Segment[] {
  const span = domain.endMs - domain.startMs;
  return windows.flatMap((window) => {
    const start = Math.max(Date.parse(window.startUtc), domain.startMs);
    const end = Math.min(Date.parse(window.endUtc), domain.endMs);
    if (end <= start) return [];
    return [
      {
        left: ((start - domain.startMs) / span) * 100,
        width: ((end - start) / span) * 100,
        window,
      },
    ];
  });
}

/** The observation in effect at `timeMs` (sample-and-hold), or null outside the series. */
export function sampleAt(
  series: VisibilitySample[],
  timeMs: number,
  stepMinutes: number,
): VisibilitySample | null {
  let low = 0;
  let high = series.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (Date.parse(series[mid].t) <= timeMs) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  if (found < 0) return null;
  const sample = series[found];
  return timeMs < Date.parse(sample.t) + stepMinutes * 60_000 ? sample : null;
}

/** A "longest" duration plus whether the matching window is cut by the period edge. */
export function longestOf(
  windows: VisibilityWindow[],
  longestHrs: number,
): { hours: number; atLeast: boolean } {
  const match = windows.find(
    (window) => Math.abs(window.durationHrs - longestHrs) < 1e-6,
  );
  return {
    hours: longestHrs,
    atLeast: Boolean(match && (match.startTruncated || match.endTruncated)),
  };
}

export function formatHours(hours: number, atLeast = false): string {
  const prefix = atLeast ? '≥ ' : '';
  if (hours === 0) return '0 h';
  const rounded = Number.isInteger(hours) ? hours : Number(hours.toFixed(1));
  return hours >= 48
    ? `${prefix}${rounded} h (${(hours / 24).toFixed(1)} d)`
    : `${prefix}${rounded} h`;
}

export function formatUtc(timeMs: number | string): string {
  const date = new Date(
    typeof timeMs === 'string' ? Date.parse(timeMs) : timeMs,
  );
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

export function formatPercent(value: number): string {
  return `${value.toFixed(value >= 10 || value === 0 ? 0 : 1)}%`;
}

/** Day ticks for an axis, as percentages; thinned to at most `maxTicks`. */
export function dayTicks(
  domain: Domain,
  maxTicks = 8,
): { left: number; label: string; minor: boolean }[] {
  const span = domain.endMs - domain.startMs;
  const firstDay = Math.ceil(domain.startMs / (24 * HOUR_MS)) * 24 * HOUR_MS;
  const days: number[] = [];
  for (let t = firstDay; t <= domain.endMs; t += 24 * HOUR_MS) days.push(t);
  const stride = Math.max(1, Math.ceil(days.length / maxTicks));
  return days
    .filter((_, index) => index % stride === 0)
    .map((t, index) => ({
      left: ((t - domain.startMs) / span) * 100,
      label: new Date(t).toISOString().slice(5, 10),
      // Every other tick is hidden on narrow screens.
      minor: index % 2 === 1,
    }));
}
