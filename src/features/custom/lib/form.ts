import type { CustomEvaluationRequest } from '@/domain/custom-evaluation';

export type CustomForm = {
  latitude: string;
  longitude: string;
  height: string;
  ground: string;
  start: string;
  end: string;
  step: string;
  mode: 'geometric' | 'terrain';
  accepted: boolean;
};
export const defaultCustomForm: CustomForm = {
  latitude: '-89',
  longitude: '0',
  height: '2',
  ground: '',
  start: '2026-11-14T00:00',
  end: '2026-11-15T00:00',
  step: '60',
  mode: 'geometric',
  accepted: false,
};

export function customRequest(form: CustomForm): {
  request?: CustomEvaluationRequest;
  issues: string[];
} {
  const issues: string[] = [];
  const number = (value: string, label: string, min: number, max: number) => {
    const result = value.trim() ? Number(value) : NaN;
    if (!Number.isFinite(result) || result < min || result > max)
      issues.push(`${label} must be between ${min} and ${max}.`);
    return result;
  };
  const latitudeDeg = number(form.latitude, 'Latitude (degrees)', -90, 90);
  const longitudeDeg = number(
    form.longitude,
    'East longitude (degrees)',
    -180,
    180,
  );
  const observerHeightM = number(form.height, 'Observer height (m)', 0, 1000);
  const surfaceElevationM =
    form.mode === 'geometric'
      ? number(form.ground, 'Ground elevation (m)', -20000, 20000)
      : undefined;
  const stepMinutes = number(form.step, 'Sample interval (minutes)', 1, 1440);
  if (!Number.isInteger(stepMinutes))
    issues.push('Sample interval must be a whole number of minutes.');
  const date = (value: string) => {
    const ms = Date.parse(`${value}:00Z`);
    return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) &&
      Number.isFinite(ms) &&
      new Date(ms).toISOString().slice(0, 16) === value
      ? ms
      : NaN;
  };
  const start = date(form.start),
    end = date(form.end);
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    start < Date.parse('2000-01-01T00:00Z') ||
    end > Date.parse('2040-01-01T00:00Z') ||
    end <= start
  )
    issues.push(
      'Choose a valid UTC period in 2000–2039 with the end after the start.',
    );
  else if (end - start > 31 * 86400000)
    issues.push('Choose a period of at most 31 days.');
  else if (Math.ceil((end - start) / (stepMinutes * 60000)) > 744)
    issues.push(
      'Choose a shorter period or larger sample interval (maximum 744 samples).',
    );
  if (form.mode === 'terrain' && latitudeDeg > -60)
    issues.push(
      'Custom terrain is limited to 60–90°S. Choose a south-polar point or select geometric mode.',
    );
  if (form.mode === 'terrain' && !form.accepted)
    issues.push(
      'Accept the Mean Earth frame approximation to request terrain evaluation.',
    );
  if (issues.length) return { issues };
  return {
    issues,
    request: {
      location: {
        latitudeDeg,
        longitudeDeg,
        observerHeightM,
        ...(surfaceElevationM === undefined ? {} : { surfaceElevationM }),
      },
      horizonMode: form.mode,
      allowMeanEarthApproximation: form.mode === 'terrain' && form.accepted,
      startUtc: new Date(start).toISOString().replace('.000Z', 'Z'),
      endUtc: new Date(end).toISOString().replace('.000Z', 'Z'),
      stepMinutes,
      visibilityRule: 'any-disc',
    },
  };
}

export function customErrorTitle(error: {
  status?: number;
  code?: string;
}): string {
  if (error.code === 'invalid_custom_response')
    return 'Incomplete scientific data';
  if (error.status === 404 || error.code === 'custom_disabled')
    return 'Custom evaluation unavailable';
  if (error.code === 'custom_busy') return 'Evaluation service busy';
  if (error.status === 422) return 'Observer or coverage needs attention';
  if (error.status === 502) return 'Horizons service unavailable';
  if (error.status === 504) return 'Evaluation time limit reached';
  if (error.status === 503) return 'Evaluation data unavailable';
  return 'Unable to evaluate this observer';
}
