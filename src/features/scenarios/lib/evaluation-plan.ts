type PreviousEvaluation = {
  status: 'idle' | 'loading' | 'ready' | 'error';
  requestKey?: string;
  data?: unknown;
};

/** Keep an unchanged ready slot when updating its partner; explicit refresh checks both. */
export function planReferenceRequests(
  keys: string[],
  previous: PreviousEvaluation[],
): boolean[] {
  const reusable = keys.map(
    (key, index) =>
      previous[index]?.status === 'ready' &&
      previous[index].data !== undefined &&
      previous[index].requestKey === key,
  );
  return reusable.every(Boolean)
    ? keys.map(() => true)
    : reusable.map((ready) => !ready);
}
