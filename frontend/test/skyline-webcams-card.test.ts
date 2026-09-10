import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import '../src/skyline-webcams-card.js';
import { SkylineWebcamsCard } from '../src/skyline-webcams-card.js';

describe('skyline-webcams-card', () => {
  let el: SkylineWebcamsCard;

  beforeEach(() => {
    el = document.createElement('skyline-webcams-card') as SkylineWebcamsCard;
    document.body.appendChild(el);
  });

  afterEach(() => {
    document.body.removeChild(el);
    vi.useRealTimers();
  });

  it('is defined', () => {
    expect(el).toBeInstanceOf(SkylineWebcamsCard);
  });

  it('returns a stub config', () => {
    const config = SkylineWebcamsCard.getStubConfig();
    expect(config).toEqual({
      entity: '',
      aspect_ratio: '16/9',
      show_video_controls: true,
    });
  });

  it('picks a real camera for the stub config so the picker preview works', () => {
    const hass = {
      states: {
        'light.kitchen': { entity_id: 'light.kitchen', state: 'on', attributes: {} },
        'camera.front_door': { entity_id: 'camera.front_door', state: 'idle', attributes: {} },
        'camera.venice': {
          entity_id: 'camera.venice',
          state: 'streaming',
          attributes: { source: 'https://www.skylinewebcams.com/en/webcam/venezia.html' },
        },
      },
    };

    // @ts-expect-error Mocking minimal hass
    const config = SkylineWebcamsCard.getStubConfig(hass, Object.keys(hass.states));
    expect(config.entity).toBe('camera.venice');

    // The picker feeds the stub straight back into setConfig.
    expect(() => el.setConfig(config as never)).not.toThrow();
  });

  it('falls back to any camera when no skyline camera exists', () => {
    const hass = {
      states: {
        'camera.front_door': { entity_id: 'camera.front_door', state: 'idle', attributes: {} },
      },
    };
    // @ts-expect-error Mocking minimal hass
    expect(SkylineWebcamsCard.getStubConfig(hass, ['light.kitchen', 'camera.front_door']).entity).toBe(
      'camera.front_door',
    );
  });

  it('offers grid options for the sections view', () => {
    expect(el.getGridOptions()).toEqual({ rows: 'auto', columns: 12, min_columns: 6 });
  });

  it('throws an error if entity is missing in config', () => {
    expect(() => {
      // @ts-expect-error Testing invalid config
      el.setConfig({});
    }).toThrow('Please define a camera entity.');
  });

  it('sets config correctly', () => {
    el.setConfig({ entity: 'camera.test_cam' });
    expect(el.getCardSize()).toBe(4);
  });

  it('renders nothing if hass or config is missing', async () => {
    await el.updateComplete;
    expect(el.shadowRoot?.querySelector('ha-card')).toBeNull();
  });

  it('renders an error container if entity is not found in hass', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: {} };
    await el.updateComplete;

    const error = el.shadowRoot?.querySelector('.error-container');
    expect(error).not.toBeNull();
    expect(error?.textContent).toContain('Entity not found');
  });

  it('renders the video container when valid state is provided', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': {
          state: 'idle',
          attributes: { friendly_name: 'Test Cam', source: 'http://example.com' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    const container = el.shadowRoot?.querySelector('.video-container');
    expect(container).not.toBeNull();
    const link = el.shadowRoot?.querySelector('.webcam-source-link');
    expect(link).toBeNull(); // show_link is false by default
  });

  it('renders the original link when show_link is true', async () => {
    el.setConfig({ entity: 'camera.test_cam', show_link: true });
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': {
          state: 'idle',
          attributes: { friendly_name: 'Test Cam', source: 'http://example.com/webcam.html' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    const link = el.shadowRoot?.querySelector('.webcam-source-link') as HTMLAnchorElement;
    expect(link).not.toBeNull();
    expect(link.href).toBe('http://example.com/webcam.html');
  });

  it('renders video control buttons when valid state is provided', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': {
          state: 'idle',
          attributes: { friendly_name: 'Test Cam', source: 'http://example.com' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    const controls = el.shadowRoot?.querySelector('.video-controls');
    expect(controls).not.toBeNull();

    const buttons = el.shadowRoot?.querySelectorAll('.control-btn');
    expect(buttons?.length).toBeGreaterThanOrEqual(2); // Play/Pause and Fullscreen
  });

  it('triggers control action handlers', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': {
          state: 'idle',
          attributes: { friendly_name: 'Test Cam', source: 'http://example.com' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    const playBtn = el.shadowRoot?.querySelector('.control-btn') as HTMLButtonElement;
    expect(playBtn).not.toBeNull();

    const mockEvent = new Event('click');
    expect(() => {
      // @ts-expect-error Testing private method
      el._togglePlay(mockEvent);
    }).not.toThrow();

    expect(() => {
      // @ts-expect-error Testing private method
      el._togglePiP(mockEvent);
    }).not.toThrow();

    expect(() => {
      // @ts-expect-error Testing private method
      el._toggleFullscreen(mockEvent);
    }).not.toThrow();
  });

  it('shows an unavailable state instead of a black area when the camera goes unavailable', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    // Home Assistant strips the attributes of an unavailable entity, so entry_id is gone.
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': { state: 'unavailable', attributes: {} },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    const overlay = el.shadowRoot?.querySelector('.unavailable-overlay');
    expect(overlay).not.toBeNull();
    expect(overlay?.textContent?.trim()).not.toBe('');
  });

  it('restarts the stream through the backoff timer once the camera comes back', async () => {
    vi.useFakeTimers();
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': { state: 'unavailable', attributes: {} },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;
    expect(el.shadowRoot?.querySelector('.unavailable-overlay')).not.toBeNull();

    // @ts-expect-error Testing private method
    const startSpy = vi.spyOn(el, '_startStream');
    // The card is on screen, which is what the restart timer checks before it
    // opens a stream.
    // @ts-expect-error Testing private state
    el._isIntersecting = true;

    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': {
          state: 'idle',
          attributes: { friendly_name: 'Test Cam', entry_id: 'abc123' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    expect(startSpy).not.toHaveBeenCalled(); // waits for the backoff delay
    vi.advanceTimersByTime(1000);
    expect(startSpy).toHaveBeenCalled();
    // @ts-expect-error Testing private state
    expect(el._streamUrl).toContain('/api/skylinewebcams_proxy/abc123.m3u8');

    await el.updateComplete;
    expect(el.shadowRoot?.querySelector('.unavailable-overlay')).toBeNull();
  });
  it('does not start a stream on a card that is scrolled out of view', async () => {
    vi.useFakeTimers();
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': { state: 'unavailable', attributes: {} },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    // @ts-expect-error Testing private method
    const startSpy = vi.spyOn(el, '_startStream');
    // Never scrolled into view, so nobody is watching this card.
    // @ts-expect-error Testing private state
    el._isIntersecting = false;

    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': {
          state: 'idle',
          attributes: { friendly_name: 'Test Cam', entry_id: 'abc123' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    vi.advanceTimersByTime(30000);
    expect(startSpy).not.toHaveBeenCalled();
  });
});
