import { LitElement, html, TemplateResult, css } from 'lit';
import { property, state } from 'lit/decorators.js';
import { HomeAssistant, LovelaceCardEditor, SkylineWebcamsCardConfig } from './types.js';

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
];

export class SkylineWebcamsCardEditor extends LitElement implements LovelaceCardEditor {
  @property({ attribute: false }) public hass?: HomeAssistant;
  @state() private _config?: SkylineWebcamsCardConfig;

  public setConfig(config: SkylineWebcamsCardConfig): void {
    this._config = config;
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
        return 'Camera Entity';
      case 'title':
        return 'Title (Optional)';
      case 'aspect_ratio':
        return 'Aspect Ratio (Default: 16/9)';
      case 'show_link':
        return 'Show Website Link';
      default:
        return schema.name;
    }
  }

  protected render(): TemplateResult | void {
    if (!this.hass || !this._config) {
      return html``;
    }

    return html`
      <ha-form
        .hass=${this.hass}
        .data=${this._config}
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
