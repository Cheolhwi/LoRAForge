import {
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
  type Viewport,
  useNodesState,
} from "@xyflow/react";
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

export const NODE_OPTIONS_CHANGED_EVENT = "loraforge:node-options-changed";

export type FlowNodeDefinition = {
  element: HTMLElement;
  id: string;
  option: string;
  position: { x: number; y: number };
  width: number;
};

export type FlowEdgeDefinition = readonly [source: string, target: string];

type LegacyNodeData = {
  element: HTMLElement;
  option: string;
};

type LegacyNode = Node<LegacyNodeData, "legacy">;

export type FlowCanvasController = {
  centerNode: (id: string) => void;
  fit: (animate?: boolean) => void;
  fitNodes: (ids: string[], animate?: boolean) => void;
  getViewport: () => Viewport | null;
  setViewport: (viewport: Viewport, animate?: boolean) => void;
  zoomIn: () => void;
  zoomOut: () => void;
};

type FlowCanvasProps = {
  edgeDefinitions: FlowEdgeDefinition[];
  initialNodeOptions: Record<string, boolean>;
  nodeDefinitions: FlowNodeDefinition[];
  onInstance: (instance: ReactFlowInstance<LegacyNode, Edge>) => void;
  onMounted: () => void;
};

function prepareInteractiveContent(element: HTMLElement) {
  element.style.removeProperty("left");
  element.style.removeProperty("top");
  element.style.removeProperty("width");
  element.classList.add("react-flow-node-content");
  element.querySelectorAll<HTMLElement>("button, input, select, textarea, a").forEach((control) => {
    control.classList.add("nodrag", "nopan");
  });
  element.querySelectorAll<HTMLElement>(
    ".review-gallery, .audit-clusters, .event-log, .table-wrap, textarea",
  ).forEach((scrollable) => scrollable.classList.add("nowheel", "nodrag", "nopan"));
}

const LegacyNodeView = memo(function LegacyNodeView({ data }: NodeProps<LegacyNode>) {
  const hostRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    prepareInteractiveContent(data.element);
    host.replaceChildren(data.element);
  }, [data.element]);

  return (
    <div className="legacy-node-host">
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div ref={hostRef} className="legacy-node-mount" />
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
});

const nodeTypes = { legacy: LegacyNodeView };
const defaultViewport: Viewport = { x: 24, y: 28, zoom: 0.62 };
const fitViewOptions = { padding: 0.06, minZoom: 0.32, maxZoom: 0.78 };
const panButtons = [0, 1];
const proOptions = { hideAttribution: true };

function nodeIsEnabled(
  node: LegacyNode | undefined,
  options: Record<string, boolean>,
) {
  if (!node || !Object.hasOwn(options, node.data.option)) return true;
  return Boolean(options[node.data.option]);
}

export function createFlowEdges(
  edgeDefinitions: FlowEdgeDefinition[],
  nodes: LegacyNode[],
  options: Record<string, boolean>,
): Edge[] {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  return edgeDefinitions.map(([source, target], index) => {
    const active = (
      nodeIsEnabled(nodesById.get(source), options)
      && nodeIsEnabled(nodesById.get(target), options)
    );
    return {
      id: `${source}-${target}`,
      source,
      target,
      type: "default",
      className: `canvas-edge ${active ? "active" : "bypassed"}`,
      deletable: false,
      focusable: false,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: active ? "#aeb7da" : "#9aa5b9",
        height: 14,
        width: 14,
      },
      style: { "--edge-delay": `${index * -0.17}s` } as React.CSSProperties,
    };
  });
}

function FlowCanvas({
  edgeDefinitions,
  initialNodeOptions,
  nodeDefinitions,
  onInstance,
  onMounted,
}: FlowCanvasProps) {
  const initialNodes = useMemo(() => nodeDefinitions.map<LegacyNode>((definition) => ({
    id: definition.id,
    type: "legacy",
    position: definition.position,
    data: {
      element: definition.element,
      option: definition.option,
    },
    dragHandle: ".flow-node-header",
    selectable: false,
    style: { width: definition.width },
  })), [nodeDefinitions]);
  const [nodes, , onNodesChange] = useNodesState<LegacyNode>(initialNodes);
  const [nodeOptions, setNodeOptions] = useState({ ...initialNodeOptions });
  const [edges, setEdges] = useState(() => (
    createFlowEdges(edgeDefinitions, initialNodes, initialNodeOptions)
  ));
  const pendingZoom = useRef(0.62);
  const zoomFrame = useRef(0);

  useEffect(() => {
    const onOptionsChanged = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, boolean>>).detail;
      if (detail) setNodeOptions({ ...detail });
    };
    window.addEventListener(NODE_OPTIONS_CHANGED_EVENT, onOptionsChanged);
    return () => window.removeEventListener(NODE_OPTIONS_CHANGED_EVENT, onOptionsChanged);
  }, []);

  useEffect(() => {
    setEdges(createFlowEdges(edgeDefinitions, initialNodes, nodeOptions));
  }, [edgeDefinitions, initialNodes, nodeOptions]);

  useEffect(() => () => {
    if (zoomFrame.current) cancelAnimationFrame(zoomFrame.current);
  }, []);

  useLayoutEffect(() => {
    const frame = requestAnimationFrame(onMounted);
    return () => cancelAnimationFrame(frame);
  }, [onMounted]);

  const updateZoomLabel = useCallback((viewport: Viewport) => {
    pendingZoom.current = viewport.zoom;
    if (zoomFrame.current) return;
    zoomFrame.current = requestAnimationFrame(() => {
      zoomFrame.current = 0;
      const label = document.getElementById("canvas-zoom-value");
      const value = `${Math.round(pendingZoom.current * 100)}%`;
      if (label && label.textContent !== value) label.textContent = value;
    });
  }, []);

  const setDraggingState = useCallback((_event: MouseEvent | TouchEvent, node: LegacyNode) => {
    node.data.element.classList.add("is-dragging");
  }, []);

  const clearDraggingState = useCallback((_event: MouseEvent | TouchEvent, node: LegacyNode) => {
    node.data.element.classList.remove("is-dragging");
  }, []);

  const handleMove = useCallback((_event, viewport: Viewport) => {
    updateZoomLabel(viewport);
  }, [updateZoomLabel]);

  return (
    <ReactFlow<LegacyNode, Edge>
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onInit={onInstance}
      onMove={handleMove}
      onNodeDragStart={setDraggingState}
      onNodeDragStop={clearDraggingState}
      defaultViewport={defaultViewport}
      minZoom={0.32}
      maxZoom={1.35}
      fitView
      fitViewOptions={fitViewOptions}
      panOnDrag={panButtons}
      panOnScroll={false}
      zoomOnDoubleClick={false}
      zoomOnPinch
      zoomOnScroll
      preventScrolling
      nodesConnectable={false}
      edgesReconnectable={false}
      edgesFocusable={false}
      elementsSelectable={false}
      selectNodesOnDrag={false}
      deleteKeyCode={null}
      noDragClassName="nodrag"
      noPanClassName="nopan"
      noWheelClassName="nowheel"
      proOptions={proOptions}
    />
  );
}

export function mountReactFlowCanvas(
  container: HTMLElement,
  nodeDefinitions: FlowNodeDefinition[],
  edgeDefinitions: FlowEdgeDefinition[],
  initialNodeOptions: Record<string, boolean>,
  onMounted: () => void,
): FlowCanvasController {
  let instance: ReactFlowInstance<LegacyNode, Edge> | null = null;
  const root = createRoot(container);
  root.render(
    <FlowCanvas
      edgeDefinitions={edgeDefinitions}
      initialNodeOptions={initialNodeOptions}
      nodeDefinitions={nodeDefinitions}
      onMounted={onMounted}
      onInstance={(nextInstance) => {
        instance = nextInstance;
      }}
    />,
  );

  const duration = (animate: boolean) => (animate ? 320 : 0);
  return {
    centerNode(id) {
      void instance?.fitView({
        nodes: [{ id }],
        padding: 0.24,
        minZoom: 0.72,
        maxZoom: 1.05,
        duration: 320,
      });
    },
    fit(animate = true) {
      void instance?.fitView({
        padding: 0.06,
        minZoom: 0.32,
        maxZoom: 0.78,
        duration: duration(animate),
      });
    },
    fitNodes(ids, animate = true) {
      void instance?.fitView({
        nodes: ids.map((id) => ({ id })),
        padding: 0.16,
        minZoom: 0.42,
        maxZoom: 1.18,
        duration: duration(animate),
      });
    },
    getViewport() {
      return instance?.getViewport() || null;
    },
    setViewport(viewport, animate = true) {
      void instance?.setViewport(viewport, { duration: duration(animate) });
    },
    zoomIn() {
      void instance?.zoomIn({ duration: 160 });
    },
    zoomOut() {
      void instance?.zoomOut({ duration: 160 });
    },
  };
}
