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

    const form = editor.locator('ha-form');
    await expect(form).toBeVisible();
    await expect(form.locator('ha-entity-picker')).toHaveCount(1);
    await expect(dialog.getByText('Camera Entity', { exact: false })).toBeVisible();
    await expect(dialog.getByText('Aspect Ratio', { exact: false })).toBeVisible();

    // Everything above passes with computeLabel handed over unbound, which is
    // why the reported missing entity row does not reproduce: real ha-form
    // calls the label function with itself as `this`, and it carries a `.hass`
    // of its own, so an unbound `this._computeLabel` resolved our translations
    // by accident. The rows above are worth asserting, but they cannot tell
    // the two apart - and neither can a detached call, because localize falls
    // back to English rather than throwing on a missing hass.
    //
    // What does tell them apart is whose hass the label follows. Called with
    // two different languages as `this`, a bound function ignores both and
    // answers from the editor's own hass twice; an unbound one answers from
    // the caller and gives two different labels.
    const labelsFromForeignLanguages = await form.evaluate((el) => {
      const computeLabel = (el as HTMLElement & { computeLabel?: (schema: { name: string }) => string }).computeLabel;
      if (typeof computeLabel !== 'function') {
        return ['ha-form was given no computeLabel at all'];
      }
      return ['de', 'en'].map((language) => computeLabel.call({ hass: { language } }, { name: 'entity' }));
    });

    expect(labelsFromForeignLanguages[0]).toBe(labelsFromForeignLanguages[1]);
    // And it is our translation, not the bare schema name.
    expect(labelsFromForeignLanguages[0]).not.toBe('entity');
  });
});
