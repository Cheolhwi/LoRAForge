import { describe, expect, it } from "vitest";

import { createFlowEdges } from "./FlowCanvas";

describe("createFlowEdges", () => {
  it("marks edges as bypassed when either pipeline node is disabled", () => {
    const nodes = [
      { id: "scan", data: { option: "deduplicate" } },
      { id: "embedding", data: { option: "embedding" } },
      { id: "output", data: { option: "output" } },
    ] as any;

    const edges = createFlowEdges(
      [["scan", "embedding"], ["embedding", "output"]],
      nodes,
      { deduplicate: true, embedding: false },
    );

    expect(edges.map((edge) => edge.className)).toEqual([
      "canvas-edge bypassed",
      "canvas-edge bypassed",
    ]);
  });

  it("keeps locked nodes active when they have no configurable option", () => {
    const nodes = [
      { id: "input", data: { option: "input" } },
      { id: "scan", data: { option: "deduplicate" } },
    ] as any;

    const [edge] = createFlowEdges(
      [["input", "scan"]],
      nodes,
      { deduplicate: true },
    );

    expect(edge.className).toBe("canvas-edge active");
  });
});
