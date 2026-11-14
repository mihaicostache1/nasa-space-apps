import type { ApiErrorResponse } from '@/domain/evaluation';
import type { ReferenceSiteCatalog } from '@/domain/reference';
import type {
  ReferenceEvaluationContract,
  ReferenceEvaluationRequestContract,
} from '@/domain/terrain-evaluation';

/** Browser-visible FastAPI origin; inlined at build time. */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Human-readable message for a structured FastAPI error envelope. */
export function describeApiError(status: number, body: unknown): string {
  const envelope = body as Partial<ApiErrorResponse> | null;
  const error = envelope?.error;
  if (!error || typeof error.message !== 'string') {
    return `The API returned HTTP ${status}.`;
  }
  const details = (error.details ?? [])
    .map((detail) => {
      const field = detail.location.filter((part) => part !== 'body').join('.');
      return field ? `${field}: ${detail.message}` : detail.message;
    })
    .filter(Boolean);
  return details.length
    ? `${error.message} ${details.join('; ')}`
    : error.message;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...init?.headers },
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw cause;
    }
    throw new ApiError(
      `Cannot reach the LunarWindow API at ${API_BASE_URL}. A hosted API may be waking up (up to a minute); locally, start it with "docker compose up -d --wait api". Then retry.`,
      0,
    );
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      describeApiError(response.status, body),
      response.status,
    );
  }
  return body as T;
}

export function fetchReferenceSites(signal?: AbortSignal) {
  return request<ReferenceSiteCatalog>('/api/reference/sites', { signal });
}

export function evaluateReference(
  body: ReferenceEvaluationRequestContract,
  signal?: AbortSignal,
) {
  return request<ReferenceEvaluationContract>('/api/reference/evaluations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}
