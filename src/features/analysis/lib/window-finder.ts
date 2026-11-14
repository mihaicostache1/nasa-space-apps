import type { VisibilityWindow } from '@/domain/evaluation';

export type MissionWindow = VisibilityWindow & {
  /** True when the real duration may be longer than shown (cut by the period). */
  atLeast: boolean;
  isLongest: boolean;
};

export type MissionWindowSort = 'longest' | 'earliest';

/**
 * Combined Sun + Earth windows (`windows.both`) lasting at least `minHours`.
 * A window cut by the period edge is kept: its true length is at least its shown length.
 */
export function findMissionWindows(
  both: VisibilityWindow[],
  longestBothHrs: number,
  minHours: number,
  sort: MissionWindowSort = 'longest',
): MissionWindow[] {
  const rows = both
    .filter((window) => window.durationHrs + 1e-9 >= minHours)
    .map((window) => ({
      ...window,
      atLeast: window.startTruncated || window.endTruncated,
      isLongest: Math.abs(window.durationHrs - longestBothHrs) < 1e-6,
    }));
  return rows.sort((a, b) =>
    sort === 'longest'
      ? b.durationHrs - a.durationHrs || a.startUtc.localeCompare(b.startUtc)
      : a.startUtc.localeCompare(b.startUtc),
  );
}
