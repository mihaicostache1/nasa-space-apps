import type { ReferenceEvaluationDataset } from '@/domain/evaluation';

export type Slot = 'A' | 'B';

/** A completed reference evaluation shown in the analysis views. */
export type ScenarioResult = {
  slot: Slot;
  data: ReferenceEvaluationDataset;
  /** True when the inputs changed after this result was calculated. */
  stale: boolean;
};
