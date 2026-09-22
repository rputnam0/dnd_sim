import type { CSSProperties } from "react";

import type { BoardCalibration, FeetPoint } from "./vtt-board-calibration";
import {
  drawingLayer,
  projectDrawingAnnotation,
} from "./vtt-drawings";
import type { DrawingAnnotation } from "./vtt-annotations";

function arrowHeadPoints(input: {
  start: { x_px: number; y_px: number };
  end: { x_px: number; y_px: number };
  size: number;
}): string {
  const angle = Math.atan2(
    input.end.y_px - input.start.y_px,
    input.end.x_px - input.start.x_px,
  );
  const spread = Math.PI / 7;
  const left = {
    x: input.end.x_px - input.size * Math.cos(angle - spread),
    y: input.end.y_px - input.size * Math.sin(angle - spread),
  };
  const right = {
    x: input.end.x_px - input.size * Math.cos(angle + spread),
    y: input.end.y_px - input.size * Math.sin(angle + spread),
  };
  return `${input.end.x_px},${input.end.y_px} ${left.x},${left.y} ${right.x},${right.y}`;
}

export function VttDrawingLayer({
  drawings,
  layer,
  calibration,
  originFeet,
  widthPx,
  heightPx,
  selectedAnnotationId,
}: {
  drawings: DrawingAnnotation[];
  layer: DrawingAnnotation["layer"];
  calibration: BoardCalibration;
  originFeet: FeetPoint;
  widthPx: number;
  heightPx: number;
  selectedAnnotationId: string;
}) {
  const projected = drawingLayer(drawings, layer).map((drawing) =>
    projectDrawingAnnotation(drawing, calibration, originFeet),
  );
  if (projected.length === 0) return null;
  return (
    <svg
      className={`drawing-overlay drawing-${layer.replace("_", "-")}`}
      viewBox={`0 0 ${widthPx} ${heightPx}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`${layer === "under_tokens" ? "Under-token" : "Over-token"} shared drawings`}
    >
      {projected.map((drawing) => {
        const selected = drawing.annotation.annotation_id === selectedAnnotationId;
        const common = {
          stroke: drawing.stroke,
          fill: drawing.fill ?? "none",
          opacity: drawing.opacity,
          strokeWidth: drawing.strokeWidthPx,
          strokeDasharray: drawing.dashed
            ? `${drawing.strokeWidthPx * 4} ${drawing.strokeWidthPx * 3}`
            : undefined,
          className: `drawing-mark${selected ? " is-selected" : ""}`,
          "data-annotation-id": drawing.annotation.annotation_id,
        };
        if (drawing.kind === "freehand") {
          return (
            <polyline
              {...common}
              points={drawing.points.map((point) => `${point.x_px},${point.y_px}`).join(" ")}
              strokeLinecap="round"
              strokeLinejoin="round"
              key={drawing.annotation.annotation_id}
            />
          );
        }
        if (drawing.kind === "rectangle") {
          return (
            <rect
              {...common}
              x={drawing.x}
              y={drawing.y}
              width={drawing.width}
              height={drawing.height}
              key={drawing.annotation.annotation_id}
            />
          );
        }
        if (drawing.kind === "ellipse") {
          return (
            <ellipse
              {...common}
              cx={drawing.x + drawing.width / 2}
              cy={drawing.y + drawing.height / 2}
              rx={drawing.width / 2}
              ry={drawing.height / 2}
              key={drawing.annotation.annotation_id}
            />
          );
        }
        if (drawing.kind === "arrow") {
          return (
            <g
              className={`drawing-mark${selected ? " is-selected" : ""}`}
              opacity={drawing.opacity}
              data-annotation-id={drawing.annotation.annotation_id}
              key={drawing.annotation.annotation_id}
            >
              <line
                x1={drawing.start.x_px}
                y1={drawing.start.y_px}
                x2={drawing.end.x_px}
                y2={drawing.end.y_px}
                stroke={drawing.stroke}
                strokeWidth={drawing.strokeWidthPx}
                strokeDasharray={common.strokeDasharray}
                strokeLinecap="round"
              />
              <polygon
                points={arrowHeadPoints({
                  start: drawing.start,
                  end: drawing.end,
                  size: drawing.headSizePx,
                })}
                fill={drawing.stroke}
              />
            </g>
          );
        }
        return (
          <text
            {...common}
            x={drawing.anchor.x_px}
            y={drawing.anchor.y_px}
            fontSize={drawing.fontSizePx}
            fill={drawing.stroke}
            stroke={drawing.backgroundColor ?? "none"}
            strokeWidth={drawing.backgroundColor ? drawing.fontSizePx * 0.3 : 0}
            paintOrder="stroke"
            data-plain-text="true"
            style={{ whiteSpace: "pre" } as CSSProperties}
            key={drawing.annotation.annotation_id}
          >
            {drawing.text.split("\n").map((line, index) => (
              <tspan
                x={drawing.anchor.x_px}
                dy={index === 0 ? 0 : drawing.fontSizePx * 1.2}
                key={index}
              >
                {line}
              </tspan>
            ))}
          </text>
        );
      })}
    </svg>
  );
}
