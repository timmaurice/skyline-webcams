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

  it('resolves labels from the editor hass, not from whatever calls it', async () => {
    el.setConfig({ type: 'custom:skyline-webcams-card', entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: {}, language: 'de' };
    await el.updateComplete;

    const form = el.shadowRoot?.querySelector('ha-form') as HTMLElement & {
      computeLabel?: (schema: { name: string }) => string;
    };
    const computeLabel = form.computeLabel!;

    // This used to call it detached, which Home Assistant never does: ha-form
    // always calls the label function with itself as `this`, and that element
    // carries a `.hass`. That is exactly why handing the method over unbound
    // resolved the translations by accident and the missing entity row never
    // reproduced against a real Home Assistant.
    //
    // The contract worth pinning is whose hass wins. Called with a caller that
    // has a hass of its own, the label must still come out in the language of
    // THIS editor - which only a bound function does.
    expect(computeLabel.call({ hass: { language: 'en' } }, { name: 'entity' })).toBe('Kamera-Entität');
    expect(computeLabel.call({ hass: { language: 'en' } }, { name: 'nope' })).toBe('nope');
  });
});
