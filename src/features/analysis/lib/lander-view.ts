import type { DiscVisibility, VisibilitySample } from '@/domain/evaluation';

/** Signed shortest turn from `from` to `to`, in (-180, 180] degrees. */
export function angleDelta(from: number, to: number): number {
  const delta = (((to - from) % 360) + 540) % 360;
  return delta - 180 === -180 ? 180 : delta - 180;
}

export function wrap360(angle: number): number {
  return ((angle % 360) + 360) % 360;
}

/** Interpolate azimuths along the short way round, so 359° → 1° passes north. */
export function lerpAngle(from: number, to: number, fraction: number): number {
  return wrap360(from + angleDelta(from, to) * fraction);
}

/** Horizon elevation at a fractional azimuth: circular-linear, as in the engine. */
export function horizonElAt(horizon: { el: number }[], az: number): number {
  const wrapped = wrap360(az);
  const lower = Math.floor(wrapped) % 360;
  const fraction = wrapped - Math.floor(wrapped);
  const next = horizon[(lower + 1) % 360];
  return horizon[lower].el * (1 - fraction) + next.el * fraction;
}

export type BodyState = {
  az: number;
  el: number;
  radiusDeg: number;
  /** The model's flag (visibility rule applied) for the observation in effect. */
  visible: boolean;
  visibility: DiscVisibility;
};

export type SkyState = {
  timeMs: number;
  sun: BodyState;
  earth: BodyState;
};

/**
 * Positions are interpolated between the hourly observations so the animation
 * moves smoothly; visibility flags are the model's, held from the observation in
 * effect (sample-and-hold), so they always agree with the timeline.
 */
export function createSkyTrack(
  series: VisibilitySample[],
  stepMinutes: number,
) {
  const times = series.map((sample) => Date.parse(sample.t));
  const stepMs = stepMinutes * 60_000;

  return function at(timeMs: number): SkyState | null {
    let low = 0;
    let high = times.length - 1;
    let index = -1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (times[mid] <= timeMs) {
        index = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    if (index < 0 || timeMs >= times[index] + stepMs) return null;
    const held = series[index];
    const next = series[index + 1];
    const fraction =
      next && times[index + 1] - times[index] === stepMs
        ? (timeMs - times[index]) / stepMs
        : 0;
    const to = next ?? held;
    const body = (key: 'sun' | 'earth'): BodyState => ({
      az: lerpAngle(held[`${key}Az`], to[`${key}Az`], fraction),
      el: held[`${key}El`] + (to[`${key}El`] - held[`${key}El`]) * fraction,
      radiusDeg: held[`${key}AngularRadiusDeg`],
      visible: key === 'sun' ? held.sunLit : held.earthVis,
      visibility: key === 'sun' ? held.sunVisibility : held.earthVisibility,
    });
    return { timeMs, sun: body('sun'), earth: body('earth') };
  };
}

const RAD = Math.PI / 180;

/**
 * Earth's phase as seen from the Moon. The Sun is effectively at infinity, so the
 * phase angle at Earth is 180° minus the Sun–Earth elongation in the lunar sky:
 * Earth is full when the Sun is behind the observer, new when beside Earth.
 * `bearingDeg` points from Earth's disc toward the Sun: 0° = up (zenith),
 * 90° = toward increasing azimuth (right, in a view facing the horizon).
 */
export function earthIllumination(
  sun: { az: number; el: number },
  earth: { az: number; el: number },
): { fraction: number; elongationDeg: number; bearingDeg: number } {
  const dAz = (sun.az - earth.az) * RAD;
  const sunEl = sun.el * RAD;
  const earthEl = earth.el * RAD;
  const cosE =
    Math.sin(sunEl) * Math.sin(earthEl) +
    Math.cos(sunEl) * Math.cos(earthEl) * Math.cos(dAz);
  const elongation = Math.acos(Math.min(1, Math.max(-1, cosE)));
  const bearing = Math.atan2(
    Math.sin(dAz) * Math.cos(sunEl),
    Math.cos(earthEl) * Math.sin(sunEl) -
      Math.sin(earthEl) * Math.cos(sunEl) * Math.cos(dAz),
  );
  return {
    fraction: (1 - Math.cos(elongation)) / 2,
    elongationDeg: elongation / RAD,
    bearingDeg: wrap360(bearing / RAD),
  };
}

/** The Moon's sidereal rotation period: the stars' turn rate in the lunar sky. */
export const SIDEREAL_HOURS = 655.72;

/**
 * Near the pole the sky turns about the zenith, so stars shift in azimuth at the
 * sidereal rate, in the same sense as the Sun's daily drift in the data.
 */
export function skyDrift(series: VisibilitySample[]): number {
  if (series.length < 2) return -1;
  let total = 0;
  for (let i = 1; i < series.length; i++) {
    total += angleDelta(series[i - 1].sunAz, series[i].sunAz);
  }
  return total < 0 ? -1 : 1;
}

export function starAzimuth(baseAz: number, hours: number, drift: number) {
  return wrap360(baseAz + (drift * 360 * hours) / SIDEREAL_HOURS);
}

export type Camera = {
  /** Azimuth at the centre of the view. */
  az: number;
  /** Elevation at the centre of the view. */
  el: number;
  pxPerDeg: number;
  width: number;
  height: number;
};

/** Cylindrical projection; at these elevations (|el| < 15°) distortion is < 4%. */
export function project(camera: Camera, az: number, el: number) {
  return {
    x: camera.width / 2 + angleDelta(camera.az, az) * camera.pxPerDeg,
    y: camera.height / 2 - (el - camera.el) * camera.pxPerDeg,
  };
}

/**
 * Vertical aim for a tracked body: follow it halfway so the body and the 0°
 * horizon both stay in frame, a few degrees from the edges.
 */
export function cameraElevation(bodyEl: number, viewHeightDeg: number) {
  const limit = Math.max(0, viewHeightDeg / 2 - 3);
  return Math.min(limit, Math.max(-limit, bodyEl * 0.5 + 1));
}

/** A disc's position relative to the local skyline, from geometry alone. */
export function discAgainstSkyline(
  body: { az: number; el: number; radiusDeg: number },
  horizon: { el: number }[],
): DiscVisibility {
  const skyline = horizonElAt(horizon, body.az);
  if (body.el + body.radiusDeg <= skyline) return 'hidden';
  if (body.el - body.radiusDeg >= skyline) return 'full';
  return 'partial';
}

/** Deterministic star field (az, el in degrees; magnitude-like 0..1 brightness). */
export function starField(count: number, seed = 7) {
  let state = seed;
  const random = () => {
    state = (state * 1_103_515_245 + 12_345) % 2_147_483_648;
    return state / 2_147_483_648;
  };
  return Array.from({ length: count }, () => ({
    az: random() * 360,
    el: -20 + random() * 60,
    brightness: random() ** 3,
  }));
}
