"use client";

import { useCallback, useRef } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  EdgeText,
  getSmoothStepPath,
  useReactFlow,
  type EdgeProps,
  type XYPosition,
} from "@xyflow/react";

interface EditableEdgeData {
  /** User-placed bend point (flow coordinates). Absent → default route. */
  waypoint?: XYPosition;
  /** Fallback/loop-back edge — bowed out to the side by default so it doesn't hide behind
   *  the vertical main chain it runs alongside. */
  fallback?: boolean;
  [k: string]: unknown;
}

/** How far a fallback edge bows out to the side of the node column, in flow units. */
const FALLBACK_BOW = 220;

/** Path from `a` to `b` bent through `m`, with the corner at `m` rounded. */
function roundedThrough(a: XYPosition, m: XYPosition, b: XYPosition, r = 16): string {
  const dist = (p: XYPosition, q: XYPosition) => Math.hypot(q.x - p.x, q.y - p.y) || 1;
  const toward = (from: XYPosition, to: XYPosition, len: number) => ({
    x: from.x + ((to.x - from.x) / dist(from, to)) * len,
    y: from.y + ((to.y - from.y) / dist(from, to)) * len,
  });
  const rIn = Math.min(r, dist(a, m) / 2);
  const rOut = Math.min(r, dist(m, b) / 2);
  const p1 = toward(m, a, rIn);
  const p2 = toward(m, b, rOut);
  return `M ${a.x},${a.y} L ${p1.x},${p1.y} Q ${m.x},${m.y} ${p2.x},${p2.y} L ${b.x},${b.y}`;
}

/**
 * Pipeline edge with a draggable bend handle. Drag the dot on a connection to route it
 * around nodes; the bend persists on the edge. Double-click the handle to straighten it.
 * With no bend it renders the standard orthogonal smoothstep path, matching plain edges.
 */
export default function EditablePipelineEdge(props: EdgeProps) {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style,
    markerEnd,
    label,
    labelStyle,
    labelBgStyle,
    labelBgPadding,
    labelBgBorderRadius,
    data,
  } = props;
  const { screenToFlowPosition, setEdges } = useReactFlow();
  const edgeData = data as EditableEdgeData | undefined;
  const wp = edgeData?.waypoint;
  const draggingRef = useRef(false);

  const [smoothPath, smoothLabelX, smoothLabelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const source: XYPosition = { x: sourceX, y: sourceY };
  const target: XYPosition = { x: targetX, y: targetY };

  // Default route: smoothstep for normal edges; a side-bowed arc for fallback/loop-back
  // edges (they run against the vertical main chain and would otherwise hide behind it).
  // A user-placed waypoint overrides either default.
  const defaultBow: XYPosition | null = edgeData?.fallback
    ? { x: Math.max(sourceX, targetX) + FALLBACK_BOW, y: (sourceY + targetY) / 2 }
    : null;
  const bend = wp ?? defaultBow;
  const handle = bend ?? { x: smoothLabelX, y: smoothLabelY };
  const path = bend ? roundedThrough(source, bend, target) : smoothPath;

  const setWaypoint = useCallback(
    (pos: XYPosition | undefined) => {
      setEdges((eds) =>
        eds.map((e) => (e.id === id ? { ...e, data: { ...e.data, waypoint: pos } } : e)),
      );
    },
    [id, setEdges],
  );

  const onPointerDown = useCallback((ev: React.PointerEvent) => {
    ev.stopPropagation();
    (ev.target as Element).setPointerCapture(ev.pointerId);
    draggingRef.current = true;
  }, []);

  const onPointerMove = useCallback(
    (ev: React.PointerEvent) => {
      if (!draggingRef.current) return;
      ev.stopPropagation();
      setWaypoint(screenToFlowPosition({ x: ev.clientX, y: ev.clientY }));
    },
    [screenToFlowPosition, setWaypoint],
  );

  const onPointerUp = useCallback((ev: React.PointerEvent) => {
    draggingRef.current = false;
    (ev.target as Element).releasePointerCapture?.(ev.pointerId);
  }, []);

  const onDoubleClick = useCallback(
    (ev: React.MouseEvent) => {
      ev.stopPropagation();
      setWaypoint(undefined);
    },
    [setWaypoint],
  );

  return (
    <>
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      {label && (
        <EdgeText
          x={handle.x}
          y={handle.y - 12}
          label={label}
          labelStyle={labelStyle}
          labelBgStyle={labelBgStyle}
          labelBgPadding={labelBgPadding}
          labelBgBorderRadius={labelBgBorderRadius}
        />
      )}
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan"
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${handle.x}px, ${handle.y}px)`,
            pointerEvents: "all",
          }}
        >
          <div
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onDoubleClick={onDoubleClick}
            title={
              wp
                ? "Drag to reroute this connection, double-click to straighten it"
                : "Drag to bend this connection"
            }
            style={{
              width: wp ? 11 : 9,
              height: wp ? 11 : 9,
              borderRadius: "50%",
              cursor: "grab",
              background: wp ? "#818cf8" : "rgba(148,163,184,0.7)",
              border: "1.5px solid #ffffff",
              boxShadow: "0 1px 2px rgba(0,0,0,0.25)",
              opacity: wp ? 1 : 0.5,
            }}
          />
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
