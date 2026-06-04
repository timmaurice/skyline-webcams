import { vi } from 'vitest';
const ResizeObserverMock = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));
vi.stubGlobal('ResizeObserver', ResizeObserverMock);

class IntersectionObserverMock {
  constructor() {}
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
vi.stubGlobal('IntersectionObserver', IntersectionObserverMock);

if (typeof HTMLVideoElement !== 'undefined') {
  HTMLVideoElement.prototype.requestPictureInPicture = vi.fn().mockResolvedValue({});
}
if (typeof Element !== 'undefined') {
  Element.prototype.requestFullscreen = vi.fn().mockResolvedValue({});
}

if (typeof HTMLMediaElement !== 'undefined') {
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  HTMLMediaElement.prototype.pause = vi.fn();
  HTMLMediaElement.prototype.load = vi.fn();
}
