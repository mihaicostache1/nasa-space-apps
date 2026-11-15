import { z } from 'zod';

export const capabilitiesSchema = z.object({
  schemaVersion: z.literal('lunarwindow.capabilities.v1'),
  customEvaluation: z
    .object({ enabled: z.boolean(), terrainEnabled: z.boolean() })
    .refine((value) => !value.terrainEnabled || value.enabled),
});

export type Capabilities = z.infer<typeof capabilitiesSchema>;

export type CapabilityState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: Capabilities };

export function customModeEnabled(
  state: CapabilityState,
  mode: 'geometric' | 'terrain',
): boolean {
  return (
    state.status === 'ready' &&
    state.data.customEvaluation.enabled &&
    (mode === 'geometric' || state.data.customEvaluation.terrainEnabled)
  );
}
