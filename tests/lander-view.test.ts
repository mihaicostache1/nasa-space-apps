import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { ReferenceEvaluationDataset } from '@/domain/evaluation';
import {
  angleDelta,
  cameraElevation,
  createSkyTrack,
  discAgainstSkyline,
  earthIllumination,
  horizonElAt,
  lerpAngle,
  project,
  skyDrift,
  starAzimuth,
} from '@/features/analysis/lib/lander-view';

// A real POST /api/reference/evaluations response for Site01 (30 days, hourly).
const site01: ReferenceEvaluationDataset = JSON.parse(
  readFileSync(
    new URL('./fixtures/reference-evaluation-site01.json', import.meta.url),
    'utf8',
  ),
);
const HOUR = 3_600_000;

describe('angles', () => {
  it('takes the short way round north', () => {
    expect(angleDelta(359, 1)).toBeCloseTo(2);
    expect(angleDelta(1, 359)).toBeCloseTo(-2);
    expect(angleDelta(0, 180)).toBe(180);
    expect(lerpAngle(359, 1, 0.5)).toBeCloseTo(0);
    expect(lerpAngle(350, 10, 0.25)).toBeCloseTo(355);
  });

  it('interpolates the horizon circularly between 359° and 0°', () => {
    const horizon = Array.from({ length: 360 }, (_, az) => ({
      az,
      el: az === 359 ? 2 : az === 0 ? 4 : 0,
    }));
    expect(horizonElAt(horizon, 359.5)).toBeCloseTo(3);
    expect(horizonElAt(horizon, -0.5)).toBeCloseTo(3);
    expect(horizonElAt(horizon, 0)).toBe(4);
  });
});

describe('sky track', () => {
  const at = createSkyTrack(site01.series, site01.calculation.stepMinutes);
  const [first, second] = site01.series;
  const t0 = Date.parse(first.t);

  it('returns the observation itself at a sample time', () => {
    const state = at(t0)!;
    expect(state.sun.az).toBeCloseTo(first.sunAz);
    expect(state.earth.el).toBeCloseTo(first.earthEl);
    expect(state.earth.radiusDeg).toBe(first.earthAngularRadiusDeg);
  });

  it('interpolates positions but holds the model flags between samples', () => {
    const state = at(t0 + HOUR / 2)!;
    expect(state.earth.el).toBeCloseTo((first.earthEl + second.earthEl) / 2);
    expect(state.sun.az).toBeCloseTo(lerpAngle(first.sunAz, second.sunAz, 0.5));
    expect(state.earth.visible).toBe(first.earthVis);
    expect(state.sun.visibility).toBe(first.sunVisibility);
  });

  it('is empty outside the evaluated period', () => {
    const end = Date.parse(site01.provenance.ephemeris.endUtc);
    expect(at(t0 - 1)).toBeNull();
    expect(at(end)).toBeNull();
    expect(at(end - 1)).not.toBeNull();
  });
});

describe('Earth phase seen from the Moon', () => {
  const earth = { az: 135, el: 0 };

  it('is full with the Sun behind the observer and new beside Earth', () => {
    expect(earthIllumination({ az: 315, el: 0 }, earth).fraction).toBeCloseTo(
      1,
    );
    expect(earthIllumination({ az: 135, el: 0 }, earth).fraction).toBeCloseTo(
      0,
    );
    const quarter = earthIllumination({ az: 225, el: 0 }, earth);
    expect(quarter.fraction).toBeCloseTo(0.5);
    expect(quarter.elongationDeg).toBeCloseTo(90);
  });

  it('lights the side of the disc that faces the Sun', () => {
    // Larger azimuth is to the right in a view facing the horizon.
    expect(earthIllumination({ az: 225, el: 0 }, earth).bearingDeg).toBeCloseTo(
      90,
    );
    expect(earthIllumination({ az: 45, el: 0 }, earth).bearingDeg).toBeCloseTo(
      270,
    );
    expect(
      earthIllumination({ az: 135, el: 30 }, earth).bearingDeg,
    ).toBeCloseTo(0);
  });
});

describe('sky rotation', () => {
  it('turns the stars the same way the Sun drifts in the real data', () => {
    // The Sun's azimuth decreases by about 0.51° per hour at the south pole.
    expect(skyDrift(site01.series)).toBe(-1);
    expect(starAzimuth(100, 655.72 / 4, -1)).toBeCloseTo(10);
  });
});

describe('camera', () => {
  const camera = { az: 358, el: 1, pxPerDeg: 20, width: 800, height: 400 };

  it('projects across north without jumping', () => {
    expect(project(camera, 358, 1)).toEqual({ x: 400, y: 200 });
    expect(project(camera, 2, 1).x).toBeCloseTo(480);
    expect(project(camera, 354, 0)).toEqual({ x: 320, y: 220 });
  });

  it('keeps the 0° horizon in frame while following a body', () => {
    const viewHeightDeg = 20;
    for (const el of [-8, -2, 0, 4, 11]) {
      const centre = cameraElevation(el, viewHeightDeg);
      expect(Math.abs(centre)).toBeLessThan(viewHeightDeg / 2);
      expect(Math.abs(el - centre)).toBeLessThan(viewHeightDeg / 2);
    }
  });

  it('classifies a disc against the local skyline', () => {
    const flat = Array.from({ length: 360 }, (_, az) => ({ az, el: 0 }));
    expect(discAgainstSkyline({ az: 10, el: 1, radiusDeg: 0.27 }, flat)).toBe(
      'full',
    );
    expect(discAgainstSkyline({ az: 10, el: 0.1, radiusDeg: 0.27 }, flat)).toBe(
      'partial',
    );
    expect(discAgainstSkyline({ az: 10, el: -1, radiusDeg: 0.27 }, flat)).toBe(
      'hidden',
    );
  });
});
