import { describe, expect, it, vi } from "vitest";

import { PipelineEventBatcher, type PipelineEvent } from "./pipelineEventBatcher";

describe("PipelineEventBatcher", () => {
  it("coalesces ordinary running events but preserves detailed and terminal events", () => {
    let scheduled: FrameRequestCallback = () => {
      throw new Error("frame was not scheduled");
    };
    const render = vi.fn();
    const batcher = new PipelineEventBatcher<PipelineEvent>(render, {
      requestFrame: (callback) => {
        scheduled = callback;
        return 1;
      },
      cancelFrame: vi.fn(),
    });

    batcher.enqueue({ stage: "scan", status: "running", progress: 0.1 }, "job-1");
    batcher.enqueue({ stage: "scan", status: "running", progress: 0.2 }, "job-1");
    batcher.enqueue(
      { stage: "locate", status: "running", data: { locate_flow: { event: "candidate" } } },
      "job-1",
    );
    batcher.enqueue({ stage: "scan", status: "completed", progress: 1 }, "job-1");

    expect(render).not.toHaveBeenCalled();
    scheduled(0);

    expect(render).toHaveBeenCalledTimes(3);
    expect(render.mock.calls[0][0].progress).toBe(0.2);
    expect(render.mock.calls[1][0].data.locate_flow.event).toBe("candidate");
    expect(render.mock.calls[2][0].status).toBe("completed");
  });

  it("cancels pending work when reset", () => {
    const cancelFrame = vi.fn();
    const render = vi.fn();
    const batcher = new PipelineEventBatcher<PipelineEvent>(render, {
      requestFrame: () => 42,
      cancelFrame,
    });

    batcher.enqueue({ stage: "scan", status: "running" }, "job-1");
    batcher.reset();
    batcher.flush();

    expect(cancelFrame).toHaveBeenCalledWith(42);
    expect(render).not.toHaveBeenCalled();
  });
});
