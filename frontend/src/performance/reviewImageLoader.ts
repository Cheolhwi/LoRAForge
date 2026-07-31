type ImageStatus = "idle" | "queued" | "loading" | "loaded" | "error";

interface ImageState {
  controller: AbortController | null;
  objectUrl: string | null;
  status: ImageStatus;
  token: number;
  wanted: boolean;
}

export interface ReviewImageLoaderOptions {
  concurrency?: number;
  rootMargin?: string;
  fallbackCount?: number;
}

export class ReviewImageLoader {
  private readonly concurrency: number;
  private readonly fallbackCount: number;
  private readonly root: HTMLElement;
  private readonly rootMargin: string;
  private readonly states = new Map<HTMLImageElement, ImageState>();
  private readonly queue: HTMLImageElement[] = [];
  private active = 0;
  private disposed = false;
  private observer: IntersectionObserver | null = null;

  constructor(root: HTMLElement, options: ReviewImageLoaderOptions = {}) {
    this.root = root;
    this.concurrency = Math.max(1, options.concurrency ?? 4);
    this.fallbackCount = Math.max(1, options.fallbackCount ?? 15);
    this.rootMargin = options.rootMargin ?? "280px 0px";
  }

  observe(images: HTMLImageElement[]): void {
    images.forEach((image) => {
      this.states.set(image, {
        controller: null,
        objectUrl: null,
        status: "idle",
        token: 0,
        wanted: false,
      });
    });

    if (typeof window.IntersectionObserver !== "function") {
      images.slice(0, this.fallbackCount).forEach((image) => this.request(image));
      return;
    }

    this.observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const image = entry.target as HTMLImageElement;
          const state = this.states.get(image);
          if (!state) return;
          if (entry.isIntersecting) {
            state.wanted = true;
            this.request(image);
          } else if (state.wanted || state.status === "loaded" || state.status === "loading") {
            this.release(image, state);
          }
        });
      },
      { root: this.root, rootMargin: this.rootMargin, threshold: 0.01 },
    );
    images.forEach((image) => this.observer?.observe(image));
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.observer?.disconnect();
    this.queue.length = 0;
    this.states.forEach((state, image) => {
      state.token += 1;
      state.controller?.abort();
      if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
      image.removeAttribute("src");
      image.classList.remove("is-loaded");
    });
    this.states.clear();
  }

  private request(image: HTMLImageElement): void {
    const state = this.states.get(image);
    if (!state || ["loaded", "loading", "queued", "error"].includes(state.status)) return;
    state.wanted = true;
    state.status = "queued";
    this.queue.push(image);
    this.pump();
  }

  private release(image: HTMLImageElement, state: ImageState): void {
    state.wanted = false;
    state.token += 1;
    state.controller?.abort();
    state.controller = null;
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = null;
    state.status = state.status === "error" ? "error" : "idle";
    image.removeAttribute("src");
    image.classList.remove("is-loaded");
  }

  private pump(): void {
    if (this.disposed) return;
    while (this.active < this.concurrency && this.queue.length) {
      const image = this.queue.shift();
      if (!image) continue;
      const state = this.states.get(image);
      if (!state?.wanted || state.status !== "queued" || !image.isConnected) continue;
      this.active += 1;
      state.status = "loading";
      state.token += 1;
      const token = state.token;
      const controller = new AbortController();
      state.controller = controller;
      void this.load(image, state, token, controller);
    }
  }

  private async load(
    image: HTMLImageElement,
    state: ImageState,
    token: number,
    controller: AbortController,
  ): Promise<void> {
    try {
      const url = image.dataset.thumbnailUrl;
      if (!url) throw new Error("review thumbnail URL is missing");
      const response = await fetch(url, { cache: "force-cache", signal: controller.signal });
      if (!response.ok) throw new Error(`thumbnail request failed: ${response.status}`);
      const blob = await response.blob();
      if (this.disposed || !state.wanted || state.token !== token) return;
      const objectUrl = URL.createObjectURL(blob);
      state.objectUrl = objectUrl;
      image.src = objectUrl;
      if (typeof image.decode === "function") await image.decode();
      if (this.disposed || !state.wanted || state.token !== token) {
        URL.revokeObjectURL(objectUrl);
        if (state.objectUrl === objectUrl) state.objectUrl = null;
        image.removeAttribute("src");
        return;
      }
      state.status = "loaded";
      image.classList.add("is-loaded");
      image.closest(".review-thumb")?.classList.remove("thumbnail-error");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError") && state.token === token) {
        state.status = "error";
        image.removeAttribute("src");
        image.closest(".review-thumb")?.classList.add("thumbnail-error");
      }
    } finally {
      if (state.controller === controller) state.controller = null;
      this.active = Math.max(0, this.active - 1);
      this.pump();
    }
  }
}
