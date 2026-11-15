import type { ScenarioResult, Slot } from '../types';
import { longestOf } from './timeline';

export function comparisonInsight(results: ScenarioResult[]): {
  comparable: boolean;
  title: string;
  description: string;
  differences: { sun: number; earth: number; both: number } | null;
  longestWindowLeader: Slot | null;
} {
  const a = results.find((r) => r.slot === 'A');
  const b = results.find((r) => r.slot === 'B');
  const unavailable = (title: string, description: string) => ({
    comparable: false,
    title,
    description,
    differences: null,
    longestWindowLeader: null,
  });
  if (!a || !b)
    return unavailable(
      'Choose two scenarios',
      'Evaluate both scenarios to inspect their differences.',
    );
  if (a.stale || b.stale)
    return unavailable(
      'Update the comparison',
      'Inputs have changed. Update the results before interpreting their differences.',
    );
  const pa = a.data.provenance.ephemeris;
  const pb = b.data.provenance.ephemeris;
  if (
    Date.parse(pa.startUtc) !== Date.parse(pb.startUtc) ||
    Date.parse(pa.endUtc) !== Date.parse(pb.endUtc)
  )
    return unavailable(
      'Two periods, one elapsed-time view',
      'These scenarios cover different UTC periods. The cursor aligns elapsed hours, not absolute timestamps. Direct differences are hidden.',
    );
  if (
    a.data.calculation.stepMinutes !== b.data.calculation.stepMinutes ||
    a.data.calculation.visibilityRule !== b.data.calculation.visibilityRule
  )
    return unavailable(
      'Different evaluation settings',
      'Match sampling intervals and disc rules to show direct differences. The timeline still aligns elapsed hours.',
    );
  const differences = {
    sun: a.data.metrics.pctSun - b.data.metrics.pctSun,
    earth: a.data.metrics.pctEarth - b.data.metrics.pctEarth,
    both: a.data.metrics.pctBoth - b.data.metrics.pctBoth,
  };
  const leader = (delta: number): Slot | null =>
    Math.abs(delta) < 1e-6 ? null : delta > 0 ? 'A' : 'B';
  const sun = leader(differences.sun),
    earth = leader(differences.earth),
    both = leader(differences.both);
  const wa = longestOf(a.data.windows.both, a.data.metrics.longestBothHrs),
    wb = longestOf(b.data.windows.both, b.data.metrics.longestBothHrs);
  const longestWindowLeader =
    wa.atLeast || wb.atLeast ? null : leader(wa.hours - wb.hours);
  const phrases = [
    sun
      ? `Scenario ${sun} has a higher sunlight share`
      : 'Sunlight shares are equal',
    earth
      ? `scenario ${earth} has a higher Earth-visibility share`
      : 'Earth-visibility shares are equal',
  ];
  return {
    comparable: true,
    title:
      sun && earth && sun !== earth
        ? 'Different strengths. A visible trade-off.'
        : both
          ? `Scenario ${both} has more joint visibility`
          : 'Similar joint visibility. Inspect the windows.',
    description: `${phrases.join('; ')}. This is a visibility comparison, not an overall mission ranking.${a.data.horizonMode !== b.data.horizonMode ? ' Horizon models differ.' : ''}${wa.atLeast || wb.atLeast ? ' Boundary-clipped longest windows are lower bounds and are not ranked.' : longestWindowLeader ? ` Scenario ${longestWindowLeader} has the longer observed continuous joint window.` : ''}`,
    differences,
    longestWindowLeader,
  };
}
