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
  const palette = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return {
      background: getComputedStyle(document.body).backgroundColor,
      earth: root.getPropertyValue('--earth').trim(),
      solar: root.getPropertyValue('--sun').trim(),
    };
  });
  assert.deepEqual(palette, {
    background: 'rgb(2, 7, 10)',
    earth: '#0297de',
    solar: '#fc734d',
  });
  await page.locator('.mission-grid').scrollIntoViewIfNeeded();
  await page.waitForFunction(
    () => document.querySelector('.mission-grid').dataset.revealed === 'true',
  );
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
  const lander = page.getByRole('img', {
    name: /Animated view from the reference point/,
  });
  await lander.waitFor();
  await page.waitForFunction(
    () => document.querySelector('.lander-canvas canvas')?.width > 0,
  );
  assert.equal(
    await lander.evaluate((canvas) =>
      canvas
        .getContext('2d')
        .getImageData(0, 0, canvas.width, canvas.height)
        .data.some((value) => value !== 0),
    ),
    true,
  );
  await page
    .getByRole('group', { name: 'Camera', exact: true })
    .getByRole('button', { name: 'Follow Earth' })
    .click();
  await lander.focus();
  await lander.press('ArrowRight');
  assert.equal(
    await page
      .getByRole('button', { name: 'Free look', exact: true })
      .getAttribute('aria-pressed'),
    'true',
  );
  await lander.press('Home');
  assert.equal(
    await page
      .getByRole('button', { name: 'Follow Sun', exact: true })
      .getAttribute('aria-pressed'),
    'true',
  );
  const evaluationCountBeforePlayback = evaluations.length;
  await page
    .getByRole('button', { name: 'Play the period', exact: true })
    .click();
  await page.waitForFunction(
    () => Number(document.querySelector('.cursor-control input').value) > 0,
  );
  await page.getByRole('button', { name: 'Play archived samples' }).click();
  assert.equal(
    await page
      .getByRole('button', { name: 'Play the period', exact: true })
      .count(),
    1,
  );
  await page.getByRole('button', { name: 'Pause archived samples' }).click();
  const pausedCursor = await page.locator('.cursor-control input').inputValue();
  await page.waitForTimeout(180);
  assert.equal(
    await page.locator('.cursor-control input').inputValue(),
    pausedCursor,
  );
  assert.equal(evaluations.length, evaluationCountBeforePlayback);
  assert.ok(
    (await page.locator('.timeline .stats dt').allTextContents()).includes(
      'Next sunset',
    ),
  );
  assert.ok(
    (await page.locator('.timeline .stats dt').allTextContents()).includes(
      'Next Earthset',
    ),
  );
  await page.getByRole('button', { name: 'Sky dome', exact: true }).click();
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

  // Terrain requires a deliberate opt-in; the UI retains the returned evidence.
  await scenario.getByLabel('Horizon model').selectOption('terrain');
  const consent = scenario.getByRole('checkbox');
  assert.equal(await consent.isChecked(), false);
  await consent.check();
  const terrainResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/reference/evaluations' &&
      response.request().method() === 'POST' &&
      response.request().postDataJSON()?.horizonMode === 'terrain',
  );
  await page.getByRole('button', { name: /Update comparison/ }).click();
  const terrain = await terrainResponse;
  assert.equal(terrain.status(), 200);
  const terrainData = await terrain.json();
  assert.equal(terrainData.horizonMode, 'terrain');
  assert.equal(
    terrainData.provenance.terrain.compatibility.frameStatus,
    'approximate',
  );
  assert.equal(
    terrainData.provenance.terrain.compatibility.transformationApplied,
    false,
  );
  await matched.waitFor({ state: 'visible', timeout: 45_000 });
  await page.locator('.provenance-details summary').click();
  assert.ok(
    (await page.locator('.provenance-hash').innerText()).includes(
      terrainData.provenance.terrain.artifactSha256,
    ),
  );
  await page.locator('.provenance-details summary').click();

  // The keyboard playhead and sample-driven playback update the dome.
  const cursor = page.locator('.cursor-control input');
  await cursor.focus();
  await cursor.press('Home');
  const markerBefore = await page
    .locator('.dome-marker-position.sun')
    .getAttribute('style');
  await cursor.press('ArrowRight');
  assert.equal(await cursor.inputValue(), '1');
  assert.notEqual(
    await page.locator('.dome-marker-position.sun').getAttribute('style'),
    markerBefore,
  );
  assert.ok(
    await page
      .locator('.dome-marker-position.sun')
      .evaluate(
        (element) =>
          parseFloat(getComputedStyle(element).transitionDuration) > 0,
      ),
  );
  assert.ok(
    (await page.locator('.dome-readout > strong').innerText()).includes(
      '01:00',
    ),
  );
  await page.getByRole('button', { name: 'Play archived samples' }).click();
  await page.waitForFunction(
    () => Number(document.querySelector('.cursor-control input').value) > 1,
  );
  await page.getByRole('button', { name: 'Pause archived samples' }).click();

  await page.getByRole('button', { name: 'Polar map', exact: true }).click();
  const contrast = initial.find(
    (entry) => entry.data.siteId === 'lola-site23-reference',
  ).data;
  await page
    .locator('.map-site-key')
    .getByRole('button', { name: contrast.site })
    .click();
  assert.equal(
    await scenario.getByLabel('Reference site').inputValue(),
    contrast.siteId,
  );
  assert.equal(
    await scenario.getByLabel('Horizon model').inputValue(),
    'geometric',
  );
  assert.equal(
    await scenario
      .getByLabel('Horizon model')
      .locator('option[value="terrain"]')
      .isDisabled(),
    true,
  );
  const mapSvg = page.locator('.polar-map svg');
  const beforeZoom = await mapSvg.getAttribute('viewBox');
  await page.getByRole('button', { name: 'Zoom in map' }).click();
  assert.notEqual(await mapSvg.getAttribute('viewBox'), beforeZoom);
  await page.getByRole('button', { name: 'Reset map', exact: true }).click();
  assert.equal(await mapSvg.getAttribute('viewBox'), beforeZoom);

  // Archive coverage is a hard boundary, including the headline six-week shift.
  assert.equal(
    await page
      .getByRole('button', { name: '+6 WEEKS', exact: true })
      .isDisabled(),
    true,
  );
  const shift = page.getByRole('slider', { name: /Shift mission date/ });
  await shift.focus();
  await shift.press('End');
  assert.equal(
    await page
      .getByRole('button', { name: /Simulate mission shift/ })
      .isDisabled(),
    true,
  );
  await page.getByRole('button', { name: '+7 DAYS', exact: true }).click();
  const shiftedResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/reference/evaluations' &&
      response.request().method() === 'POST' &&
      response.request().postDataJSON()?.startUtc === '2026-11-21T00:00:00Z',
  );
  await page.getByRole('button', { name: /Simulate mission shift/ }).click();
  const shifted = await shiftedResponse;
  assert.equal(shifted.status(), 200);
  const shiftedData = await shifted.json();
  assert.equal(shiftedData.series.length, 24);
  await matched.waitFor({ state: 'visible', timeout: 45_000 });
  await page.locator('.shift-results').waitFor();
  const measuredResponses = await Promise.all(evaluations);
  const originalShift = measuredResponses.find(
    (entry) =>
      entry.data.provenance.ephemeris.startUtc === '2026-11-14T00:00:00Z' &&
      entry.data.series.length === 24,
  ).data;
  for (const [key, property] of [
    ['sun', 'pctSun'],
    ['earth', 'pctEarth'],
    ['joint', 'pctBoth'],
  ]) {
    const metric = page.locator(`.shift-results [data-metric="${key}"]`);
    const displayed = parseFloat(
      await metric.locator('.metric-difference .motion-value').innerText(),
    );
    assert.ok(
      Math.abs(
        displayed -
          (shiftedData.metrics[property] - originalShift.metrics[property]),
      ) < 0.051,
    );
    assert.equal(
      await metric.locator('.metric-after').innerText(),
      `${shiftedData.metrics[property].toFixed(1)}%`,
    );
  }
  await page.getByLabel('Mission duration').selectOption('3');
  await page.locator('.shift-results').waitFor({ state: 'hidden' });
  await page.getByLabel('Mission duration').selectOption('1');
  await page.locator('.shift-results').waitFor();
  await page.getByRole('button', { name: 'Sky dome', exact: true }).click();
  assert.equal(await cursor.inputValue(), '0');
  const requestCount = evaluations.length;
  const lesson = page.getByRole('slider', {
    name: 'Illustrative horizon elevation',
  });
  await lesson.focus();
  await lesson.press('End');
  assert.equal(
    await page.locator('.lesson-values [role="status"]').innerText(),
    'Occluded',
  );
  await lesson.press('Home');
  assert.equal(
    await page.locator('.lesson-values [role="status"]').innerText(),
    'Fully visible',
  );
  assert.equal(
    evaluations.length,
    requestCount,
    'The illustrative lesson must not submit evaluations.',
  );
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
  const mobile = await browser.newPage({
    viewport: { width: 390, height: 844 },
    reducedMotion: 'reduce',
  });
  mobile.on('pageerror', (error) => pageErrors.push(error.message));
  await mobile.goto(web);
  await mobile
    .getByText('Results match the inputs above.', { exact: true })
    .waitFor({ timeout: 45_000 });
  assert.equal(
    await mobile.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  assert.equal(
    await mobile
      .locator('.hero-copy')
      .evaluate((element) => getComputedStyle(element).animationName),
    'none',
  );
  await mobile.locator('.visual-stage').scrollIntoViewIfNeeded();
  await mobile.getByRole('button', { name: 'Sky dome', exact: true }).click();
  assert.equal(
    await mobile.locator('.experience').getAttribute('data-motion'),
    'reduced',
  );
  assert.equal(
    await mobile
      .locator('.dome-marker-position.sun')
      .evaluate((element) => getComputedStyle(element).transitionDuration),
    '0s',
  );
  assert.equal(
    await mobile
      .locator('.headline-line')
      .first()
      .evaluate((element) => getComputedStyle(element).animationName),
    'none',
  );
  await mobile.emulateMedia({ reducedMotion: 'no-preference' });
  await mobile.waitForFunction(
    () => document.querySelector('.experience').dataset.motion === 'ready',
  );
  assert.equal(
    await mobile
      .locator('.headline-line')
      .first()
      .evaluate((element) => getComputedStyle(element).opacity),
    '1',
  );
  assert.equal(
    await mobile
      .locator('.headline-line')
      .first()
      .evaluate((element) => getComputedStyle(element).animationName),
    'none',
  );
  await mobile.close();
  assert.deepEqual(pageErrors, []);
  console.log(
    JSON.stringify({
      web: webOrigin,
      api: apiOrigin,
      initialEvaluations: initial.length,
      updatedVisibilityRule: 'full-disc',
      terrain: 'verified with explicit frame acceptance',
      mapSelection: 'ok',
      sharedCursorAndPlayback: 'ok',
      landerViewAndPlaybackOwnership: 'ok',
      landerKeyboardCamera: 'ok',
      palette: 'midnight / electric blue / cantaloupe',
      motionAndReducedMotion: 'ok',
      shiftPercentagePointDifferences: 'verified against API responses',
      illustrativeHorizonLesson: 'isolated from mission results',
      missionShift: '7 days; 6 weeks blocked by coverage',
      mobileOverflow: false,
      readiness: 'ready',
      invalidRangeStatus: 422,
      browserErrors: 0,
    }),
  );
} finally {
  await browser.close();
}
