import { useEffect } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";

import { ReviewImageLoader } from "../performance/reviewImageLoader";

export interface ReviewItem {
  candidate_role: string;
  cluster_id: number | string;
  jobId: string;
  locate_attempt: number | string;
  manifestIndex: number;
  source: string;
}

interface ReviewGalleryProps {
  apiBase: string;
  galleryRoot: HTMLElement;
  items: ReviewItem[];
  locked: boolean;
  onOpen: (index: number, trigger: HTMLButtonElement) => void;
  onRemove: (index: number, trigger: HTMLButtonElement) => void;
  startIndex: number;
  thumbnailAvailable: boolean;
  total: number;
}

function filename(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

function ReviewGallery({
  apiBase,
  galleryRoot,
  items,
  locked,
  onOpen,
  onRemove,
  startIndex,
  thumbnailAvailable,
  total,
}: ReviewGalleryProps) {
  const loaderKey = items.map((item) => `${item.jobId}:${item.manifestIndex}`).join("|");

  useEffect(() => {
    const loader = new ReviewImageLoader(galleryRoot, { concurrency: 4, rootMargin: "280px 0px" });
    const images = [...galleryRoot.querySelectorAll<HTMLImageElement>("img[data-thumbnail-url]")];
    loader.observe(images);
    return () => loader.dispose();
  }, [galleryRoot, loaderKey]);

  if (!items.length) return <div className="review-empty">最终数据集为空</div>;
  const digits = Math.max(3, String(total).length);

  return items.map((item, pageOffset) => {
    const index = startIndex + pageOffset;
    const sourceName = filename(item.source);
    const reviewUrl = `${apiBase}/jobs/${encodeURIComponent(item.jobId)}/review/${item.manifestIndex}`;
    const thumbnailUrl = thumbnailAvailable ? `${reviewUrl}/thumbnail` : reviewUrl;
    const retry = item.candidate_role === "backup_retry";
    return (
      <article className="review-card" key={`${item.jobId}:${item.manifestIndex}`}>
        <button
          type="button"
          className="review-card-open"
          aria-label={`查看图片 ${index + 1}：${sourceName}`}
          onClick={(event) => onOpen(index, event.currentTarget)}
        >
          <div className="review-thumb">
            <img
              alt={sourceName}
              data-thumbnail-url={thumbnailUrl}
              decoding="async"
              fetchPriority={pageOffset < 5 ? "high" : "low"}
              height={240}
              loading="eager"
              width={320}
            />
            <span className="review-card-index">
              {String(index + 1).padStart(digits, "0")} / {String(total).padStart(digits, "0")}
            </span>
            <span className={`review-card-role ${retry ? "retry" : ""}`}>
              {retry ? "RETRY PASS" : "MEDOID"}
            </span>
          </div>
          <div className="review-card-caption">
            <strong title={item.source}>{sourceName}</strong>
            <span>CLUSTER #{item.cluster_id} · ATTEMPT {item.locate_attempt}</span>
          </div>
        </button>
        <button
          type="button"
          className="review-card-pass"
          aria-label={`将 ${sourceName} 移出候选集`}
          disabled={locked}
          title="点击移出候选集"
          onClick={(event) => onRemove(index, event.currentTarget)}
        >
          ✓
        </button>
      </article>
    );
  });
}

const roots = new WeakMap<HTMLElement, Root>();

export function renderReviewGallery(
  container: HTMLElement,
  props: Omit<ReviewGalleryProps, "galleryRoot">,
): void {
  let root = roots.get(container);
  if (!root) {
    root = createRoot(container);
    roots.set(container, root);
  }
  flushSync(() => root?.render(<ReviewGallery {...props} galleryRoot={container} />));
}

export function unmountReviewGallery(container: HTMLElement): void {
  const root = roots.get(container);
  if (!root) return;
  flushSync(() => root?.unmount());
  roots.delete(container);
}
