import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

// Playwright is installed in temporary CI storage, outside application dependencies.
const { chromium } = createRequire(import.meta.url)('playwright');
const web = process.env.LUNARWINDOW_WEB_URL ?? 'http://localhost:3000';
const api = process.env.LUNARWINDOW_API_URL ?? 'http://localhost:8000';
const webOrigin = new URL(web).origin;
const apiOrigin = new URL(api).origin;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const pageErrors = [];
  const evaluations = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (
      url.pathname === '/api/reference/evaluations' &&
      response.request().method() === 'POST'
    ) {
      evaluations.push(
        response
          .json()
          .then((data) => ({
            status: response.status(),
            origin: url.origin,
            cors: response.headers()['access-control-allow-origin'],
            data,
          }))
          .catch((error) => ({ error: error.message })),
      );
    }
  });
  const opened = await page.goto(web, { waitUntil: 'domcontentloaded' });
  assert.equal(opened.status(), 200);
  const matched = page.getByText('Results match the inputs above.', {
    exact: true,
  });
  await matched.waitFor({ state: 'visible', timeout: 45_000 });
  await page
    .getByRole('heading', { name: 'Compare two scenarios', exact: true })
    .waitFor();
  const initial = await Promise.all(evaluations);
  assert.ok(initial.length >= 2, 'Both default scenarios must call the API.');
  for (const response of initial) {
    assert.equal(response.status, 200);
    assert.equal(response.origin, apiOrigin);
    assert.equal(response.cors, webOrigin);
    assert.equal(response.data.dataMode, 'reference');
    assert.equal(response.data.horizonMode, 'geometric');
    assert.equal(response.data.series.length, 720);
  }
  const scenario = page.getByRole('group', { name: 'Scenario A' });
  await scenario.getByLabel('Visible when').selectOption('full-disc');
  await page
    .getByText(
      'Inputs changed: results below are out of date until you update.',
      { exact: true },
    )
    .waitFor();
  const updatedResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/reference/evaluations' &&
      response.request().method() === 'POST' &&
      response.request().postDataJSON()?.visibilityRule === 'full-disc',
  );
  await page.getByRole('button', { name: /Update comparison/ }).click();
  const updated = await updatedResponse;
  assert.equal(updated.status(), 200);
  assert.equal((await updated.json()).calculation.visibilityRule, 'full-disc');
  await matched.waitFor({ state: 'visible', timeout: 45_000 });
  const probe = await page.evaluate(async (origin) => {
    const ready = await fetch(`${origin}/api/ready`);
    const readiness = await ready.json();
    const invalid = await fetch(`${origin}/api/reference/evaluations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        siteId: 'lola-site01-reference',
        horizonMode: 'geometric',
        startUtc: '2026-11-01T00:00:00Z',
        endUtc: '2026-11-15T00:00:00Z',
      }),
    });
    return {
      readinessStatus: ready.status,
      readiness,
      invalidStatus: invalid.status,
      invalid: await invalid.json(),
    };
  }, apiOrigin);
  assert.equal(probe.readinessStatus, 200);
  assert.equal(probe.readiness.status, 'ready');
  assert.equal(probe.invalidStatus, 422);
  assert.equal(probe.invalid.error.code, 'validation_error');
  assert.deepEqual(pageErrors, []);
  console.log(
    JSON.stringify({
      web: webOrigin,
      api: apiOrigin,
      initialEvaluations: initial.length,
      updatedVisibilityRule: 'full-disc',
      readiness: 'ready',
      invalidRangeStatus: 422,
      browserErrors: 0,
    }),
  );
} finally {
  await browser.close();
}
