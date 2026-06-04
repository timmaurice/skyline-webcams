/**
 * Dispatches a standard Home Assistant event.
 * @param node The HTMLElement to fire the event from.
 * @param type The event type (e.g., 'hass-more-info').
 * @param detail Optional detail object to include in the event.
 */
export const fireEvent = (node: HTMLElement, type: string, detail?: any): void => {
  const event = new CustomEvent(type, {
    bubbles: true,
    cancelable: false,
    composed: true,
    detail: detail || {},
  });
  node.dispatchEvent(event);
};

/**
 * Checks if Picture-in-Picture is supported by the current browser.
 */
export const isPiPSupported = (): boolean => {
  return typeof document !== 'undefined' && 'pictureInPictureEnabled' in document && document.pictureInPictureEnabled;
};

/**
 * Toggles Picture-in-Picture mode for a video element.
 * @param video The HTMLVideoElement to toggle PiP for.
 */
export const togglePiP = async (video: HTMLVideoElement | undefined | null): Promise<void> => {
  if (!video) return;

  try {
    if (document.pictureInPictureElement === video) {
      await document.exitPictureInPicture();
    } else {
      await video.requestPictureInPicture();
    }
  } catch (err) {
    console.error('skyline-webcams-card: failed to toggle PiP', err);
  }
};

/**
 * Toggles Fullscreen mode for a container element.
 * @param container The HTMLElement to toggle fullscreen for.
 */
export const toggleFullscreen = async (container: Element | undefined | null): Promise<void> => {
  if (!container) return;

  try {
    if (document.fullscreenElement === container) {
      await document.exitFullscreen();
    } else {
      await container.requestFullscreen();
    }
  } catch (err) {
    console.error('skyline-webcams-card: failed to toggle Fullscreen', err);
  }
};
