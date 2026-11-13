import { describe, expect, it } from 'vitest';
import { scenarioSchema, type Scenario } from '@/domain/scenario';

const valid: Scenario = {
  name: 'South pole example',
  location: { latitudeDeg: -89, longitudeDeg: 0, altitudeKm: 0 },
  startUtc: '2026-11-14T00:00:00Z',
  endUtc: '2026-11-15T00:00:00Z',
  stepMinutes: 60,
};

describe('scenario input contract', () => {
  it('accepts a bounded lunar scenario in UTC', () => {
    expect(scenarioSchema.safeParse(valid).success).toBe(true);
  });

  it.each([
    { ...valid, location: { ...valid.location, latitudeDeg: -91 } },
    { ...valid, location: { ...valid.location, longitudeDeg: 181 } },
    { ...valid, location: { ...valid.location, altitudeKm: Number.NaN } },
    { ...valid, startUtc: '2026-11-14T00:00:00' },
    { ...valid, startUtc: '2026-11-14T00:00:00+02:00' },
    { ...valid, endUtc: valid.startUtc },
    { ...valid, endUtc: '2026-11-13T00:00:00Z' },
    { ...valid, endUtc: '2027-01-01T00:00:00Z' },
    { ...valid, stepMinutes: 0 },
    { ...valid, stepMinutes: 1, endUtc: '2026-12-01T00:00:00Z' },
  ])(
    'rejects invalid coordinates, time ranges, or sample bounds (%#)',
    (scenario) => {
      expect(scenarioSchema.safeParse(scenario).success).toBe(false);
    },
  );
});
