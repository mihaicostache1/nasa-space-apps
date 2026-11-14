import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ReferenceEvaluationDataset } from '@/domain/evaluation';
import type { ScenarioResult } from '@/features/analysis/types';
import {
  compareMissionShift,
  formatDifference,
} from '@/features/mission/lib/shift-comparison';

const fixture: ReferenceEvaluationDataset = JSON.parse(
  readFileSync(
    new URL('./fixtures/reference-evaluation-site01.json', import.meta.url),
    'utf8',
  ),
);
const original = (): ScenarioResult => ({
  slot: 'A',
  data: structuredClone(fixture),
  stale: false,
});
const revised = (): ScenarioResult => ({
  slot: 'B',
  data: structuredClone(fixture),
  stale: false,
});

describe('mission-shift comparison', () => {
  it('reports percentage-point differences rather than relative percentage changes', () => {
    const a = original();
    const b = revised();
    // Controlled percentages test presentation arithmetic, not NASA predictions.
    a.data.metrics.pctEarth = 40;
    b.data.metrics.pctEarth = 50;
    a.data.metrics.pctBoth = 30;
    b.data.metrics.pctBoth = 20;
    const result = compareMissionShift([b, a]);
    expect(
      result?.metrics.find((metric) => metric.key === 'earth')?.differencePp,
    ).toBe(10);
    expect(
      result?.metrics.find((metric) => metric.key === 'joint')?.differencePp,
    ).toBe(-10);
    expect(result?.hours).toBe(720);
  });
  it('supports a reset to the original interval with zero difference', () => {
    expect(
      compareMissionShift([original(), revised()])?.metrics.every(
        (metric) => metric.differencePp === 0,
      ),
    ).toBe(true);
  });
  it('does not compare missing or stale responses', () => {
    expect(compareMissionShift([original()])).toBeNull();
    expect(
      compareMissionShift([original(), { ...revised(), stale: true }]),
    ).toBeNull();
  });
  it('rejects different sites, observer geometry, durations, rules, or cadence', () => {
    const changes: ((value: ScenarioResult) => void)[] = [
      (value) => {
        value.data.siteId = 'different';
      },
      (value) => {
        value.data.altitudeKm += 0.002;
      },
      (value) => {
        value.data.lat += 0.001;
      },
      (value) => {
        value.data.metrics.evaluatedHrs = 24;
      },
      (value) => {
        value.data.calculation.stepMinutes = 120;
      },
      (value) => {
        value.data.calculation.visibilityRule = 'full-disc';
      },
    ];
    for (const change of changes) {
      const b = revised();
      change(b);
      expect(compareMissionShift([original(), b])).toBeNull();
    }
  });
  it('formats small, zero and negative changes without misleading signs', () => {
    expect(formatDifference(10)).toBe('+10.0 pp');
    expect(formatDifference(-5.15)).toBe('-5.2 pp');
    expect(formatDifference(-0.001)).toBe('0.0 pp');
  });
});
