import type { HassEntity, HomeAssistant, SkylineWebcamsCardConfig } from '../src/types.js';

export const CARD_TYPE = 'custom:skyline-webcams-card';

/** An entity as a test writes it: only what the test is about, the rest is filled in. */
export interface MockEntity {
  entity_id?: string;
  state: string;
  attributes?: HassEntity['attributes'];
}

/** A hass as a test writes it: only what the card reads is needed. */
export interface MockHassInit {
  states?: Record<string, MockEntity>;
  language?: string;
  callWS?: (message: { type: string; [key: string]: unknown }) => Promise<unknown>;
}

export const mockEntity = (entityId: string, entity: MockEntity): HassEntity => ({
  entity_id: entityId,
  attributes: {},
  last_changed: '2026-01-01T00:00:00Z',
  last_updated: '2026-01-01T00:00:00Z',
  ...entity,
});

/**
 * Builds a complete `HomeAssistant` from the few fields a test sets. The card
 * only ever calls `callWS` with a result shape of its own choosing, so the
 * generic `callWS` is satisfied here, in one place, instead of in every test.
 */
export const mockHass = (init: MockHassInit = {}): HomeAssistant => {
  const states: HomeAssistant['states'] = {};
  for (const [entityId, entity] of Object.entries(init.states ?? {})) {
    states[entityId] = mockEntity(entityId, entity);
  }
  return {
    states,
    localize: (key: string) => key,
    language: init.language ?? 'en',
    locale: { language: init.language ?? 'en', number_format: 'system', time_format: '24' },
    callWS: (init.callWS ?? (() => Promise.reject(new Error('callWS not mocked')))) as HomeAssistant['callWS'],
  };
};

/** A card config with the `type` Home Assistant always adds. */
export const cardConfig = (config: Partial<SkylineWebcamsCardConfig> = {}): SkylineWebcamsCardConfig => ({
  type: CARD_TYPE,
  entity: 'camera.test_cam',
  ...config,
});
