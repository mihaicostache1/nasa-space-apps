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
  // A sleeping/unreachable API must not block the bundled reference explorer.
  const offline = await browser.newPage();
  offline.setDefaultTimeout(30_000);
  const offlineErrors = [];
  const offlineReferenceRequests = [];
  offline.on('pageerror', (error) => offlineErrors.push(error.message));
  offline.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/reference/'))
      offlineReferenceRequests.push(request);
  });
  await offline.route(`${apiOrigin}/**`, (route) => route.abort('failed'));
  const offlineStart = performance.now();
  const offlineOpened = await offline.goto(web, {
    waitUntil: 'domcontentloaded',
  });
  assert.equal(offlineOpened.status(), 200);
  await offline
    .getByText('Results match the inputs above.', { exact: true })
    .waitFor();
  await offline.getByText(/Precomputed reference snapshots · A, B/).waitFor();
  await offline.waitForFunction(
    () => document.querySelector('.lander-canvas canvas')?.width > 0,
  );
  const offlineStartupMs = Math.round(performance.now() - offlineStart);
  await offline
    .getByRole('button', { name: 'Play the period', exact: true })
    .click();
  await offline.waitForFunction(
    () => Number(document.querySelector('.cursor-control input').value) > 0,
  );
  await offline.getByRole('button', { name: 'Pause', exact: true }).click();
  assert.equal(
    offlineReferenceRequests.length,
    0,
    'Startup and playback must not need the API.',
  );
  await offline.getByRole('button', { name: /Update comparison/ }).click();
  await offline
    .getByText(
      'Update failed. Previous results are retained; see the errors above.',
      { exact: true },
    )
    .waitFor();
  assert.equal(
    offlineReferenceRequests.length,
    2,
    'An explicit update must still use the API.',
  );
  await offline.getByText(/Precomputed reference snapshots · A, B/).waitFor();
  assert.equal(
    await offline
      .getByText('Results match the inputs above.', { exact: true })
      .count(),
    0,
  );
  // A fresh page restores snapshots; a changed A replaces only its own source label.
  await offline.reload({ waitUntil: 'domcontentloaded' });
  await offline.unroute(`${apiOrigin}/**`);
  const snapshotScenario = offline.getByRole('group', { name: 'Scenario A' });
  await snapshotScenario.locator('.scenario-advanced summary').click();
  await snapshotScenario.getByLabel('Visible when').selectOption('full-disc');
  const beforeSnapshotUpdate = offlineReferenceRequests.length;
  await offline.getByRole('button', { name: /Update comparison/ }).click();
  await offline
    .getByText('Results match the inputs above.', { exact: true })
    .waitFor();
  assert.equal(offlineReferenceRequests.length, beforeSnapshotUpdate + 1);
  await offline.getByText(/Precomputed reference snapshots · B ·/).waitFor();
  await offline.locator('.provenance-details > summary').click();
  await offline
    .getByText('Scenario A · API evaluation', { exact: true })
    .waitFor();
  await offline
    .getByText(/Scenario B · Precomputed reference snapshot/)
    .waitFor();
  assert.deepEqual(offlineErrors, []);
  await offline.close();

  const page = await browser.newPage();
  const pageErrors = [];
  const evaluations = [];
  const customRequests = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/custom/evaluations')
      customRequests.push(request);
  });
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
  const portraitImage = page.locator('.moon-object img');
  assert.equal(
    await portraitImage.evaluate(
      (element) => getComputedStyle(element).animationName,
    ),
    'portrait-moon-rotation',
  );
  await page
    .getByRole('button', { name: 'Pause Moon rotation', exact: true })
    .click();
  assert.equal(
    await portraitImage.evaluate(
      (element) => getComputedStyle(element).animationPlayState,
    ),
    'paused',
  );
  await page
    .getByRole('button', { name: 'Resume Moon rotation', exact: true })
    .click();
  assert.equal(
    await portraitImage.evaluate(
      (element) => getComputedStyle(element).animationPlayState,
    ),
    'running',
  );
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
    background: 'rgb(5, 10, 14)',
    earth: '#18b8f2',
    solar: '#ff704f',
  });
  await page.locator('.mission-grid').scrollIntoViewIfNeeded();
  await page.waitForFunction(
    () => document.querySelector('.mission-grid').dataset.revealed === 'true',
  );
  await page
    .getByRole('heading', { name: 'Compare two scenarios', exact: true })
    .waitFor();
  assert.equal(
    evaluations.length,
    0,
    'Initial reference results come from the verified release.',
  );
  await page.getByText(/Precomputed reference snapshots · A, B/).waitFor();
  await page.getByRole('button', { name: /Update comparison/ }).click();
  await matched.waitFor({ state: 'visible', timeout: 45_000 });
  const initial = await Promise.all(evaluations);
  assert.equal(
    initial.length,
    2,
    'Explicitly refreshing both unchanged scenarios must call the API.',
  );
  assert.equal(await page.locator('.snapshot-note').count(), 0);
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
    (
      await page.locator('.comparison-secondary-metrics dt').allTextContents()
    ).includes('Next sunset'),
  );
  assert.ok(
    (
      await page.locator('.comparison-secondary-metrics dt').allTextContents()
    ).includes('Next Earthset'),
  );
  await page.getByRole('button', { name: 'Sky dome', exact: true }).click();
  await scenario.locator('.scenario-advanced summary').click();
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
  const beforeSingleUpdate = evaluations.length;
  await page.getByRole('button', { name: /Update comparison/ }).click();
  const updated = await updatedResponse;
  assert.equal(updated.status(), 200);
  assert.equal((await updated.json()).calculation.visibilityRule, 'full-disc');
  await matched.waitFor({ state: 'visible', timeout: 45_000 });
  assert.equal(
    evaluations.length,
    beforeSingleUpdate + 1,
    'Editing A must not resubmit the unchanged ready B scenario.',
  );

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
    (await page.locator('p.provenance-hash').innerText()).includes(
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
  await page.locator('.mission-planning-details > summary').click();
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
  assert.equal(
    customRequests.length,
    0,
    'Custom acquisition must run only on explicit submission.',
  );
  assert.equal(await page.locator('.comparison-summary').count(), 2);
  for (const summary of await page.locator('.comparison-summary').all()) {
    assert.equal(
      await summary.locator('.comparison-primary-metrics dt').count(),
      4,
    );
  }
  const custom = page.locator('#evaluate');
  await custom
    .getByRole('button', { name: 'Check availability again' })
    .waitFor();
  const customSubmit = custom.getByRole('button', {
    name: 'Evaluate coordinates',
  });
  const customTerrain = custom.getByRole('button', {
    name: 'Terrain-aware',
    exact: true,
  });
  let customEvaluationStatus = null;
  if (await customSubmit.isEnabled()) {
    await custom.getByLabel('Lunar latitude (°)', { exact: true }).fill('91');
    await custom.getByRole('button', { name: 'Evaluate coordinates' }).click();
    await custom.locator('.custom-issues').waitFor();
    assert.equal(customRequests.length, 0);
    await custom.getByLabel('Lunar latitude (°)', { exact: true }).fill('-89');
    await custom
      .getByLabel('Ground elevation above reference sphere (m)', {
        exact: true,
      })
      .fill('0');
    await custom
      .getByLabel('End (UTC, excluded)', { exact: true })
      .fill('2026-11-14T03:00');
    const customResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/custom/evaluations',
    );
    await custom.getByRole('button', { name: 'Evaluate coordinates' }).click();
    const response = await customResponse;
    customEvaluationStatus = response.status();
    if (response.status() === 200) {
      const value = await response.json();
      assert.equal(value.dataMode, 'custom');
      assert.equal(value.series.length, 3);
      await custom.locator('.custom-completed').waitFor();
      assert.equal(
        await custom.locator('.custom-primary-metrics dt').count(),
        4,
      );
      await custom
        .getByLabel('Observer height above ground (m)', { exact: true })
        .fill('3');
      await custom.locator('.custom-stale').waitFor();
    } else {
      assert.ok(
        [404, 502, 503, 504].includes(response.status()),
        'Custom service state must be represented honestly.',
      );
      await custom.getByRole('alert').waitFor();
    }
    if (await customTerrain.isEnabled()) {
      const calls = customRequests.length;
      await custom
        .getByRole('button', { name: 'Terrain-aware', exact: true })
        .click();
      await custom.getByLabel('Lunar latitude (°)', { exact: true }).fill('0');
      await custom.getByRole('checkbox').check();
      await custom
        .getByRole('button', { name: 'Evaluate coordinates' })
        .click();
      await custom.locator('.custom-issues').waitFor();
      assert.equal(
        customRequests.length,
        calls,
        'Unsupported terrain coordinates must not trigger a geometric fallback.',
      );
      assert.equal(
        await custom
          .getByRole('button', { name: 'Terrain-aware', exact: true })
          .getAttribute('aria-pressed'),
        'true',
      );
    }
  } else {
    assert.equal(
      customRequests.length,
      0,
      'Disabled or unknown custom availability must prevent acquisition.',
    );
    assert.equal(await customTerrain.isDisabled(), true);
    assert.ok(
      (await custom.locator('#custom-availability').innerText()).length > 0,
    );
  }
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
  await page.evaluate(() =>
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: 'instant',
    }),
  );
  await page.waitForFunction(
    () =>
      document
        .querySelector('nav a[href="#methodology"]')
        ?.getAttribute('aria-current') === 'location',
  );
  const mobile = await browser.newPage({
    viewport: { width: 390, height: 844 },
    reducedMotion: 'reduce',
  });
  mobile.on('pageerror', (error) => pageErrors.push(error.message));
  await mobile.goto(web);
  assert.equal(
    await mobile
      .locator('.moon-object img')
      .evaluate((element) => getComputedStyle(element).animationName),
    'none',
  );
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
  await mobile.setViewportSize({ width: 320, height: 844 });
  assert.equal(
    await mobile.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  const clippedControls = await mobile
    .locator('input, select, button')
    .evaluateAll((elements) =>
      elements
        .filter((element) => {
          const box = element.getBoundingClientRect();
          return (
            element.checkVisibility() &&
            box.width > 0 &&
            (box.left < -1 || box.right > innerWidth + 1)
          );
        })
        .map((element) => element.id || element.textContent),
    );
  assert.deepEqual(
    clippedControls,
    [],
    'Visible controls must fit at 320px, not merely be clipped by a container.',
  );
  await mobile.close();
  assert.deepEqual(pageErrors, []);
  console.log(
    JSON.stringify({
      web: webOrigin,
      api: apiOrigin,
      initialEvaluations: initial.length,
      startupReferenceRequests: 0,
      startupWorksWithoutApi: true,
      offlineStartupMs,
      updatedVisibilityRule: 'full-disc',
      terrain: 'verified with explicit frame acceptance',
      mapSelection: 'ok',
      sharedCursorAndPlayback: 'ok',
      landerViewAndPlaybackOwnership: 'ok',
      landerKeyboardCamera: 'ok',
      palette: 'aerospace dark / sunlight orange / Earth visibility blue',
      customCoordinates:
        'explicit submission, validation, real service state, no terrain fallback',
      customEvaluationStatus,
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
