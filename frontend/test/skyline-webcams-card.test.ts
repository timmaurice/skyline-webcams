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

  it('falls back to an empty entity when there is no camera to stub with', () => {
    // The suite used to assert this and "picks a real camera" side by side, as
    // if the stub both did and did not name one. There is only one case where
    // it cannot: a Home Assistant with no camera entity at all.
    const config = SkylineWebcamsCard.getStubConfig();
    expect(config).toEqual({
      entity: '',
      aspect_ratio: '16/9',
      show_video_controls: true,
    });

    // And that config still has to preview, which is the whole point of a stub.
    expect(() => el.setConfig(config as never)).not.toThrow();
  });

  it('renders a hint rather than an error when no entity is configured', async () => {
    el.setConfig(SkylineWebcamsCard.getStubConfig() as never);
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: {} };
    await el.updateComplete;

    const hint = el.shadowRoot?.querySelector('.no-entity-hint');
    expect(hint).not.toBeNull();
    expect(hint?.textContent?.trim()).toBe('Pick a camera entity to show a webcam here.');
    // Not the error card the picker showed before.
    expect(el.shadowRoot?.querySelector('.error-container')).toBeNull();
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
    expect(el.getGridOptions()).toEqual({ columns: 'full', min_columns: 6, rows: 'auto' });
  });

  it('still rejects a config that is not there at all', () => {
    expect(() => {
      // @ts-expect-error Testing invalid config
      el.setConfig(undefined);
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
    // Home Assistant strips the attributes of an unavailable entity, so proxy_token is gone.
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
          attributes: { friendly_name: 'Test Cam', entry_id: 'abc123', proxy_token: 'tok-123' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    expect(startSpy).not.toHaveBeenCalled(); // waits for the backoff delay
    vi.advanceTimersByTime(1000);
    expect(startSpy).toHaveBeenCalled();
    // @ts-expect-error Testing private state
    expect(el._streamUrl).toContain('/api/skylinewebcams_proxy/tok-123.m3u8');

    await el.updateComplete;
    expect(el.shadowRoot?.querySelector('.unavailable-overlay')).toBeNull();
  });
  const OFFLINE_CAM = {
    state: 'idle',
    attributes: {
      friendly_name: 'Rome - Pantheon',
      place: 'Rome',
      region: 'Lazio',
      country: 'Italy',
      description: 'View of the Pantheon',
      source: 'https://www.skylinewebcams.com/en/webcam/italia/lazio/roma/pantheon.html',
      poster: 'https://cdn.skylinewebcams.com/social165.jpg',
      entry_id: 'abc123',
      proxy_token: 'tok-123',
      offline: true,
    },
  };

  it('says the webcam is offline instead of playing it', async () => {
    el.setConfig({ entity: 'camera.test_cam', show_link: true });
    const callWS = vi.fn(() => Promise.resolve({ url: '/api/mock' }));
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: { 'camera.test_cam': OFFLINE_CAM }, callWS };
    await el.updateComplete;

    const overlay = el.shadowRoot?.querySelector('.offline-overlay');
    expect(overlay).not.toBeNull();
    // Real text, not only an icon: a screen reader has to be able to say it.
    expect(overlay?.getAttribute('role')).toBe('status');
    expect(overlay?.querySelector('.offline-title')?.textContent?.trim()).toBe('Webcam offline');
    expect(overlay?.querySelector('.offline-msg')?.textContent?.trim()).toBe(
      'It is not broadcasting on SkylineWebcams right now.',
    );
    // The poster stays, dimmed, and so does everything around the video.
    expect(el.shadowRoot?.querySelector('.video-container.offline')).not.toBeNull();
    expect(el.shadowRoot?.querySelector('video')?.getAttribute('poster')).toBe(OFFLINE_CAM.attributes.poster);
    expect(el.shadowRoot?.querySelector('.webcam-title')?.textContent?.trim()).toBe('Rome - Pantheon');
    expect(el.shadowRoot?.querySelector('.webcam-location')?.textContent).toContain('Rome, Lazio, Italy');
    expect(el.shadowRoot?.querySelector('.webcam-description')).not.toBeNull();
    expect(el.shadowRoot?.querySelector('.webcam-source-link')).not.toBeNull();
    // A play button for a stream that is not there would only invite a click.
    expect(el.shadowRoot?.querySelector('.video-controls')).toBeNull();
    expect(el.shadowRoot?.querySelector('.unavailable-overlay')).toBeNull();

    // On screen and visible: whatever would start the stream, it must not.
    // @ts-expect-error Testing private method
    const initSpy = vi.spyOn(el, '_initHls');
    // @ts-expect-error Testing private state
    el._isIntersecting = true;
    // @ts-expect-error Testing private method
    el._updatePlaybackState();
    // @ts-expect-error Testing private method
    await el._startStream();
    await el.updateComplete;

    expect(initSpy).not.toHaveBeenCalled();
    expect(callWS).not.toHaveBeenCalled();
    // @ts-expect-error Testing private state
    expect(el._streamUrl).toBeUndefined();
    // @ts-expect-error Testing private state
    expect(el._loading).toBe(false);
    expect(el.shadowRoot?.querySelector('.loading-overlay')).toBeNull();
  });

  it('localizes the offline overlay', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = { language: 'de', states: { 'camera.test_cam': OFFLINE_CAM }, callWS: vi.fn() };
    await el.updateComplete;

    expect(el.shadowRoot?.querySelector('.offline-title')?.textContent?.trim()).toBe('Webcam offline');
    expect(el.shadowRoot?.querySelector('.offline-msg')?.textContent?.trim()).toBe(
      'Sie sendet gerade nicht auf SkylineWebcams.',
    );
  });

  it('stops a playing stream when the webcam goes offline', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    const online = { ...OFFLINE_CAM, state: 'streaming', attributes: { ...OFFLINE_CAM.attributes, offline: false } };
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: { 'camera.test_cam': online }, callWS: vi.fn() };
    await el.updateComplete;
    // @ts-expect-error Testing private method
    await el._startStream();
    // @ts-expect-error Testing private state
    expect(el._streamUrl).toContain('/api/skylinewebcams_proxy/tok-123.m3u8');

    // @ts-expect-error Mocking minimal hass
    el.hass = { states: { 'camera.test_cam': OFFLINE_CAM }, callWS: vi.fn() };
    await el.updateComplete;

    // @ts-expect-error Testing private state
    expect(el._streamUrl).toBeUndefined();
    expect(el.shadowRoot?.querySelector('.offline-overlay')).not.toBeNull();
  });

  it('starts the stream once the webcam is broadcasting again', async () => {
    vi.useFakeTimers();
    el.setConfig({ entity: 'camera.test_cam' });
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: { 'camera.test_cam': OFFLINE_CAM }, callWS: vi.fn() };
    await el.updateComplete;
    expect(el.shadowRoot?.querySelector('.offline-overlay')).not.toBeNull();

    // @ts-expect-error Testing private method
    const startSpy = vi.spyOn(el, '_startStream');
    // @ts-expect-error Testing private state
    el._isIntersecting = true;

    const online = { ...OFFLINE_CAM, state: 'streaming', attributes: { ...OFFLINE_CAM.attributes, offline: false } };
    // @ts-expect-error Mocking minimal hass
    el.hass = { states: { 'camera.test_cam': online }, callWS: vi.fn() };
    await el.updateComplete;

    // Through the same backoff timer as a camera that comes back from unavailable.
    expect(startSpy).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(startSpy).toHaveBeenCalled();
    // @ts-expect-error Testing private state
    expect(el._streamUrl).toContain('/api/skylinewebcams_proxy/tok-123.m3u8');

    await el.updateComplete;
    expect(el.shadowRoot?.querySelector('.offline-overlay')).toBeNull();
    expect(el.shadowRoot?.querySelector('.video-container.offline')).toBeNull();
    expect(el.shadowRoot?.querySelector('.video-controls')).not.toBeNull();
  });

  it('never points the proxy at the entry id, which no longer opens it', async () => {
    el.setConfig({ entity: 'camera.test_cam' });
    const callWS = vi.fn(() => Promise.resolve({ url: '/api/hls/core-token/master_playlist.m3u8' }));
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: {
        'camera.test_cam': { state: 'idle', attributes: { friendly_name: 'Test Cam', entry_id: 'abc123' } },
      },
      callWS,
    };
    // @ts-expect-error Testing private method
    await el._startStream();

    expect(callWS).toHaveBeenCalledWith({ type: 'camera/stream', entity_id: 'camera.test_cam' });
    // @ts-expect-error Testing private state
    expect(el._streamUrl).toBe('/api/hls/core-token/master_playlist.m3u8');
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
          attributes: { friendly_name: 'Test Cam', entry_id: 'abc123', proxy_token: 'tok-123' },
        },
      },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;

    vi.advanceTimersByTime(30000);
    expect(startSpy).not.toHaveBeenCalled();
  });
});

describe('entity suggestion', () => {
  const suggestionFor = (hass: unknown, entityId: string) => {
    const entry = window.customCards?.find((card) => card.type === 'skyline-webcams-card');
    return entry?.getEntitySuggestion?.(hass as never, entityId) ?? null;
  };

  it('opts the card into the picker suggestions', () => {
    // Home Assistant asks only the custom cards that declare this hook and
    // offers its own providers' answers otherwise - which is why the picker
    // used to suggest a picture-entity for a SkylineWebcams camera and never
    // this card, however it was registered.
    const entry = window.customCards?.find((card) => card.type === 'skyline-webcams-card');
    expect(typeof entry?.getEntitySuggestion).toBe('function');
  });

  it('suggests the card for one of our cameras', () => {
    const hass = {
      states: {
        'camera.venice': {
          entity_id: 'camera.venice',
          state: 'streaming',
          attributes: { source: 'https://www.skylinewebcams.com/en/webcam/venezia.html' },
        },
      },
    };

    expect(suggestionFor(hass, 'camera.venice')).toEqual({
      config: {
        type: 'custom:skyline-webcams-card',
        entity: 'camera.venice',
        aspect_ratio: '16/9',
        show_video_controls: true,
      },
    });
  });

  it('prefixes the config type with custom:', () => {
    // A config naming the bare element name is not a card Home Assistant can
    // build - it renders as "Custom element doesn't exist". The prefix is
    // added for the entries HA builds itself, never for a config we hand over.
    const hass = {
      states: {
        'camera.venice': {
          entity_id: 'camera.venice',
          state: 'streaming',
          attributes: { source: 'https://www.skylinewebcams.com/en/webcam/venezia.html' },
        },
      },
    };
    const suggestion = suggestionFor(hass, 'camera.venice');
    expect(suggestion && 'config' in suggestion && suggestion.config.type).toBe('custom:skyline-webcams-card');
  });

  it('stays out of the way for a camera that is not ours', () => {
    // The card speaks HLS to SkylineWebcams and has nothing to offer a
    // doorbell. The suggestions panel is only useful while it is short.
    const hass = {
      states: {
        'camera.front_door': { entity_id: 'camera.front_door', state: 'idle', attributes: {} },
      },
    };
    expect(suggestionFor(hass, 'camera.front_door')).toBeNull();
  });

  it('says no to a non-camera and to an entity that is not there', () => {
    const hass = { states: { 'light.kitchen': { entity_id: 'light.kitchen', state: 'on', attributes: {} } } };
    expect(suggestionFor(hass, 'light.kitchen')).toBeNull();
    expect(suggestionFor(hass, 'camera.ghost')).toBeNull();
    expect(suggestionFor(undefined, 'camera.ghost')).toBeNull();
  });

  it('suggests what the stub config would have built', () => {
    // A suggestion the stub would not have produced is one that previews
    // differently from the card the picker otherwise creates.
    const hass = {
      states: {
        'camera.venice': {
          entity_id: 'camera.venice',
          state: 'streaming',
          attributes: { source: 'https://www.skylinewebcams.com/en/webcam/venezia.html' },
        },
      },
    };
    const suggestion = suggestionFor(hass, 'camera.venice');
    const config = suggestion && 'config' in suggestion ? suggestion.config : {};
    // @ts-expect-error Mocking minimal hass
    const stub = SkylineWebcamsCard.getStubConfig(hass, Object.keys(hass.states));
    const withoutType = { ...(config as Record<string, unknown>) };
    delete withoutType.type;
    expect(withoutType).toEqual(stub);
  });
});

describe('the text around the video', () => {
  let el: SkylineWebcamsCard;

  const FULL_CAM = {
    state: 'idle',
    attributes: {
      friendly_name: 'Venice - St Mark Square',
      description: 'Webcam overlooking St. Mark’s Square',
      place: 'Venice',
      region: 'Veneto',
      country: 'Italy',
      source: 'https://www.skylinewebcams.com/en/webcam/venezia.html',
    },
  };

  const show = async (config: Record<string, unknown>, attributes = FULL_CAM.attributes) => {
    el.setConfig({ entity: 'camera.venice', ...config } as never);
    // @ts-expect-error Mocking minimal hass
    el.hass = {
      states: { 'camera.venice': { ...FULL_CAM, attributes } },
      callWS: () => Promise.resolve({ url: '/api/mock' }),
    };
    await el.updateComplete;
  };

  const has = (selector: string) => el.shadowRoot?.querySelector(selector) !== null;

  beforeEach(() => {
    el = document.createElement('skyline-webcams-card') as SkylineWebcamsCard;
    document.body.appendChild(el);
  });

  afterEach(() => {
    document.body.removeChild(el);
  });

  it('shows the title, the location and the description by default', async () => {
    await show({});
    expect(has('.webcam-title')).toBe(true);
    expect(has('.webcam-location')).toBe(true);
    expect(has('.webcam-description')).toBe(true);
    // A card that still has something to say keeps its padding.
    expect(has('ha-card.bare')).toBe(false);
  });

  it('hides each text on its own', async () => {
    await show({ show_title: false });
    expect(has('.webcam-title')).toBe(false);
    expect(has('.webcam-location')).toBe(true);

    await show({ show_location: false });
    expect(has('.webcam-location')).toBe(false);
    expect(has('.webcam-title')).toBe(true);

    await show({ show_description: false });
    expect(has('.webcam-description')).toBe(false);
    expect(has('.webcam-title')).toBe(true);
  });

  it('hides the name in the header too, not just under the video', async () => {
    // `title` moves the name into the card header. Switching the name off has
    // to reach it there as well, or "hide the title" hides it in one place and
    // leaves it in the other.
    await show({ title: 'My Webcam' });
    expect(el.shadowRoot?.querySelector('.card-header')?.textContent?.trim()).toBe('My Webcam');

    await show({ title: 'My Webcam', show_title: false });
    expect(has('.card-header')).toBe(false);
  });

  it('drops the card padding once only the stream is left', async () => {
    // What the option is for: the stream on its own, shown the way
    // picture-entity shows a camera rather than as a picture in a padded box.
    await show({ show_title: false, show_location: false, show_description: false });
    expect(has('.webcam-info')).toBe(false);
    expect(has('ha-card.bare')).toBe(true);
    // The video is still there, and so is the card that carries the theme.
    expect(has('.video-container')).toBe(true);
    expect(has('ha-card')).toBe(true);
  });

  it('keeps the padding while the link is still shown', async () => {
    // The link lives in the same block as the texts, so it counts as content.
    await show({ show_title: false, show_location: false, show_description: false, show_link: true });
    expect(has('.webcam-source-link')).toBe(true);
    expect(has('ha-card.bare')).toBe(false);
  });

  it('keeps the padding while a configured title is still shown', async () => {
    await show({ title: 'My Webcam', show_location: false, show_description: false });
    expect(has('ha-card.bare')).toBe(false);
  });

  it('goes bare for a camera that has no text to show anyway', async () => {
    // Nothing switched off - the camera simply carries no location and no
    // description, and its name is off. Padding around nothing is still
    // padding around nothing.
    await show({ show_title: false }, { friendly_name: 'Bare Cam' });
    expect(has('ha-card.bare')).toBe(true);
  });

  it('leaves an existing card untouched', async () => {
    // Every option defaults to the old behaviour: a config written before they
    // existed has to render exactly as it did.
    await show({ show_link: true });
    expect(has('.webcam-title')).toBe(true);
    expect(has('.webcam-location')).toBe(true);
    expect(has('.webcam-description')).toBe(true);
    expect(has('.webcam-source-link')).toBe(true);
    expect(has('ha-card.bare')).toBe(false);
  });
});
