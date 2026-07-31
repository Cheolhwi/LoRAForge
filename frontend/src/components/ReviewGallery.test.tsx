import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../performance/reviewImageLoader", () => ({
  ReviewImageLoader: class {
    observe = vi.fn();
    dispose = vi.fn();
  },
}));

import { renderReviewGallery, unmountReviewGallery } from "./ReviewGallery";

describe("ReviewGallery", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("renders the 720p thumbnail endpoint without falling back to the original image", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const onOpen = vi.fn();
    const onRemove = vi.fn();

    renderReviewGallery(container, {
      apiBase: "http://127.0.0.1:8000/api",
      items: [{
        candidate_role: "medoid",
        cluster_id: 4,
        jobId: "job-1",
        locate_attempt: 1,
        manifestIndex: 8,
        source: "/images/example.png",
      }],
      locked: false,
      onOpen,
      onRemove,
      startIndex: 0,
      thumbnailAvailable: true,
      total: 1,
    });

    const image = container.querySelector("img");
    expect(image?.dataset.thumbnailUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/review/8/thumbnail",
    );
    expect(image?.hasAttribute("src")).toBe(false);
    expect(container.querySelectorAll(".review-card")).toHaveLength(1);

    unmountReviewGallery(container);
  });
});
