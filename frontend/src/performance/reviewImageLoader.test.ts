import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewImageLoader } from "./reviewImageLoader";

describe("ReviewImageLoader", () => {
  const originalIntersectionObserver = globalThis.IntersectionObserver;

  beforeEach(() => {
    document.body.innerHTML = "";
    Object.defineProperty(globalThis, "IntersectionObserver", {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => `blob:review-${Math.random()}`),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(HTMLImageElement.prototype, "decode", {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(globalThis, "IntersectionObserver", {
      configurable: true,
      value: originalIntersectionObserver,
    });
  });

  it("limits simultaneous thumbnail requests and disposes decoded URLs", async () => {
    const pending: Array<(response: Response) => void> = [];
    const fetchMock = vi.fn(
      () => new Promise<Response>((resolve) => pending.push(resolve)),
    );
    vi.stubGlobal("fetch", fetchMock);

    const gallery = document.createElement("div");
    const images = Array.from({ length: 10 }, (_, index) => {
      const image = document.createElement("img");
      image.dataset.thumbnailUrl = `/thumbnail/${index}`;
      gallery.appendChild(image);
      return image;
    });
    document.body.appendChild(gallery);

    const loader = new ReviewImageLoader(gallery, { concurrency: 4, fallbackCount: 10 });
    loader.observe(images);
    expect(fetchMock).toHaveBeenCalledTimes(4);

    pending.shift()?.(new Response(new Blob(["jpeg"]), { status: 200 }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));

    loader.dispose();
    expect(images.every((image) => !image.hasAttribute("src"))).toBe(true);
  });
});
