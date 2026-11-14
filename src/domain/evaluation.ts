import type { EphemerisDataset, EphemerisSample } from './ephemeris';
import type { Scenario } from './scenario';

export type VisibilityRule = 'any-disc' | 'body-center' | 'full-disc';
export type DiscVisibility = 'hidden' | 'partial' | 'full';

/** Existing scenarios remain valid; calculation options are optional. */
export type EvaluationRequest = Scenario & {
  visibilityRule?: VisibilityRule;
  /** Within [startUtc, endUtc); defaults to startUtc. */
  asOfUtc?: string | null;
};

/** Demo coordinates and source data remain illustrative. */
export type DemoSite = {
  id: string;
  name: string;
  lat: number;
  lon: number;
  altitudeKm: number;
  coordinateSource: string;
};

export type SiteCatalog = {
  dataMode: 'synthetic';
  sites: DemoSite[];
};

export type VisibilitySample = EphemerisSample & {
  sunHorizonEl: number;
  earthHorizonEl: number;
  sunVisibility: DiscVisibility;
  earthVisibility: DiscVisibility;
  /** Flags follow the chosen visibilityRule. */
  sunLit: boolean;
  earthVis: boolean;
};

export type VisibilityWindow = {
  startUtc: string;
  /** Exclusive end; a range boundary does not imply an actual event. */
  endUtc: string;
  durationHrs: number;
  startTruncated: boolean;
  endTruncated: boolean;
};

export type VisibilityWindows = {
  sunlit: VisibilityWindow[];
  earthVisible: VisibilityWindow[];
  both: VisibilityWindow[];
  darkness: VisibilityWindow[];
  earthBlackout: VisibilityWindow[];
};

/** The setting transition is bracketed by two observations: (afterUtc, byUtc]. */
export type EventBracket = { afterUtc: string; byUtc: string };

export type VisibilityMetrics = {
  evaluatedHrs: number;
  sunlitHrs: number;
  earthVisibleHrs: number;
  bothHrs: number;
  pctSun: number;
  pctEarth: number;
  pctBoth: number;
  longestDarkHrs: number;
  longestEarthBlackoutHrs: number;
  longestBothHrs: number;
  asOfUtc: string;
  /** Upper bracket endpoints; null means no subsequent setting was observed. */
  nextSunset: string | null;
  nextEarthset: string | null;
  /** Hours to the upper bracket endpoint, relative to asOfUtc. */
  hoursToSunset: number | null;
  hoursToEarthset: number | null;
  nextSunsetBracket: EventBracket | null;
  nextEarthsetBracket: EventBracket | null;
};

export type CalculationInfo = {
  visibilityRule: VisibilityRule;
  horizonInterpolation: 'circular-linear';
  discModel: 'local-horizontal-limb';
  timeModel: 'sample-and-hold';
  eventTiming: 'sample-transition-brackets';
  stepMinutes: number;
};

export type EvaluationDataset = {
  schemaVersion: 'lunarwindow.evaluation.v2';
  dataMode: 'synthetic';
  siteId: string;
  site: string;
  lat: number;
  lon: number;
  altitudeKm: number;
  coordinateSource: string;
  /** Exactly 360 points, indexed by azimuth in whole degrees. */
  horizon: { az: number; el: number }[];
  series: VisibilitySample[];
  metrics: VisibilityMetrics;
  windows: VisibilityWindows;
  calculation: CalculationInfo;
  provenance: {
    provider: 'LunarWindow deterministic demo generator';
    startUtc: string;
    endUtc: string;
    endExclusive: true;
    stepMinutes: number;
    timeScale: 'UTC';
    terrainModel: 'synthetic';
    warning: string;
  };
};

/** POST /api/reference/evaluations: verified archived data with a geometric horizon. */
export type ReferenceEvaluationRequest = {
  siteId: string;
  horizonMode: 'geometric';
  startUtc: string;
  endUtc: string;
  stepMinutes?: number;
  visibilityRule?: VisibilityRule;
  asOfUtc?: string | null;
};

export type ReferenceArchiveCoverage = {
  startUtc: string;
  endUtc: string;
  endExclusive: true;
  stepMinutes: number;
  sampleCount: number;
};

export type ReferenceEvaluationProvenance = {
  /** Period/step describe selected samples; original NASA request evidence is retained. */
  ephemeris: EphemerisDataset['provenance'];
  archive: ReferenceArchiveCoverage;
  warning: string;
};

export type ReferenceEvaluationDataset = Omit<
  EvaluationDataset,
  'schemaVersion' | 'dataMode' | 'provenance'
> & {
  schemaVersion: 'lunarwindow.reference-evaluation.v1';
  dataMode: 'reference';
  horizonMode: 'geometric';
  provenance: ReferenceEvaluationProvenance;
};

export type ApiErrorResponse = {
  error: {
    code: string;
    message: string;
    details: { location: (string | number)[]; message: string; type: string }[];
  };
};
