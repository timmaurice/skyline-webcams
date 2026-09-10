import { test, expect } from './fixtures/hass';
import { removeState, setState, useDashboard } from './helpers/homeassistant';

const ENTITY = 'camera.e2e_card_webcam';

/**
 * Mirrors what camera.py puts on the entity: `_additional_attributes` (source,
 * description, poster, country, region, place) plus the `entry_id` the card
 * needs to build its proxy URL. Writing the real shape here is the point of an
 * end-to-end test - an invented one would have passed while the card showed
 * nothing.
 */
const ATTRIBUTES = {
  friendly_name: 'E2E Harbour Cam',
  source: 'https://www.skylinewebcams.com/en/webcam/italia/veneto/venezia/piazza-san-marco.html',
  description: 'A harbour, end to end',
  poster: 'https://embed.skylinewebcams.com/img/e2e.jpg',
  country: 'Italy',
  region: 'Veneto',
  place: 'Venice',
  entry_id: 'e2e0000000000000000000000000e2e0',
  entity_picture: '/api/camera_proxy/camera.e2e_card_webcam',
  supported_features: 2,
};

const DASHBOARD = {
  views: [
    {
      title: 'Cams',
      cards: [
        {
          type: 'custom:skyline-webcams-card',
          entity: ENTITY,
          show_link: true,
          show_video_controls: true,
        },
      ],
    },
    { title: 'Elsewhere', cards: [{ type: 'markdown', content: 'nothing here' }] },
  ],
};

let urlPath: string;

test.beforeAll(async () => {
  await setState(ENTITY, 'streaming', ATTRIBUTES);
  urlPath = await useDashboard('card', DASHBOARD);
});

test.afterAll(async () => {
  await removeState(ENTITY);
});

test.describe('The card on a real dashboard', () => {
  test('renders the webcam the camera entity describes', async ({ page }) => {
    await page.goto(`/${urlPath}/0`);

    // Assert on what the card paints, not on the custom element itself: the host
    // has no box of its own, so Playwright rightly calls it hidden.
    const card = page.locator('skyline-webcams-card');
    await expect(card.locator('ha-card')).toBeVisible({ timeout: 60_000 });
    await expect(card.locator('.video-container')).toBeVisible();
    await expect(card.locator('.webcam-title')).toHaveText('E2E Harbour Cam');
    await expect(card.locator('.webcam-location')).toContainText('Venice, Veneto, Italy');
    await expect(card.locator('.webcam-description')).toHaveText('A harbour, end to end');
    await expect(card.locator('a.webcam-source-link')).toHaveAttribute('href', ATTRIBUTES.source);

    // An available camera must not be wearing the unavailable overlay.
    await expect(card.locator('.unavailable-overlay')).toHaveCount(0);
  });

  test('points the player at the integration proxy for this entry', async ({ page }) => {
    // The URL is what ties card and integration together. Building it from the
    // wrong attribute is invisible to a unit test that stubs the player.
    const requests: string[] = [];
    page.on('request', (request) => requests.push(request.url()));

    await page.goto(`/${urlPath}/0`);
    await expect(page.locator('skyline-webcams-card').locator('ha-card')).toBeVisible({ timeout: 60_000 });

    await expect
      .poll(
        () => requests.filter((url) => url.includes(`/api/skylinewebcams_proxy/${ATTRIBUTES.entry_id}.m3u8`)).length,
      )
      .toBeGreaterThan(0);
  });

  test('comes back after leaving the view and returning', async ({ page }) => {
    // Views are torn out of the DOM on a switch. A card that does not notice it
    // is visible again comes back empty - that is exactly how the streaming card
    // failed, and no unit test saw it.
    await page.goto(`/${urlPath}/0`);
    const card = page.locator('skyline-webcams-card');
    await expect(card.locator('.webcam-title')).toHaveText('E2E Harbour Cam', { timeout: 60_000 });

    await page.getByRole('tab', { name: 'Elsewhere' }).click();
    await expect(card).toHaveCount(0);

    await page.getByRole('tab', { name: 'Cams' }).click();
    await expect(card.locator('.webcam-title')).toHaveText('E2E Harbour Cam', { timeout: 30_000 });
    await expect(card.locator('.video-container')).toBeVisible();
  });
});
