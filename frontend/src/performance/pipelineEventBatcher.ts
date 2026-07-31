export interface PipelineEvent {
  data?: {
    cluster_audit?: unknown;
    locate_flow?: unknown;
    curation_flow?: unknown;
    [key: string]: unknown;
  };
  stage: string;
  status: string;
  [key: string]: unknown;
}

interface QueuedEvent<T extends PipelineEvent> {
  event: T;
  jobId: string;
}

export interface PipelineEventBatcherOptions {
  cancelFrame?: (frame: number) => void;
  requestFrame?: (callback: FrameRequestCallback) => number;
}

export class PipelineEventBatcher<T extends PipelineEvent> {
  private readonly cancelFrame: (frame: number) => void;
  private readonly render: (event: T, jobId: string) => void;
  private readonly requestFrame: (callback: FrameRequestCallback) => number;
  private frame = 0;
  private queue: QueuedEvent<T>[] = [];

  constructor(
    render: (event: T, jobId: string) => void,
    options: PipelineEventBatcherOptions = {},
  ) {
    this.render = render;
    this.requestFrame = options.requestFrame ?? window.requestAnimationFrame.bind(window);
    this.cancelFrame = options.cancelFrame ?? window.cancelAnimationFrame.bind(window);
  }

  enqueue(event: T, jobId: string): void {
    this.queue.push({ event, jobId });
    if (!this.frame) this.frame = this.requestFrame(() => this.flush());
  }

  reset(): void {
    this.queue = [];
    if (this.frame) this.cancelFrame(this.frame);
    this.frame = 0;
  }

  flush(): void {
    this.frame = 0;
    const queued = this.queue;
    this.queue = [];
    const lastCoalescibleIndex = new Map<string, number>();
    queued.forEach(({ event }, index) => {
      if (this.isCoalescible(event)) lastCoalescibleIndex.set(event.stage, index);
    });
    queued.forEach(({ event, jobId }, index) => {
      if (this.isCoalescible(event) && lastCoalescibleIndex.get(event.stage) !== index) return;
      this.render(event, jobId);
    });
  }

  private isCoalescible(event: T): boolean {
    const hasDetailedFlow = Boolean(
      event.data?.cluster_audit || event.data?.locate_flow || event.data?.curation_flow,
    );
    return event.status === "running" && !hasDetailedFlow;
  }
}
