import type { ScenarioResult } from '@/features/analysis/types';

/** A comparison is meaningful only for matching geometry, rules and interval lengths. */
export function compareMissionShift(results: ScenarioResult[]) {
  const original = results.find((result) => result.slot === 'A');
  const revised = results.find((result) => result.slot === 'B');
  if (!original || !revised || original.stale || revised.stale) return null;
  const a = original.data;
  const b = revised.data;
  if (
    a.siteId !== b.siteId ||
    a.lat !== b.lat ||
    a.lon !== b.lon ||
    a.altitudeKm !== b.altitudeKm ||
    a.horizonMode !== b.horizonMode ||
    a.calculation.visibilityRule !== b.calculation.visibilityRule ||
    a.calculation.stepMinutes !== b.calculation.stepMinutes ||
    a.metrics.evaluatedHrs !== b.metrics.evaluatedHrs ||
    (a.horizonMode === 'terrain' &&
      b.horizonMode === 'terrain' &&
      a.provenance.terrain.artifactSha256 !==
        b.provenance.terrain.artifactSha256)
  )
    return null;
  return {
    site: a.site,
    hours: a.metrics.evaluatedHrs,
    startOriginal: a.provenance.ephemeris.startUtc,
    startRevised: b.provenance.ephemeris.startUtc,
    metrics: [
      {
        key: 'sun',
        label: 'Sunlight',
        original: a.metrics.pctSun,
        revised: b.metrics.pctSun,
      },
      {
        key: 'earth',
        label: 'Earth visibility',
        original: a.metrics.pctEarth,
        revised: b.metrics.pctEarth,
      },
      {
        key: 'joint',
        label: 'Joint availability',
        original: a.metrics.pctBoth,
        revised: b.metrics.pctBoth,
      },
    ].map((metric) => ({
      ...metric,
      differencePp: metric.revised - metric.original,
    })),
  };
}

export function formatDifference(value: number) {
  const rounded =
    (Math.sign(value) * Math.round((Math.abs(value) + Number.EPSILON) * 10)) /
    10;
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)} pp`;
}
