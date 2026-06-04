import { LitElement, TemplateResult, html, unsafeCSS } from 'lit';
import { property, state, query } from 'lit/decorators.js';
import Hls from 'hls.js';
import { HomeAssistant, LovelaceCard, LovelaceCardEditor, SkylineWebcamsCardConfig } from './types.js';
import styles from './styles/card.styles.scss';
import './skyline-webcams-card-editor.js';

const ELEMENT_NAME = 'skyline-webcams-card';

export class SkylineWebcamsCard extends LitElement implements LovelaceCard {
  public static async getConfigElement(): Promise<LovelaceCardEditor> {
    return document.createElement('skyline-webcams-card-editor') as LovelaceCardEditor;
  }

  public static getStubConfig(): Record<string, unknown> {
    return {
      entity: '',
      aspect_ratio: '16/9',
    };
  }

  @property({ attribute: false }) public hass!: HomeAssistant;
  @state() private _config!: SkylineWebcamsCardConfig;
  @state() private _error?: string;
  @state() private _loading = false;
  @state() private _streamUrl?: string;

  @query('video') private _videoEl?: HTMLVideoElement;

  private _hls?: Hls;
  private _visibilityListener?: () => void;

  public setConfig(config: SkylineWebcamsCardConfig): void {
    if (!config || !config.entity) {
      throw new Error('Please define a camera entity.');
    }
    this._config = config;
  }

  public getCardSize(): number {
    return 4;
  }

  public connectedCallback(): void {
    super.connectedCallback();

    if (this.hass && this._config?.entity) {
      this._startStream();
    }

    // Set up page visibility listener to refresh stream when tab becomes active
    this._visibilityListener = () => {
      if (document.visibilityState === 'visible' && this._config?.entity) {
        console.debug('skyline-webcams-card: tab active, refreshing stream');
        this._startStream();
      } else if (document.visibilityState === 'hidden') {
        console.debug('skyline-webcams-card: tab hidden, stopping stream');
        this._destroyHls();
      }
    };
    document.addEventListener('visibilitychange', this._visibilityListener);
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this._visibilityListener) {
      document.removeEventListener('visibilitychange', this._visibilityListener);
    }
    this._destroyHls();
  }

  protected updated(changedProperties: Map<string | number | symbol, unknown>): void {
    super.updated(changedProperties);

    if (changedProperties.has('_config')) {
      const oldConfig = changedProperties.get('_config') as SkylineWebcamsCardConfig | undefined;
      if (oldConfig?.entity !== this._config?.entity) {
        this._startStream();
      }
    }
  }

  private _streamSessionId = 0;

  private _destroyHls(): void {
    if (this._hls) {
      console.debug('skyline-webcams-card: destroying hls instance');
      this._hls.stopLoad();
      this._hls.detachMedia();
      this._hls.destroy();
      this._hls = undefined;
    }
    if (this._videoEl) {
      this._videoEl.pause();
      this._videoEl.removeAttribute('src');
      this._videoEl.load();
    }
    this._streamUrl = undefined;
  }

  private async _startStream(): Promise<void> {
    if (!this.hass || !this._config?.entity) return;

    this._streamSessionId++;
    const sessionId = this._streamSessionId;

    this._destroyHls();
    this._loading = true;
    this._error = undefined;
    this.requestUpdate();

    try {
      console.debug(`skyline-webcams-card: resolving direct stream for ${this._config.entity}`);

      const stateObj = this.hass.states[this._config.entity];
      if (!stateObj) {
        throw new Error(`Entity not found: ${this._config.entity}`);
      }

      const entryId = stateObj.attributes.entry_id;
      if (!entryId) {
        console.warn('skyline-webcams-card: entry_id not found, falling back to camera/stream');
        const result = await this.hass.callWS<{ url: string }>({
          type: 'camera/stream',
          entity_id: this._config.entity,
        });
        if (result && result.url) {
          this._streamUrl = result.url;
        } else {
          throw new Error('No stream URL returned from Home Assistant.');
        }
      } else {
        // Point directly to our internal HLS proxy endpoint
        this._streamUrl = `/api/skylinewebcams_proxy/${entryId}.m3u8?t=${Date.now()}`;
      }

      if (this._streamSessionId !== sessionId) return;

      if (this._streamUrl) {
        this._loading = false;
        this.requestUpdate();

        // Wait for video element to render, then attach Hls
        await this.updateComplete;

        if (this._streamSessionId !== sessionId) return;
        this._initHls();
      } else {
        throw new Error('No stream URL returned.');
      }
    } catch (err) {
      if (this._streamSessionId !== sessionId) return;
      console.error('skyline-webcams-card: failed to start stream', err);
      this._error = (err as Error)?.message || 'Failed to start stream.';
      this._loading = false;
      this.requestUpdate();
    }
  }

  private _initHls(): void {
    const video = this._videoEl;
    const url = this._streamUrl;

    if (!video || !url) {
      console.warn('skyline-webcams-card: video element or stream URL missing, cannot initialize Hls');
      return;
    }

    if (Hls.isSupported()) {
      console.debug('skyline-webcams-card: initializing Hls.js');
      const hls = new Hls({
        maxBufferLength: 30,
        maxMaxBufferLength: 60,
        enableWorker: true,
      });

      this._hls = hls;
      hls.loadSource(url);
      hls.attachMedia(video);

      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        console.debug('skyline-webcams-card: manifest parsed, playing video');
        video.play().catch((err) => {
          if (err.name === 'AbortError') return;
          video.muted = true;
          video.play().catch((e) => {
            if (e.name === 'AbortError') return;
            console.error('skyline-webcams-card: failed to play even after muting', e);
          });
        });
      });

      hls.on(Hls.Events.ERROR, (event, data) => {
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR && data.details === 'bufferStalledError') {
          // Silently ignore buffer stalled errors as they are common and self-recovering
          return;
        }
        console.warn(`skyline-webcams-card: Hls error: ${data.type} - ${data.details}`, data);
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              console.debug('skyline-webcams-card: fatal network error, attempting to recover');
              // Try to start a fresh stream from HA since the stream worker might have crashed/expired
              this._startStream();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              console.debug('skyline-webcams-card: fatal media error, attempting recovery');
              hls.recoverMediaError();
              break;
            default:
              console.error('skyline-webcams-card: unrecoverable fatal Hls error, restarting stream');
              this._startStream();
              break;
          }
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Native HLS support (Safari / iOS)
      console.debug('skyline-webcams-card: using native HLS support');
      video.src = url;
      video.addEventListener('loadedmetadata', () => {
        video.play().catch((err) => {
          console.warn('skyline-webcams-card: native autoplay prevented, video muted', err);
          video.muted = true;
          video.play().catch((e) => console.error('skyline-webcams-card: native play failed', e));
        });
      });

      video.onerror = () => {
        console.warn('skyline-webcams-card: native video error, reloading stream');
        this._startStream();
      };
    } else {
      this._error = 'HLS streaming is not supported by your browser.';
      this.requestUpdate();
    }
  }

  private _handleRetry(): void {
    this._startStream();
  }

  private _handleMoreInfo(): void {
    if (this._config?.entity) {
      const event = new CustomEvent('hass-more-info', {
        bubbles: true,
        cancelable: false,
        composed: true,
        detail: { entityId: this._config.entity },
      });
      this.dispatchEvent(event);
    }
  }

  protected render(): TemplateResult | void {
    if (!this.hass || !this._config) return html``;

    const entityId = this._config.entity;
    const stateObj = this.hass.states[entityId];

    if (!stateObj) {
      return html`
        <ha-card .header=${this._config.title || 'Skyline Webcam'}>
          <div class="card-content error-container">Entity not found: ${entityId}</div>
        </ha-card>
      `;
    }

    const title = this._config.title || stateObj.attributes.friendly_name || 'Skyline Webcam';
    const description = stateObj.attributes.description || '';
    const country = stateObj.attributes.country || '';
    const region = stateObj.attributes.region || '';
    const place = stateObj.attributes.place || '';

    // Construct location text
    const locationParts = [place, region, country].filter((p) => !!p);
    const locationText = locationParts.join(', ');

    return html`
      <ha-card .header=${this._config.title ? title : ''} @click=${this._handleMoreInfo} style="cursor: pointer;">
        <div class="card-content">
          <div class="video-container" style="aspect-ratio: ${this._config.aspect_ratio || '16/9'};">
            ${this._error
              ? html`
                  <div class="overlay error-overlay">
                    <p class="error-msg">${this._error}</p>
                    <button class="retry-btn" @click=${this._handleRetry}>Retry</button>
                  </div>
                `
              : ''}
            ${this._loading
              ? html`
                  <div class="overlay loading-overlay">
                    <div class="spinner"></div>
                  </div>
                `
              : ''}

            <video
              playsinline
              autoplay
              preload="auto"
              ?muted=${true}
              poster=${stateObj.attributes.poster || stateObj.attributes.entity_picture || ''}
            ></video>
          </div>

          <div class="webcam-info">
            ${!this._config.title && title ? html`<h2 class="webcam-title">${title}</h2>` : ''}
            ${locationText
              ? html`<p class="webcam-location"><ha-icon icon="mdi:map-marker"></ha-icon> ${locationText}</p>`
              : ''}
            ${description && description !== title ? html`<p class="webcam-description">${description}</p>` : ''}
            ${this._config.show_link && stateObj.attributes.source
              ? html`
                  <a
                    href="${stateObj.attributes.source}"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="webcam-source-link"
                    @click=${(e: Event) => e.stopPropagation()}
                  >
                    <ha-icon icon="mdi:open-in-new"></ha-icon> View on SkylineWebcams
                  </a>
                `
              : ''}
          </div>
        </div>
      </ha-card>
    `;
  }

  static get styles() {
    return [unsafeCSS(styles)];
  }
}

if (!customElements.get(ELEMENT_NAME)) {
  customElements.define(ELEMENT_NAME, SkylineWebcamsCard);
}

// Register custom card in Home Assistant picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: ELEMENT_NAME,
  name: 'Skyline Webcams Card',
  description:
    'A dedicated Lovelace card for Skyline Webcams supporting robust HLS streaming and automatic reconnection.',
  preview: true,
  documentationURL: 'https://github.com/timmaurice/skyline-webcams',
});
