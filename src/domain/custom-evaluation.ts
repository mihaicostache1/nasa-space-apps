import { z } from 'zod';
import type {
  CalculationInfo,
  VisibilityMetrics,
  VisibilitySample,
  VisibilityWindows,
  VisibilityRule,
} from './evaluation';
import type { EphemerisDataset } from './ephemeris';
import type { HorizonProfile, HorizonPoint } from './horizon';
import type { TerrainMask } from './terrain-mask';
import type { TerrainCompatibilityProvenance } from './terrain-evaluation';

export type CustomEvaluationRequest = {
  location: {
    latitudeDeg: number;
    longitudeDeg: number;
    observerHeightM: number;
    surfaceElevationM?: number;
  };
  horizonMode: 'geometric' | 'terrain';
  allowMeanEarthApproximation: boolean;
  startUtc: string;
  endUtc: string;
  stepMinutes: number;
  visibilityRule: VisibilityRule;
};

export type CustomEvaluation = {
  schemaVersion: 'lunarwindow.custom-evaluation.v1';
  dataMode: 'custom';
  siteId: string;
  site: string;
  observer: TerrainMask['observer'];
  horizonMode: 'geometric' | 'terrain';
  allowMeanEarthApproximation: boolean;
  horizon: HorizonPoint[];
  series: VisibilitySample[];
  metrics: VisibilityMetrics;
  windows: VisibilityWindows;
  calculation: CalculationInfo;
  provenance: {
    ephemeris: EphemerisDataset['provenance'];
    ephemerisSha256: string;
    warning: string;
    terrain: null | {
      profile: HorizonProfile;
      profileSha256: string;
      mask: TerrainMask;
      maskSha256: string;
      compatibility: TerrainCompatibilityProvenance;
      reviewStatus: 'preliminary';
    };
  };
};

const finite = z.number().finite();
const text = z.string().min(1);
const httpUrl = z
  .string()
  .url()
  .refine((value) => /^https?:\/\//.test(value));
const utc = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z$/)
  .refine(
    (v) =>
      Number.isFinite(Date.parse(v)) &&
      new Date(v).toISOString() === v.replace('Z', '.000Z'),
  );
const hash = z.string().regex(/^[0-9a-f]{64}$/);
const point = z.object({
  az: finite.min(0).max(359),
  el: finite.min(-90).max(90),
});
const horizon = z
  .array(point)
  .length(360)
  .refine((rows) => rows.every((row, i) => row.az === i));
const bracket = z.object({ afterUtc: utc, byUtc: utc }).nullable();
const windowSchema = z.object({
  startUtc: utc,
  endUtc: utc,
  durationHrs: finite.positive(),
  startTruncated: z.boolean(),
  endTruncated: z.boolean(),
});
const sample = z.object({
  t: utc,
  sunAz: finite.min(0).lt(360),
  sunEl: finite.min(-90).max(90),
  earthAz: finite.min(0).lt(360),
  earthEl: finite.min(-90).max(90),
  sunAngularRadiusDeg: finite.positive(),
  earthAngularRadiusDeg: finite.positive(),
  sunHorizonEl: finite,
  earthHorizonEl: finite,
  sunVisibility: z.enum(['hidden', 'partial', 'full']),
  earthVisibility: z.enum(['hidden', 'partial', 'full']),
  sunLit: z.boolean(),
  earthVis: z.boolean(),
});
const observer = z.object({
  lat: finite.min(-90).max(90),
  lon: finite.min(-180).max(180),
  coordinateSource: text,
  surfaceElevationM: finite,
  mastHeightM: finite.nonnegative(),
  altitudeKm: finite,
});
const demSource = z.object({
  provider: text,
  productId: text,
  productVersion: text,
  sourceUrl: httpUrl,
  sourceSha256: hash,
  retrievedAtUtc: text,
  resolutionM: finite.positive(),
  crs: text,
});
const frame = z.object({
  body: z.literal('Moon'),
  name: text,
  realization: text,
  coordinateType: z.literal('GEODETIC'),
  longitudeConvention: z.literal('east-positive'),
  referenceSurface: z.object({
    shape: z.literal('sphere'),
    radiusKm: finite.positive(),
  }),
});
const terrain = z.object({
  reviewStatus: z.literal('preliminary'),
  profileSha256: hash,
  maskSha256: hash,
  profile: z
    .object({
      schemaVersion: z.literal('lunarwindow.horizon.v1'),
      siteId: text,
      name: text,
      coordinateSource: text,
      lat: finite,
      lon: finite,
      horizon,
      terrainModel: z.literal('lola-dem'),
      surfaceElevationM: finite,
      mastHeightM: finite,
      observerAltitudeKm: finite,
      referenceRadiusM: finite,
      algorithmVersion: text,
      parameters: z.object({
        mastHeightM: finite.nonnegative(),
        maxRangeKm: finite.positive(),
        nearFieldKm: finite.nonnegative(),
        minDistanceM: finite.positive(),
        raysPerDegree: finite.int().positive(),
        stepGrowth: finite.nonnegative(),
        binning: z.literal('max-per-degree'),
      }),
      rays: z.object({
        stepDeg: finite.positive(),
        el: z.array(finite).min(360),
        horizonDistanceKm: z.array(finite.nonnegative().nullable()).min(360),
        reachKm: z.array(finite.nonnegative()).min(360),
      }),
      quality: z
        .object({
          truncatedAzimuths: z.array(z.number()).length(0),
          missingSampleFraction: z.literal(0),
          minReachKm: finite,
          nearFieldAvailable: z.boolean(),
          warnings: z.array(z.string()),
        })
        .passthrough(),
      sources: z
        .array(
          z
            .object({
              productId: text,
              role: text,
              sourceUrl: httpUrl,
              sha256: hash,
              resolutionM: finite.positive(),
            })
            .passthrough(),
        )
        .min(1),
    })
    .passthrough(),
  mask: z
    .object({
      schemaVersion: z.literal('lunarwindow.terrain-mask.v1'),
      maskId: text,
      siteId: text,
      site: text,
      terrainModel: z.literal('dem-horizon'),
      angularUnits: z.literal('degrees'),
      azimuthConvention: z.literal('clockwise-from-local-north'),
      elevationReference: z.literal('local-horizontal'),
      refractionModel: z.literal('none'),
      observer,
      referenceFrame: frame,
      horizon,
      provenance: z.object({
        sources: z.array(demSource).min(1),
        createdAtUtc: text,
        algorithm: z
          .object({
            name: text,
            version: text,
            noDataPolicy: z.literal('reject'),
            curvatureModel: z.enum(['spherical', 'quadratic-drop']),
            rayStepM: finite.positive(),
            maxDistanceM: finite.positive(),
          })
          .passthrough(),
      }),
    })
    .passthrough(),
  compatibility: z
    .object({
      frameStatus: z.literal('approximate'),
      maskId: text,
      siteId: text,
      maskFrameName: text,
      maskFrameRealization: text,
      ephemerisFrame: text,
      ephemerisDynamicalSource: z.enum(['DE440', 'DE441']),
      referenceRadiusKm: finite.positive(),
      transformationApplied: z.literal(false),
      framePolicy: z.literal('mean-earth-reference-v1'),
      limitation: text,
      references: z.array(httpUrl).min(1),
    })
    .passthrough(),
});
const responseSchema = z.object({
  schemaVersion: z.literal('lunarwindow.custom-evaluation.v1'),
  dataMode: z.literal('custom'),
  siteId: text,
  site: text,
  observer,
  horizonMode: z.enum(['geometric', 'terrain']),
  allowMeanEarthApproximation: z.boolean(),
  horizon,
  series: z.array(sample).min(1).max(10000),
  metrics: z.object({
    evaluatedHrs: finite.positive(),
    sunlitHrs: finite.nonnegative(),
    earthVisibleHrs: finite.nonnegative(),
    bothHrs: finite.nonnegative(),
    pctSun: finite.min(0).max(100),
    pctEarth: finite.min(0).max(100),
    pctBoth: finite.min(0).max(100),
    longestDarkHrs: finite.nonnegative(),
    longestEarthBlackoutHrs: finite.nonnegative(),
    longestBothHrs: finite.nonnegative(),
    asOfUtc: utc,
    nextSunset: utc.nullable(),
    nextEarthset: utc.nullable(),
    hoursToSunset: finite.nullable(),
    hoursToEarthset: finite.nullable(),
    nextSunsetBracket: bracket,
    nextEarthsetBracket: bracket,
  }),
  windows: z.object({
    sunlit: z.array(windowSchema),
    earthVisible: z.array(windowSchema),
    both: z.array(windowSchema),
    darkness: z.array(windowSchema),
    earthBlackout: z.array(windowSchema),
  }),
  calculation: z.object({
    visibilityRule: z.enum(['any-disc', 'body-center', 'full-disc']),
    stepMinutes: finite.int().positive(),
    horizonInterpolation: z.literal('circular-linear'),
    discModel: z.literal('local-horizontal-limb'),
    timeModel: z.literal('sample-and-hold'),
    eventTiming: z.literal('sample-transition-brackets'),
  }),
  provenance: z.object({
    warning: text,
    ephemerisSha256: hash,
    terrain: terrain.nullable(),
    ephemeris: z
      .object({
        provider: z.literal('NASA/JPL Horizons'),
        observerCenter: z.literal('coord@301'),
        coordinateType: z.literal('GEODETIC'),
        longitudeConvention: z.literal('east-positive'),
        terrainModel: z.literal('none'),
        positionType: z.literal('airless-apparent-body-center'),
        quantities: z.tuple([z.literal(4), z.literal(13)]),
        angularSizeModel: z.literal('equatorial-radius'),
        startUtc: utc,
        endUtc: utc,
        endExclusive: z.literal(true),
        stepMinutes: finite.int().positive(),
        timeScale: z.literal('UTC'),
        requests: z
          .array(
            z
              .object({
                target: z.enum(['sun', 'earth']),
                sourceUrl: httpUrl,
                apiVersion: text,
                responseSha256: hash,
                retrievedAtUtc: text,
                modelHeader: z.record(z.string(), z.string()),
              })
              .passthrough(),
          )
          .min(2),
      })
      .passthrough(),
  }),
});

/** Reject partial/mismatched success payloads; never fill missing science with zeroes. */
export function parseCustomEvaluation(
  body: unknown,
  request: CustomEvaluationRequest,
): CustomEvaluation {
  const result = responseSchema.parse(body);
  const source = result.provenance.ephemeris;
  const start = Date.parse(source.startUtc),
    end = Date.parse(source.endUtc),
    step = request.stepMinutes * 60000;
  const longitude =
    request.location.longitudeDeg === 180
      ? -180
      : request.location.longitudeDeg;
  const consistent =
    result.horizonMode === request.horizonMode &&
    source.startUtc === request.startUtc &&
    source.endUtc === request.endUtc &&
    source.stepMinutes === request.stepMinutes &&
    result.calculation.stepMinutes === request.stepMinutes &&
    result.calculation.visibilityRule === request.visibilityRule &&
    result.observer.lat === request.location.latitudeDeg &&
    result.observer.lon === longitude &&
    result.observer.mastHeightM === request.location.observerHeightM &&
    Math.abs(
      result.observer.altitudeKm -
        (result.observer.surfaceElevationM + result.observer.mastHeightM) /
          1000,
    ) <= 1e-6 &&
    result.series.length === Math.ceil((end - start) / step) &&
    result.series.every((row, i) => Date.parse(row.t) === start + i * step) &&
    result.metrics.evaluatedHrs === (end - start) / 3600000 &&
    source.requests.some((r) => r.target === 'sun') &&
    source.requests.some((r) => r.target === 'earth');
  if (!consistent)
    throw new Error(
      'The response does not match the requested observer or time grid.',
    );
  if (request.horizonMode === 'geometric') {
    if (
      result.provenance.terrain !== null ||
      result.allowMeanEarthApproximation ||
      result.horizon.some((p) => p.el !== 0) ||
      result.observer.surfaceElevationM !== request.location.surfaceElevationM
    )
      throw new Error(
        'The geometric response contains inconsistent horizon or height data.',
      );
  } else {
    const evidence = result.provenance.terrain;
    if (
      !evidence ||
      !result.allowMeanEarthApproximation ||
      evidence.mask.siteId !== result.siteId ||
      evidence.profile.siteId !== result.siteId ||
      JSON.stringify(evidence.mask.observer) !==
        JSON.stringify(result.observer) ||
      evidence.profile.quality.minReachKm <
        evidence.profile.parameters.maxRangeKm - 0.001 ||
      evidence.mask.horizon.some((p, i) => p.el !== result.horizon[i].el) ||
      evidence.profile.horizon.some((p, i) => p.el !== result.horizon[i].el)
    )
      throw new Error('The terrain response is incomplete or inconsistent.');
  }
  return body as CustomEvaluation;
}
