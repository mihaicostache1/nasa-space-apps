import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ReferenceEvaluationDataset } from '@/domain/evaluation';
import { formatSetting } from '@/features/analysis/lib/timeline';

// A real POST /api/reference/evaluations response for Site01 (30 days, hourly).
const site01: ReferenceEvaluationDataset = JSON.parse(
  readFileSync(
    new URL('./fixtures/reference-evaluation-site01.json', import.meta.url),
    'utf8',
  ),
);

describe('next setting countdowns', () => {
  it('reports no sunset when the Sun never sets in the period', () => {
    expect(
      formatSetting(site01.metrics.nextSunsetBracket, site01.metrics.asOfUtc),
    ).toEqual({ value: 'None observed', detail: 'No setting in this period' });
  });

  it('brackets the real Earthset between two hourly observations', () => {
    expect(
      formatSetting(site01.metrics.nextEarthsetBracket, site01.metrics.asOfUtc),
    ).toEqual({
      value: 'T+391–392 h',
      detail: '2026-11-30 07:00–08:00 UTC',
    });
    expect(site01.metrics.hoursToEarthset).toBe(392);
  });

  it('spells out both dates when the bracket crosses midnight', () => {
    expect(
      formatSetting(
        { afterUtc: '2026-11-14T22:00:00Z', byUtc: '2026-11-15T04:00:00Z' },
        '2026-11-14T00:00:00Z',
      ),
    ).toEqual({
      value: 'T+22–28 h',
      detail: '2026-11-14 22:00 – 2026-11-15 04:00 UTC',
    });
  });
});
