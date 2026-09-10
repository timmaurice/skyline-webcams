import { test, expect } from './fixtures/hass';
import { removeState, setState, useDashboard } from './helpers/homeassistant';

const ENTITY = 'camera.e2e_unavailable_webcam';

const ATTRIBUTES = {
  friendly_name: 'E2E Flapping Cam',
  source: 'https://www.skylinewebcams.com/en/webcam/italia/lazio/roma/pantheon.html',
  description: 'Comes and goes',
  country: 'Italy',
  region: 'Lazio',
  place: 'Rome',
  entry_id: 'e2e1111111111111111111111111e2e1',
};

const DASHBOARD = {
  views: [
    {
      title: 'Flaky',
      cards: [{ type: 'custom:skyline-webcams-card', entity: ENTITY }],
    },
  ],
};

let urlPath: string;

test.beforeAll(async () => {
  await setState(ENTITY, 'streaming', ATTRIBUTES);
  urlPath = await useDashboard('unavailable', DASHBOARD);
});

test.afterAll(async () => {
  await removeState(ENTITY);
});

test.describe('An unavailable camera', () => {
  test('says so instead of showing a silent black rectangle', async ({ page }) => {
    // An unavailable camera loses every attribute, entry_id included, so the
    // card cannot build a proxy URL. It used to sit there as a black box; it
    // now has to say what is wrong. Only a browser shows that.
    await page.goto(`/${urlPath}/0`);
    const card = page.locator('skyline-webcams-card');
    await expect(card.locator('ha-card')).toBeVisible({ timeout: 60_000 });
    await expect(card.locator('.unavailable-overlay')).toHaveCount(0);

    // Home Assistant drops the attributes along with availability.
    await setState(ENTITY, 'unavailable', {});

    const overlay = card.locator('.unavailable-overlay');
    await expect(overlay).toBeVisible({ timeout: 30_000 });
    await expect(overlay.locator('.unavailable-msg')).toHaveText(/unavailable/i);
  });

  test('picks the camera up again when it comes back', async ({ page }) => {
    await page.goto(`/${urlPath}/0`);
    const card = page.locator('skyline-webcams-card');
    await expect(card.locator('ha-card')).toBeVisible({ timeout: 60_000 });

    await setState(ENTITY, 'unavailable', {});
    await expect(card.locator('.unavailable-overlay')).toBeVisible({ timeout: 30_000 });

    // Back on the bus with its attributes: the overlay has to clear itself and
    // the player must be pointed at the entry again, without a page reload.
    const requests: string[] = [];
    page.on('request', (request) => requests.push(request.url()));
    await setState(ENTITY, 'streaming', ATTRIBUTES);

    await expect(card.locator('.unavailable-overlay')).toHaveCount(0, { timeout: 30_000 });
    await expect(card.locator('.video-container')).toBeVisible();
    await expect
      .poll(
        () => requests.filter((url) => url.includes(`/api/skylinewebcams_proxy/${ATTRIBUTES.entry_id}.m3u8`)).length,
        { timeout: 30_000 },
      )
      .toBeGreaterThan(0);
  });
});
