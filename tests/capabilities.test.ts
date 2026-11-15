import { afterEach, describe, expect, it, vi } from 'vitest';
import { capabilitiesSchema, customModeEnabled } from '@/domain/capabilities';
import { fetchCapabilities } from '@/lib/api-client';

const body = (enabled: boolean, terrainEnabled: boolean) => ({
  schemaVersion: 'lunarwindow.capabilities.v1' as const,
  customEvaluation: { enabled, terrainEnabled },
});

afterEach(() => vi.unstubAllGlobals());

describe('custom feature availability', () => {
  it('blocks pending, failed and disabled states without assuming availability', () => {
    for (const mode of ['geometric', 'terrain'] as const) {
      expect(customModeEnabled({ status: 'loading' }, mode)).toBe(false);
      expect(
        customModeEnabled({ status: 'error', message: 'Offline' }, mode),
      ).toBe(false);
      expect(
        customModeEnabled({ status: 'ready', data: body(false, false) }, mode),
      ).toBe(false);
    }
  });
  it('enables each mode only when its deployment flags allow it', () => {
    expect(
      customModeEnabled(
        { status: 'ready', data: body(true, false) },
        'geometric',
      ),
    ).toBe(true);
    expect(
      customModeEnabled(
        { status: 'ready', data: body(true, false) },
        'terrain',
      ),
    ).toBe(false);
    expect(
      customModeEnabled({ status: 'ready', data: body(true, true) }, 'terrain'),
    ).toBe(true);
  });
  it('rejects malformed flags, unsupported versions and inconsistent terrain opt-ins', () => {
    for (const invalid of [
      null,
      {},
      { ...body(true, false), schemaVersion: 'v2' },
      body(false, true),
      {
        schemaVersion: 'lunarwindow.capabilities.v1',
        customEvaluation: { enabled: 'false', terrainEnabled: false },
      },
    ]) {
      expect(capabilitiesSchema.safeParse(invalid).success).toBe(false);
    }
  });
  it('uses an uncached abortable GET and preserves server disabled flags', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(body(false, false)));
    vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    expect(await fetchCapabilities(controller.signal)).toEqual(
      body(false, false),
    );
    expect(fetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/capabilities$/),
      expect.objectContaining({ cache: 'no-store', signal: controller.signal }),
    );
    expect(fetch.mock.calls[0][1].method).toBeUndefined();
  });
  it('surfaces old APIs, unreachable APIs and invalid successful bodies', async () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    fetch.mockResolvedValueOnce(
      Response.json({ detail: 'Not Found' }, { status: 404 }),
    );
    await expect(fetchCapabilities()).rejects.toMatchObject({ status: 404 });
    fetch.mockRejectedValueOnce(new TypeError('Offline'));
    await expect(fetchCapabilities()).rejects.toMatchObject({ status: 0 });
    fetch.mockResolvedValueOnce(Response.json({}));
    await expect(fetchCapabilities()).rejects.toMatchObject({
      code: 'invalid_capabilities',
    });
  });
});
