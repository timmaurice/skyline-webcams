export interface FrontendLocaleData {
  language: string;
  number_format: 'comma_decimal' | 'decimal_comma' | 'space_comma' | 'system';
  time_format: '12' | '24' | 'system' | 'am_pm';
}

export interface HomeAssistant {
  states: { [entity_id: string]: HassEntity };
  localize: (key: string, ...args: unknown[]) => string;
  language: string;
  locale: FrontendLocaleData;
  callWS: <T>(message: { type: string; [key: string]: unknown }) => Promise<T>;
  themes?: {
    darkMode?: boolean;
    [key: string]: unknown;
  };
}

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: {
    friendly_name?: string;
    description?: string;
    country?: string;
    region?: string;
    place?: string;
    source?: string;
    [key: string]: unknown;
  };
  last_changed: string;
  last_updated: string;
}

export interface LovelaceCard extends HTMLElement {
  hass?: HomeAssistant;
  editMode?: boolean;
  setConfig(config: LovelaceCardConfig): void;
  getCardSize?(): number | Promise<number>;
}

export interface LovelaceCardConfig {
  type: string;
  [key: string]: unknown;
}

export interface LovelaceCardEditor extends HTMLElement {
  hass?: HomeAssistant;
  setConfig(config: LovelaceCardConfig): void;
}

export interface SkylineWebcamsCardConfig extends LovelaceCardConfig {
  entity: string;
  title?: string;
  aspect_ratio?: string;
  show_link?: boolean;
  show_video_controls?: boolean;
}

/**
 * What a custom card may hand back from `getEntitySuggestion`. `config.type`
 * carries the `custom:` prefix, because this is a finished card config rather
 * than a picker entry - Home Assistant adds that prefix itself only for the
 * entries it builds out of `customCards`.
 */
export interface CardSuggestion {
  label?: string;
  config: LovelaceCardConfig;
}

declare global {
  interface Window {
    customCards?: {
      type: string;
      name: string;
      description: string;
      documentationURL: string;
      preview?: boolean;
      /**
       * Opts the card into the picker's "Suggestions" panel for one entity.
       * Home Assistant asks every custom card that declares it and shows the
       * built-in providers' answers otherwise - which is why a card without
       * this is never suggested, whatever else it declares. Returning null
       * means "not for this entity".
       */
      getEntitySuggestion?: (hass: HomeAssistant, entityId: string) => CardSuggestion | CardSuggestion[] | null;
    }[];
  }
}
