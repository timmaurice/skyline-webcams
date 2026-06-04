import { LitElement, TemplateResult, html, unsafeCSS } from 'lit';
import { property, state, query } from 'lit/decorators.js';
import Hls from 'hls.js';
import { HomeAssistant, LovelaceCard, LovelaceCardEditor, SkylineWebcamsCardConfig } from './types.js';
import { localize } from './localize.js';
import { isPiPSupported, togglePiP, toggleFullscreen, fireEvent } from './utils.js';
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
      show_video_controls: true,
    };
  }

  @property({ attribute: false }) public hass!: HomeAssistant;
  @state() private _config!: SkylineWebcamsCardConfig;
  @state() private _error?: string;
  @state() private _loading = false;
  @state() private _streamUrl?: string;
  @state() private _isIntersecting = false;

  @query('video') private _videoEl?: HTMLVideoElement;

  private _hls?: Hls;
  private _visibilityListener?: () => void;
  private _fullscreenListener?: () => void;
  private _intersectionObserver?: IntersectionObserver;

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

    // Set up IntersectionObserver to pause/resume playback when out of viewport
    if (typeof IntersectionObserver !== 'undefined') {
      this._intersectionObserver = new IntersectionObserver(
        (entries) => {
          const entry = entries[0];
          const newIntersecting = entry.isIntersecting;
          if (this._isIntersecting !== newIntersecting) {
            this._isIntersecting = newIntersecting;
            this._updatePlaybackState();
          }
        },
        { threshold: 0.1 },
      );
      this._intersectionObserver.observe(this);
    } else {
      this._isIntersecting = true;
      this._updatePlaybackState();
    }

    // Set up page visibility listener to refresh stream when tab becomes active
    this._visibilityListener = () => {
      this._updatePlaybackState();
    };
    document.addEventListener('visibilitychange', this._visibilityListener);

    // Set up fullscreen listener to trigger updates and keep UI elements in sync
    this._fullscreenListener = () => {
      this.requestUpdate();
    };
    document.addEventListener('fullscreenchange', this._fullscreenListener);
  }

  public disconnectedCallback(): void {
    super.disconnectedCallback();
    if (this._visibilityListener) {
      document.removeEventListener('visibilitychange', this._visibilityListener);
      this._visibilityListener = undefined;
    }
    if (this._fullscreenListener) {
      document.removeEventListener('fullscreenchange', this._fullscreenListener);
      this._fullscreenListener = undefined;
    }
    if (this._intersectionObserver) {
      this._intersectionObserver.disconnect();
      this._intersectionObserver = undefined;
    }
    this._destroyHls();
  }
  protected shouldUpdate(changedProps: import('lit').PropertyValues): boolean {
    if (
      changedProps.has('_config') ||
      changedProps.has('_error') ||
      changedProps.has('_loading') ||
      changedProps.has('_streamUrl') ||
      changedProps.has('_isIntersecting')
    ) {
      return true;
    }

    const oldHass = changedProps.get('hass') as HomeAssistant | undefined;
    if (oldHass && this.hass && this._config?.entity) {
      if (oldHass.states[this._config.entity] !== this.hass.states[this._config.entity]) {
        return true;
      }
      if (oldHass.language !== this.hass.language) {
        return true;
      }
      return false;
    }

    return true;
  }

  protected updated(changedProperties: Map<string | number | symbol, unknown>): void {
    super.updated(changedProperties);

    if (changedProperties.has('_config')) {
      const oldConfig = changedProperties.get('_config') as SkylineWebcamsCardConfig | undefined;
      if (oldConfig?.entity !== this._config?.entity) {
        this._updatePlaybackState();
      }
    }
  }

  private _updatePlaybackState(): void {
    const shouldPlay = document.visibilityState === 'visible' && this._isIntersecting;
    if (shouldPlay) {
      if (!this._hls && !this._loading && !this._error && this.hass && this._config?.entity) {
        console.debug('skyline-webcams-card: active and in viewport, starting stream');
        this._startStream();
      }
    } else {
      if (this._hls || this._loading) {
        console.debug('skyline-webcams-card: hidden or out of viewport, stopping stream');
        this._destroyHls();
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
        const playPromise = video.play();
        if (playPromise !== undefined) {
          playPromise.catch((err) => {
            if (err.name === 'AbortError') return;
            video.muted = true;
            const retryPromise = video.play();
            if (retryPromise !== undefined) {
              retryPromise.catch((e) => {
                if (e.name === 'AbortError') return;
                console.error('skyline-webcams-card: failed to play even after muting', e);
              });
            }
          });
        }
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
        const playPromise = video.play();
        if (playPromise !== undefined) {
          playPromise.catch((err) => {
            console.warn('skyline-webcams-card: native autoplay prevented, video muted', err);
            video.muted = true;
            const retryPromise = video.play();
            if (retryPromise !== undefined) {
              retryPromise.catch((e) => console.error('skyline-webcams-card: native play failed', e));
            }
          });
        }
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
    this._error = undefined;
    this._startStream();
  }

  private _handleMoreInfo(): void {
    if (this._config?.entity) {
      fireEvent(this, 'hass-more-info', { entityId: this._config.entity });
    }
  }

  private _togglePlay(e: Event): void {
    e.stopPropagation();
    const video = this._videoEl;
    if (!video) return;

    if (video.paused) {
      if (this._hls) {
        this._hls.startLoad();
      }
      const playPromise = video.play();
      if (playPromise !== undefined) {
        playPromise.catch((err) => {
          if (err.name === 'AbortError') return;
          console.error('skyline-webcams-card: failed to play video', err);
        });
      }
    } else {
      video.pause();
      if (this._hls) {
        this._hls.stopLoad();
      }
    }
  }

  private async _togglePiP(e: Event): Promise<void> {
    e.stopPropagation();
    await togglePiP(this._videoEl);
  }

  private async _toggleFullscreen(e: Event): Promise<void> {
    e.stopPropagation();
    const container = this.shadowRoot?.querySelector('.video-container');
    await toggleFullscreen(container);
  }

  protected render(): TemplateResult | void {
    if (!this.hass || !this._config) return html``;

    const entityId = this._config.entity;
    const stateObj = this.hass.states[entityId];

    if (!stateObj) {
      const errorTitle = this._config.title || localize(this.hass, 'card.default_title');
      return html`
        <ha-card>
          ${errorTitle
            ? html`
                <h1 class="card-header" @click=${this._handleMoreInfo} title="Open entity">
                  <div class="name" dir="ltr">${errorTitle}</div>
                </h1>
              `
            : ''}
          <div class="card-content error-container">
            ${localize(this.hass, 'card.entity_not_found', { entity: entityId })}
          </div>
        </ha-card>
      `;
    }

    const title = this._config.title || stateObj.attributes.friendly_name || localize(this.hass, 'card.default_title');
    const description = stateObj.attributes.description || '';
    const country = stateObj.attributes.country || '';
    const region = stateObj.attributes.region || '';
    const place = stateObj.attributes.place || '';

    // Construct location text
    const locationParts = [place, region, country].filter((p) => !!p);
    const locationText = locationParts.join(', ');

    return html`
      <ha-card>
        ${this._config.title
          ? html`
              <h1 class="card-header" @click=${this._handleMoreInfo} title="Open entity">
                <div class="name" dir="ltr">${title}</div>
              </h1>
            `
          : ''}
        <div class="card-content">
          <div class="video-container" style="aspect-ratio: ${this._config.aspect_ratio || '16/9'};">
            ${this._error
              ? html`
                  <div class="overlay error-overlay">
                    <p class="error-msg">${this._error}</p>
                    <button class="retry-btn" @click=${this._handleRetry}>${localize(this.hass, 'card.retry')}</button>
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
              @play=${() => this.requestUpdate()}
              @pause=${() => this.requestUpdate()}
            ></video>

            ${this._config.show_video_controls !== false
              ? html`
                  <div class="video-controls" @click=${(e: Event) => e.stopPropagation()}>
                    <button
                      class="control-btn"
                      @click=${this._togglePlay}
                      aria-label="${this._videoEl?.paused
                        ? localize(this.hass, 'card.play')
                        : localize(this.hass, 'card.pause')}"
                      title="${this._videoEl?.paused
                        ? localize(this.hass, 'card.play')
                        : localize(this.hass, 'card.pause')}"
                    >
                      <ha-icon icon="${this._videoEl?.paused ? 'mdi:play' : 'mdi:pause'}"></ha-icon>
                    </button>
                    <div class="spacer"></div>
                    ${isPiPSupported()
                      ? html`
                          <button
                            class="control-btn"
                            @click=${this._togglePiP}
                            aria-label="${localize(this.hass, 'card.picture_in_picture')}"
                            title="${localize(this.hass, 'card.picture_in_picture')}"
                          >
                            <ha-icon icon="mdi:picture-in-picture-bottom-right"></ha-icon>
                          </button>
                        `
                      : ''}
                    <button
                      class="control-btn"
                      @click=${this._toggleFullscreen}
                      aria-label="${document.fullscreenElement
                        ? localize(this.hass, 'card.exit_fullscreen')
                        : localize(this.hass, 'card.fullscreen')}"
                      title="${document.fullscreenElement
                        ? localize(this.hass, 'card.exit_fullscreen')
                        : localize(this.hass, 'card.fullscreen')}"
                    >
                      <ha-icon
                        icon="${document.fullscreenElement ? 'mdi:fullscreen-exit' : 'mdi:fullscreen'}"
                      ></ha-icon>
                    </button>
                  </div>
                `
              : ''}
          </div>

          <div class="webcam-info">
            ${!this._config.title && title
              ? html`<h2 class="webcam-title" @click=${this._handleMoreInfo} title="Open entity">${title}</h2>`
              : ''}
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
                    <ha-icon icon="mdi:open-in-new"></ha-icon> ${localize(this.hass, 'card.view_on_skylinewebcams')}
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
