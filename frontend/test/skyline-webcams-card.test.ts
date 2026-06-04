import { describe, it, expect, beforeEach, afterEach } from 'vitest';
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
});
