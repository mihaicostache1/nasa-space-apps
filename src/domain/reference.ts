import type { ReferenceArchiveCoverage } from './evaluation';

/** GET /api/reference/sites: verified archived reference points (not landing targets). */
export type ReferenceSite = {
  id: string;
  name: string;
  lat: number;
  /** East-positive degrees. */
  lon: number;
  /** Observer altitude above the 1737.4 km reference sphere. */
  altitudeKm: number;
  coordinateSource: string;
  availability: ReferenceArchiveCoverage;
};

export type ReferenceSiteCatalog = {
  schemaVersion: 'lunarwindow.reference-catalog.v1';
  provider: string;
  timeScale: 'UTC';
  longitudeConvention: 'east-positive';
  sites: ReferenceSite[];
};
