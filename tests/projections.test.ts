import { describe, expect, it } from 'vitest';
import { skyPosition, polarPosition } from '@/features/mission/lib/projections';

describe('scientific display projections', () => {
  it('places local north up, east right, zenith at centre, and negative elevations outside 0°', () => {
    expect(skyPosition(0, 90)).toEqual({ x: 240, y: 240 });
    expect(skyPosition(0, 0).y).toBeLessThan(240);
    expect(skyPosition(90, 0).x).toBeGreaterThan(240);
    expect(skyPosition(180, 0).y).toBeGreaterThan(240);
    expect(skyPosition(270, 0).x).toBeLessThan(240);
    expect(skyPosition(0, -5).y).toBeLessThan(skyPosition(0, 0).y);
    expect(skyPosition(360, 0).x).toBeCloseTo(skyPosition(0, 0).x);
  });
  it('uses angular distance from the south pole and east-positive longitude', () => {
    expect(polarPosition(-90, 80)).toEqual({ x: 240, y: 240 });
    expect(polarPosition(-85, 0)).toEqual({ x: 240, y: 70 });
    expect(polarPosition(-85, 90).x).toBeCloseTo(410);
    expect(polarPosition(-85, -90).x).toBeCloseTo(70);
    expect(polarPosition(-89, 0).y - 240).toBeCloseTo(
      (polarPosition(-85, 0).y - 240) / 5,
    );
  });
});
