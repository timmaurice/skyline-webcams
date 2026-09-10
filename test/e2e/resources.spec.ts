import { test, expect } from './fixtures/hass';
import { resources, useDashboard } from './helpers/homeassistant';

const CARD_PREFIX = '/skylinewebcams_frontend/';

/** Room for a late write to the resource store to show up. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 5_000));

test.describe('Lovelace resource registration', () => {
  test('has exactly one resource for the bundled card', async () => {
    // The registration used to append a resource on every restart. A unit test
    // cannot see that: it needs the store Home Assistant actually persisted.
    //
    // Global setup has already waited for the core to reach RUNNING, which is
    // what fires the registration. The extra settle window is there so a second,
    // duplicate registration gets the chance to land and be counted - polling
    // for "exactly one" would happily pass on the leftover from the last run
    // and never see the duplicate arrive.
    await settle();
    const ours = (await resources()).filter((resource) => resource.url.startsWith(CARD_PREFIX));

    expect(ours).toHaveLength(1);
    expect(ours[0].url).toMatch(/^\/skylinewebcams_frontend\/skyline-webcams-card\.js\?v=/);
  });

  test('serves the bundle and defines its elements without a clash', async ({ page, consoleErrors }) => {
    const urlPath = await useDashboard('resources', {
      views: [{ title: 'Empty', cards: [] }],
    });

    await page.goto(`/${urlPath}/0`);
    await page.waitForFunction(() => customElements.get('skyline-webcams-card') !== undefined, {
      timeout: 60_000,
    });

    // The editor ships in the same bundle and is defined by the same module, so
    // a double-loaded bundle trips over it first. Ask for it the way the UI
    // editor does.
    const editorTag = await page.evaluate(async () => {
      const card = customElements.get('skyline-webcams-card') as unknown as {
        getConfigElement(): Promise<HTMLElement>;
      };
      const editor = await card.getConfigElement();
      return editor.tagName.toLowerCase();
    });
    expect(editorTag).toBe('skyline-webcams-card-editor');
    expect(await page.evaluate(() => !!customElements.get('skyline-webcams-card-editor'))).toBe(true);

    // The bundle also advertises itself to the card picker.
    expect(
      await page.evaluate(() =>
        (window as unknown as { customCards?: { type: string }[] }).customCards?.some(
          (card) => card.type === 'skyline-webcams-card',
        ),
      ),
    ).toBe(true);

    // A bundle loaded twice used to throw on the second define().
    expect(consoleErrors.filter((text) => /has already been used/i.test(text))).toEqual([]);
  });
});
