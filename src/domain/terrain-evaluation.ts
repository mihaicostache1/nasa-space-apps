import type {
  ReferenceEvaluationDataset,
  ReferenceEvaluationProvenance,
  ReferenceEvaluationRequest,
} from './evaluation';
import type { TerrainMask } from './terrain-mask';

/** Contract prepared for runtime integration; the current HTTP route is geometric only. */
export type TerrainReferenceEvaluationRequest = Omit<
  ReferenceEvaluationRequest,
  'horizonMode'
> & {
  horizonMode: 'terrain';
  /** Identifier selected by the server; no file paths or caller-supplied checksums. */
  maskId: string;
  /** Defaults to false; the current reviewed pairing needs explicit true. */
  allowMeanEarthApproximation?: boolean;
};

export type TerrainCompatibilityProvenance = {
  maskId: string;
  siteId: string;
  framePolicy: 'mean-earth-reference-v1';
  frameStatus: 'approximate';
  maskFrameName: string;
  maskFrameRealization: string;
  ephemerisFrame: string;
  ephemerisDynamicalSource: 'DE440' | 'DE441';
  referenceRadiusKm: number;
  transformationApplied: false;
  limitation: string;
  references: string[];
};

export type TerrainMaskProvenance = {
  /** SHA-256 of the original file bytes, verified by the backend loader. */
  artifactSha256: string;
  mask: TerrainMask;
  compatibility: TerrainCompatibilityProvenance;
};

export type TerrainReferenceEvaluationProvenance =
  ReferenceEvaluationProvenance & {
    terrain: TerrainMaskProvenance;
  };

export type TerrainReferenceEvaluationDataset = Omit<
  ReferenceEvaluationDataset,
  'schemaVersion' | 'horizonMode' | 'provenance'
> & {
  schemaVersion: 'lunarwindow.reference-evaluation.v2';
  horizonMode: 'terrain';
  maskId: string;
  allowMeanEarthApproximation: true;
  provenance: TerrainReferenceEvaluationProvenance;
};

/** Discriminated by horizonMode; geometric v1 retains its existing shape. */
export type ReferenceEvaluationRequestContract =
  ReferenceEvaluationRequest | TerrainReferenceEvaluationRequest;

export type ReferenceEvaluationContract =
  ReferenceEvaluationDataset | TerrainReferenceEvaluationDataset;
