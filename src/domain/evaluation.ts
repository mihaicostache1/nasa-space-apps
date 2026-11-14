import type { EphemerisSample } from './ephemeris';

/** Backend/data task 1 uses illustrative sites and synthetic results throughout. */
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

export type EvaluationDataset = {
  schemaVersion: 'lunarwindow.evaluation.v1';
  dataMode: 'synthetic';
  siteId: string;
  site: string;
  lat: number;
  lon: number;
  altitudeKm: number;
  coordinateSource: string;
  /** Exactly 360 points, indexed by azimuth in whole degrees. */
  horizon: { az: number; el: number }[];
  series: (EphemerisSample & { sunLit: boolean; earthVis: boolean })[];
  /** Reserved fields; all null until the next backend task implements metrics. */
  metrics: {
    pctSun: number | null;
    pctEarth: number | null;
    pctBoth: number | null;
    longestDarkHrs: number | null;
    nextSunset: string | null;
    nextEarthset: string | null;
  };
  provenance: {
    provider: 'LunarWindow deterministic demo generator';
    startUtc: string;
    endUtc: string;
    endExclusive: true;
    stepMinutes: number;
    timeScale: 'UTC';
    terrainModel: 'synthetic';
    visibilityRule: 'body-center-above-synthetic-horizon';
    warning: string;
  };
};

export type ApiErrorResponse = {
  error: {
    code: string;
    message: string;
    details: { location: (string | number)[]; message: string; type: string }[];
  };
};
