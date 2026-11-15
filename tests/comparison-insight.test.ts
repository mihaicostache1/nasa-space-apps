import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ReferenceEvaluationDataset } from '@/domain/evaluation';
import type { ScenarioResult } from '@/features/analysis/types';
import { comparisonInsight } from '@/features/analysis/lib/comparison-insight';

const fixture: ReferenceEvaluationDataset = JSON.parse(
  readFileSync(
    new URL('./fixtures/reference-evaluation-site01.json', import.meta.url),
    'utf8',
  ),
);
function pair(): [ScenarioResult, ScenarioResult] {
  return [
    { slot: 'A', stale: false, data: structuredClone(fixture) },
    { slot: 'B', stale: false, data: structuredClone(fixture) },
  ];
}

describe('scientific comparison insights', () => {
  it('reports metric equality without manufacturing an overall winner', () => {
    const result = comparisonInsight(pair());
    expect(result.comparable).toBe(true);
    expect(result.differences).toEqual({ sun: 0, earth: 0, both: 0 });
    expect(result.longestWindowLeader).toBeNull();
    expect(result.description).toContain('not an overall mission ranking');
  });
  it('describes an actual sunlight/Earth trade-off rather than sunlight continuity', () => {
    const scenarios = pair();
    // Controlled metric inputs exercise interpretation; these are not production results.
    scenarios[0].data.metrics.pctSun = 80;
    scenarios[1].data.metrics.pctSun = 60;
    scenarios[0].data.metrics.pctEarth = 40;
    scenarios[1].data.metrics.pctEarth = 70;
    const result = comparisonInsight(scenarios);
    expect(result.title).toContain('trade-off');
    expect(result.description).toContain(
      'Scenario A has a higher sunlight share',
    );
    expect(result.description).toContain(
      'scenario B has a higher Earth-visibility share',
    );
    expect(result.differences).toMatchObject({ sun: 20, earth: -30 });
    expect(result.description).not.toContain('sunlight continuity');
  });
  it('suppresses direct differences when UTC periods differ even for equal durations', () => {
    const scenarios = pair();
    scenarios[1].data.provenance.ephemeris.startUtc = '2026-11-15T00:00:00Z';
    scenarios[1].data.provenance.ephemeris.endUtc = '2026-12-15T00:00:00Z';
    const result = comparisonInsight(scenarios);
    expect(result.comparable).toBe(false);
    expect(result.differences).toBeNull();
    expect(result.description).toContain(
      'elapsed hours, not absolute timestamps',
    );
  });
  it('rejects different cadence, different disc rules, stale data, or missing slots', () => {
    const cadence = pair();
    cadence[1].data.calculation.stepMinutes = 120;
    expect(comparisonInsight(cadence).comparable).toBe(false);
    const rules = pair();
    rules[1].data.calculation.visibilityRule = 'full-disc';
    expect(comparisonInsight(rules).comparable).toBe(false);
    const stale = pair();
    stale[0].stale = true;
    expect(comparisonInsight(stale).differences).toBeNull();
    expect(comparisonInsight([pair()[0]]).comparable).toBe(false);
  });
  it('never ranks a clipped longest window against a complete interval', () => {
    const scenarios = pair();
    const longest = scenarios[0].data.windows.both.find(
      (window) =>
        window.durationHrs === scenarios[0].data.metrics.longestBothHrs,
    )!;
    longest.endTruncated = true;
    scenarios[1].data.metrics.longestBothHrs = 20;
    const result = comparisonInsight(scenarios);
    expect(result.longestWindowLeader).toBeNull();
    expect(result.description).toContain('lower bounds');
  });
  it('ranks complete continuous windows using observed durations', () => {
    const scenarios = pair();
    scenarios[1].data.metrics.longestBothHrs = 20;
    scenarios[1].data.windows.both = [
      {
        startUtc: '2026-11-18T00:00:00Z',
        endUtc: '2026-11-18T20:00:00Z',
        durationHrs: 20,
        startTruncated: false,
        endTruncated: false,
      },
    ];
    expect(comparisonInsight(scenarios).longestWindowLeader).toBe('A');
    expect(comparisonInsight(scenarios).description).toContain(
      'Scenario A has the longer observed continuous joint window',
    );
  });
  it('keeps an unknown bound when equal longest windows include a clipped interval', () => {
    const scenarios = pair();
    const hours = scenarios[0].data.metrics.longestBothHrs;
    const complete = scenarios[0].data.windows.both.find(
      (window) => window.durationHrs === hours,
    )!;
    scenarios[0].data.windows.both = [
      { ...complete, startTruncated: false, endTruncated: false },
      { ...complete, startTruncated: true, endTruncated: false },
    ];
    expect(comparisonInsight(scenarios).longestWindowLeader).toBeNull();
    expect(comparisonInsight(scenarios).description).toContain('lower bounds');
  });
});
