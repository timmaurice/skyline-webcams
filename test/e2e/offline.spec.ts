import { test, expect } from './fixtures/hass';
import { removeState, setState, useDashboard } from './helpers/homeassistant';

const ENTITY = 'camera.e2e_offline_webcam';

const ONLINE = {
  friendly_name: 'E2E Offline Cam',
  source: 'https://www.skylinewebcams.com/en/webcam/italia/lazio/roma/pantheon.html',
  description: 'Switched off now and then',
  country: 'Italy',
  region: 'Lazio',
  place: 'Rome',
  poster: 'https://cdn.skylinewebcams.com/social165.jpg',
  entry_id: 'e2e2222222222222222222222222e2e2',
  proxy_token: 'e2e-offline-proxy-token',
  offline: false,
};

// What the integration writes for a webcam whose page says OFFLINE: still
// available, idle rather than streaming, with every attribute in place.
const OFFLINE = { ...ONLINE, offline: true };

const DASHBOARD = {
  views: [
    {
      title: 'Offline',
      cards: [{ type: 'custom:skyline-webcams-card', entity: ENTITY }],
    },
  ],
};

const proxyRequests = (requests: string[]) =>
  requests.filter((url) => url.includes(`/api/skylinewebcams_proxy/${ONLINE.proxy_token}.m3u8`)).length;

let urlPath: string;

test.beforeAll(async () => {
  urlPath = await useDashboard('offline', DASHBOARD);
});

test.afterAll(async () => {
  await removeState(ENTITY);
});

test.describe('An offline webcam', () => {
  test('says it is offline and does not try to play', async ({ page }) => {
    await setState(ENTITY, 'idle', OFFLINE);
    const requests: string[] = [];
    page.on('request', (request) => requests.push(request.url()));

    await page.goto(`/${urlPath}/0`);
    const card = page.locator('skyline-webcams-card');
    await expect(card.locator('ha-card')).toBeVisible({ timeout: 60_000 });

    // The poster has LIVE printed on it, so the card has to say in words that
    // nothing is being broadcast - and keep saying which webcam it is.
    const overlay = card.locator('.offline-overlay');
    await expect(overlay).toBeVisible({ timeout: 30_000 });
    await expect(overlay.locator('.offline-title')).toHaveText('Webcam offline');
    await expect(overlay.locator('.offline-msg')).toHaveText(/not broadcasting/i);
    await expect(card.locator('.video-container.offline video')).toHaveAttribute('poster', OFFLINE.poster);
    await expect(card.locator('.webcam-title')).toHaveText('E2E Offline Cam');
    await expect(card.locator('.unavailable-overlay')).toHaveCount(0);

    // Give a start every chance to happen, then check that none did.
    await page.waitForTimeout(2_000);
    expect(proxyRequests(requests)).toBe(0);
  });

  test('starts the stream once the webcam is back', async ({ page }) => {
    await setState(ENTITY, 'idle', OFFLINE);
    await page.goto(`/${urlPath}/0`);
    const card = page.locator('skyline-webcams-card');
    await expect(card.locator('.offline-overlay')).toBeVisible({ timeout: 60_000 });

    // Back on the bus as broadcasting: the overlay has to clear itself and the
    // player must be pointed at the proxy, without a page reload.
    const requests: string[] = [];
    page.on('request', (request) => requests.push(request.url()));
    await setState(ENTITY, 'streaming', ONLINE);

    await expect(card.locator('.offline-overlay')).toHaveCount(0, { timeout: 30_000 });
    await expect(card.locator('.video-container.offline')).toHaveCount(0);
    await expect.poll(() => proxyRequests(requests), { timeout: 30_000 }).toBeGreaterThan(0);

    // And off again, the other way round.
    await setState(ENTITY, 'idle', OFFLINE);
    await expect(card.locator('.offline-overlay')).toBeVisible({ timeout: 30_000 });
  });
});
