import type {
  ReferenceEvaluationRequest,
  VisibilityRule,
} from '@/domain/evaluation';
import type { ReferenceSite, ReferenceTerrainMask } from '@/domain/reference';
import type { ReferenceEvaluationRequestContract } from '@/domain/terrain-evaluation';

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

export type HorizonMode = 'geometric' | 'terrain';

/** One comparison slot: a verified reference site and a whole-day UTC period. */
export type ReferenceScenarioForm = {
  slot: 'A' | 'B';
  siteId: string;
  /** YYYY-MM-DD, interpreted as 00:00 UTC (inclusive). */
  startDate: string;
  /** YYYY-MM-DD, interpreted as 00:00 UTC (exclusive). */
  endDate: string;
  stepMinutes: number;
  visibilityRule: VisibilityRule;
  /** Flat 0° horizon, or the site's server-reviewed LOLA terrain mask. */
  horizonMode: HorizonMode;
  /** Mask selected for terrain mode; empty for the geometric horizon. */
  maskId: string;
  /** The terrain mask's frame approximation must be accepted explicitly. */
  acceptFrameApproximation: boolean;
};

const GEOMETRIC = {
  horizonMode: 'geometric',
  maskId: '',
  acceptFrameApproximation: false,
} as const;

export const VISIBILITY_RULES: { value: VisibilityRule; label: string }[] = [
  { value: 'any-disc', label: 'Any part of the disc is up' },
  { value: 'body-center', label: 'Disc centre is up' },
  { value: 'full-disc', label: 'Whole disc is up' },
];

export function utcDate(iso: string): string {
  return iso.slice(0, 10);
}

/** Latest selectable start date: one day before the archive's exclusive end. */
export function lastStartDate(site: ReferenceSite): string {
  return utcDate(
    new Date(Date.parse(site.availability.endUtc) - DAY_MS).toISOString(),
  );
}

/** Step choices: whole multiples of the archive interval, up to one day. */
export function stepOptions(site: ReferenceSite | undefined): number[] {
  const base = site?.availability.stepMinutes ?? 60;
  return [1, 2, 3, 6, 12, 24]
    .map((factor) => factor * base)
    .filter((minutes) => minutes <= 1440);
}

/** The reviewed terrain mask a site advertises, if any (at most one today). */
export function terrainMask(
  site: ReferenceSite | undefined,
): ReferenceTerrainMask | undefined {
  return site?.supportedHorizonModes.includes('terrain')
    ? site.terrainMasks[0]
    : undefined;
}

export function defaultForm(
  slot: 'A' | 'B',
  site: ReferenceSite,
): ReferenceScenarioForm {
  return {
    slot,
    siteId: site.id,
    startDate: utcDate(site.availability.startUtc),
    endDate: utcDate(site.availability.endUtc),
    stepMinutes: site.availability.stepMinutes,
    visibilityRule: 'any-disc',
    ...GEOMETRIC,
  };
}

/** Keep the dates inside the newly selected site's archive coverage. */
export function withSite(
  form: ReferenceScenarioForm,
  site: ReferenceSite,
): ReferenceScenarioForm {
  const first = utcDate(site.availability.startUtc);
  const last = utcDate(site.availability.endUtc);
  const startDate =
    form.startDate < first || form.startDate > lastStartDate(site)
      ? first
      : form.startDate;
  const endDate =
    form.endDate > last || form.endDate <= startDate ? last : form.endDate;
  const stepMinutes = stepOptions(site).includes(form.stepMinutes)
    ? form.stepMinutes
    : site.availability.stepMinutes;
  // A mask belongs to one site: another site starts again from the flat horizon.
  const horizon = site.id === form.siteId ? {} : GEOMETRIC;
  return {
    ...form,
    siteId: site.id,
    startDate,
    endDate,
    stepMinutes,
    ...horizon,
  };
}

/** Switch horizon; terrain falls back to geometric when the site has no mask. */
export function withHorizonMode(
  form: ReferenceScenarioForm,
  mode: HorizonMode,
  site: ReferenceSite | undefined,
): ReferenceScenarioForm {
  const mask = mode === 'terrain' ? terrainMask(site) : undefined;
  return mask
    ? {
        ...form,
        horizonMode: 'terrain',
        maskId: mask.maskId,
        acceptFrameApproximation: false,
      }
    : { ...form, ...GEOMETRIC };
}

export function toRequest(
  form: ReferenceScenarioForm,
): ReferenceEvaluationRequestContract {
  const request: ReferenceEvaluationRequest = {
    siteId: form.siteId,
    horizonMode: 'geometric',
    startUtc: `${form.startDate}T00:00:00Z`,
    endUtc: `${form.endDate}T00:00:00Z`,
    stepMinutes: form.stepMinutes,
    visibilityRule: form.visibilityRule,
  };
  if (form.horizonMode !== 'terrain') return request;
  return {
    ...request,
    horizonMode: 'terrain',
    maskId: form.maskId,
    allowMeanEarthApproximation: form.acceptFrameApproximation,
  };
}

/** Client-side checks mirroring the API, so most mistakes never leave the page. */
export function validateForm(
  form: ReferenceScenarioForm,
  site: ReferenceSite | undefined,
): string[] {
  if (!site) return ['Choose a reference site.'];
  const issues: string[] = [];
  const start = Date.parse(`${form.startDate}T00:00:00Z`);
  const end = Date.parse(`${form.endDate}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(end)) {
    return ['Choose a start and an end date.'];
  }
  const { availability } = site;
  if (
    start < Date.parse(availability.startUtc) ||
    end > Date.parse(availability.endUtc)
  ) {
    issues.push(
      `Dates must lie within the archive: ${utcDate(availability.startUtc)} to ${utcDate(availability.endUtc)} (end excluded).`,
    );
  }
  if (end <= start) issues.push('The end date must follow the start date.');
  if (end - start > 31 * DAY_MS) issues.push('Choose at most 31 days.');
  if (form.stepMinutes % availability.stepMinutes !== 0) {
    issues.push(
      `The step must be a multiple of the archive's ${availability.stepMinutes}-minute interval.`,
    );
  }
  if (form.horizonMode === 'terrain') {
    if (terrainMask(site)?.maskId !== form.maskId) {
      issues.push('This site has no reviewed terrain horizon.');
    } else if (!form.acceptFrameApproximation) {
      issues.push('Accept the frame approximation to use the terrain horizon.');
    }
  }
  return issues;
}
