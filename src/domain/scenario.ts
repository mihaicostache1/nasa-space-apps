import { z } from 'zod';

// Internal contract: decimal degrees, east-positive longitude, UTC timestamps.
export const lunarLocationSchema = z.object({
  latitudeDeg: z.number().min(-90).max(90),
  longitudeDeg: z.number().min(-180).max(180),
  // Height above the provider's lunar reference surface; not height above terrain.
  altitudeKm: z.number().finite(),
});

export const scenarioSchema = z
  .object({
    name: z.string().trim().min(1).max(80),
    location: lunarLocationSchema,
    startUtc: z.iso.datetime(),
    endUtc: z.iso.datetime(),
    stepMinutes: z.number().int().min(1).max(1440),
  })
  .superRefine((scenario, context) => {
    const duration =
      Date.parse(scenario.endUtc) - Date.parse(scenario.startUtc);
    if (duration <= 0) {
      context.addIssue({
        code: 'custom',
        path: ['endUtc'],
        message: 'End must follow start.',
      });
    }
    if (duration > 31 * 24 * 60 * 60 * 1000) {
      context.addIssue({
        code: 'custom',
        path: ['endUtc'],
        message: 'Choose at most 31 days.',
      });
    }
    if (duration / (scenario.stepMinutes * 60_000) + 1 > 10_000) {
      context.addIssue({
        code: 'custom',
        path: ['stepMinutes'],
        message: 'Choose a larger step (maximum 10,000 samples).',
      });
    }
  });

export type LunarLocation = z.infer<typeof lunarLocationSchema>;
export type Scenario = z.infer<typeof scenarioSchema>;
