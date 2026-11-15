import { describe, expect, it } from 'vitest';
import { planReferenceRequests } from '@/features/scenarios/lib/evaluation-plan';

describe('reference comparison request planning', () => {
  const ready = (requestKey: string) => ({
    status: 'ready' as const,
    requestKey,
    data: { verified: true },
  });
  it('requests both slots on first load', () => {
    expect(
      planReferenceRequests(
        ['a', 'b'],
        [{ status: 'idle' }, { status: 'idle' }],
      ),
    ).toEqual([true, true]);
  });
  it('updates only the changed partner without discarding the other result', () => {
    expect(
      planReferenceRequests(['new-a', 'b'], [ready('a'), ready('b')]),
    ).toEqual([true, false]);
    expect(
      planReferenceRequests(['a', 'new-b'], [ready('a'), ready('b')]),
    ).toEqual([false, true]);
  });
  it('still refreshes both when the user explicitly reapplies unchanged inputs', () => {
    expect(planReferenceRequests(['a', 'b'], [ready('a'), ready('b')])).toEqual(
      [true, true],
    );
  });
  it('retries failed or interrupted slots and does not mistake retained stale data for a ready result', () => {
    for (const status of ['error', 'loading', 'idle'] as const) {
      expect(
        planReferenceRequests(
          ['a', 'b'],
          [{ ...ready('a'), status }, ready('b')],
        ),
      ).toEqual([true, false]);
    }
    expect(
      planReferenceRequests(
        ['a', 'b'],
        [{ status: 'ready', requestKey: 'a' }, ready('b')],
      ),
    ).toEqual([true, false]);
  });
  it('evaluates both when both identities change', () => {
    expect(
      planReferenceRequests(['new-a', 'new-b'], [ready('a'), ready('b')]),
    ).toEqual([true, true]);
  });
});
