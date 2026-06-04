import { LitElement, html, TemplateResult, css } from 'lit';
import { property, state } from 'lit/decorators.js';
import { HomeAssistant, LovelaceCardEditor, SkylineWebcamsCardConfig } from './types.js';
import { localize } from './localize.js';

const ELEMENT_NAME = 'skyline-webcams-card-editor';

const SCHEMA = [
  {
    name: 'title',
    selector: { text: {} },
  },
  {
    name: 'entity',
    required: true,
    selector: { entity: { domain: 'camera' } },
  },
  {
    name: 'aspect_ratio',
    selector: { text: {} },
  },
  {
    name: 'show_link',
    selector: { boolean: {} },
  },
  {
    name: 'show_video_controls',
    default: true,
    selector: { boolean: {} },
  },
];

export class SkylineWebcamsCardEditor extends LitElement implements LovelaceCardEditor {
  @property({ attribute: false }) public hass?: HomeAssistant;
  @state() private _config?: SkylineWebcamsCardConfig;

  public setConfig(config: SkylineWebcamsCardConfig): void {
    this._config = config;
  }

  protected shouldUpdate(changedProps: import('lit').PropertyValues): boolean {
    if (changedProps.has('_config')) {
      return true;
    }

    const oldHass = changedProps.get('hass') as HomeAssistant | undefined;
    if (oldHass && this.hass && oldHass.language !== this.hass.language) {
      return true;
    }

    return !oldHass;
  }

  private _valueChanged(ev: CustomEvent): void {
    if (!this._config || !this.hass) {
      return;
    }
    const changedValue = ev.detail.value;
    this._config = { ...this._config, ...changedValue };

    const event = new CustomEvent('config-changed', {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }

  private _computeLabel(schema: { name: string }): string {
    switch (schema.name) {
      case 'entity':
        return localize(this.hass, 'editor.entity');
      case 'title':
        return localize(this.hass, 'editor.title');
      case 'aspect_ratio':
        return localize(this.hass, 'editor.aspect_ratio');
      case 'show_link':
        return localize(this.hass, 'editor.show_link');
      case 'show_video_controls':
        return localize(this.hass, 'editor.show_video_controls');
      default:
        return schema.name;
    }
  }

  protected render(): TemplateResult | void {
    if (!this.hass || !this._config) {
      return html``;
    }

    const formData = {
      ...this._config,
    };

    return html`
      <ha-form
        .hass=${this.hass}
        .data=${formData}
        .schema=${SCHEMA}
        .computeLabel=${this._computeLabel}
        @value-changed=${this._valueChanged}
      ></ha-form>
    `;
  }

  static get styles() {
    return css``;
  }
}

if (!customElements.get(ELEMENT_NAME)) {
  customElements.define(ELEMENT_NAME, SkylineWebcamsCardEditor);
}
