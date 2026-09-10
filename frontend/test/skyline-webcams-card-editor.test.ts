import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import '../src/skyline-webcams-card-editor.js';
import { SkylineWebcamsCardEditor } from '../src/skyline-webcams-card-editor.js';

describe('skyline-webcams-card-editor', () => {
  let el: SkylineWebcamsCardEditor;

  beforeEach(() => {
    el = document.createElement('skyline-webcams-card-editor') as SkylineWebcamsCardEditor;
    document.body.appendChild(el);
  });

  afterEach(() => {
    document.body.removeChild(el);
  });

  it('renders the form once hass and config are set', async () => {
    el.setConfig({ type: 'custom:skyline-webcams-card', entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: {}, language: 'en' };
    await el.updateComplete;

    expect(el.shadowRoot?.querySelector('ha-form')).not.toBeNull();
  });

  it('hands ha-form a label function that does not depend on the caller`s this', async () => {
    el.setConfig({ type: 'custom:skyline-webcams-card', entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: {}, language: 'en' };
    await el.updateComplete;

    const form = el.shadowRoot?.querySelector('ha-form') as HTMLElement & {
      computeLabel?: (schema: { name: string }) => string;
    };
    // ha-form calls this with its own `this`; take it off the element to make
    // sure it still resolves our translations rather than throwing.
    const computeLabel = form.computeLabel!;
    expect(computeLabel({ name: 'entity' })).toBe('Camera Entity');
    expect(computeLabel({ name: 'nope' })).toBe('nope');
  });
});
