import { test, expect } from './fixtures/hass';
import { removeState, setState, useDashboard } from './helpers/homeassistant';

const ENTITY = 'camera.e2e_editor_webcam';

const ATTRIBUTES = {
  friendly_name: 'E2E Editor Cam',
  source: 'https://www.skylinewebcams.com/en/webcam/italia/veneto/venezia/piazza-san-marco.html',
  description: 'Edited end to end',
  country: 'Italy',
  region: 'Veneto',
  place: 'Venice',
  entry_id: 'e2e2222222222222222222222222e2e2',
  supported_features: 2,
};

const DASHBOARD = {
  views: [
    {
      title: 'Editable',
      cards: [{ type: 'custom:skyline-webcams-card', entity: ENTITY }],
    },
  ],
};

let urlPath: string;

test.beforeAll(async () => {
  await setState(ENTITY, 'streaming', ATTRIBUTES);
  // A storage-mode dashboard: the YAML one cannot be edited, which is why the
  // editor was never actually exercised against a real Home Assistant.
  urlPath = await useDashboard('editor', DASHBOARD);
});

test.afterAll(async () => {
  await removeState(ENTITY);
});

test.describe('The card editor in a storage-mode dashboard', () => {
  test('renders every row, entity picker included, with localized labels', async ({ page }) => {
    await page.goto(`/${urlPath}/0?edit=1`);

    const card = page.locator('skyline-webcams-card');
    await expect(card.locator('ha-card')).toBeVisible({ timeout: 60_000 });

    // Open the card's own editor the way a user does: in edit mode a click on
    // the card opens the card dialog.
    // Edit mode puts an "Edit" action under every card.
    await page.getByRole('button', { name: 'Edit', exact: true }).first().click();

    const dialog = page.locator('hui-dialog-edit-card');
    const editor = dialog.locator('skyline-webcams-card-editor');
    await expect(editor).toBeAttached({ timeout: 30_000 });

    // computeLabel used to be handed to ha-form unbound; it only worked
    // because ha-form happens to call it with itself as `this`, and the
    // entity row did not render at all in a harness that did not.
    const form = editor.locator('ha-form');
    await expect(form).toBeVisible();
    await expect(form.locator('ha-entity-picker')).toHaveCount(1);
    await expect(dialog.getByText('Camera Entity', { exact: false })).toBeVisible();
    await expect(dialog.getByText('Aspect Ratio', { exact: false })).toBeVisible();

    // No error banner from a label function that threw.
    expect(await page.locator('text=localize').count()).toBe(0);
  });
});
