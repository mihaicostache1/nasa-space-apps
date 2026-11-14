import type { ReferenceEvaluationContract } from '@/domain/terrain-evaluation';
import type { Slot } from '../types';

type Mode = ReferenceEvaluationContract['horizonMode'];

/** Badge text: one mode when the scenarios agree, otherwise the mode per slot. */
export function modelBadge(modes: { slot: Slot; horizonMode: Mode }[]): string {
  const distinct = new Set(modes.map((m) => m.horizonMode));
  if (distinct.size <= 1) {
    return (modes[0]?.horizonMode ?? 'geometric').toUpperCase();
  }
  return modes
    .map((m) => `${m.slot} ${m.horizonMode.toUpperCase()}`)
    .join(' · ');
}

/** Short statement of the horizon model behind one result. */
export function describeModel(data: ReferenceEvaluationContract): {
  label: string;
  detail: string;
} {
  if (data.horizonMode === 'terrain') {
    const { mastHeightM } = data.provenance.terrain.mask.observer;
    return {
      label: 'Terrain',
      detail: `reviewed LOLA DEM horizon, ${mastHeightM} m mast, frame approximation accepted`,
    };
  }
  return { label: 'Geometric', detail: 'flat 0° horizon, terrain not applied' };
}
