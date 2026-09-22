import {
  feetToBoardPixel,
  type BoardCalibration,
  type BoardPoint,
  type FeetPoint,
} from "./vtt-board-calibration";
import {
  parseVttAnnotation,
  type AnnotationPoint,
  type DrawingAnnotation,
  type DrawingStyle,
} from "./vtt-annotations";

export type DrawingKind = "freehand" | "rectangle" | "ellipse" | "arrow" | "text";

interface BuildDrawingInput {
  sceneId: string;
  authorId: string;
  audience: string[];
  kind: DrawingKind;
  layer: "under_tokens" | "over_tokens";
  locked: boolean;
  style: DrawingStyle;
  points: AnnotationPoint[];
  annotationId?: string;
  text?: string;
  fontSizeFt?: number;
  backgroundColor?: string | null;
  headSizeFt?: number;
}

function requirePoint(points: AnnotationPoint[], index: number): AnnotationPoint {
  const point = points[index];
  if (point === undefined) throw new Error("Drawing placement is missing a control point.");
  return point;
}

export function buildDrawingAnnotation(input: BuildDrawingInput): DrawingAnnotation {
  const base = {
    schema_version: "vtt.annotation.v1" as const,
    annotation_id: input.annotationId ?? crypto.randomUUID(),
    scene_id: input.sceneId,
    author_id: input.authorId,
    audience: input.audience,
    layer: input.layer,
    locked: input.locked,
    style: input.style,
  };
  let annotation: DrawingAnnotation;
  if (input.kind === "freehand") {
    annotation = {
      ...base,
      annotation_type: "freehand_drawing",
      points: input.points,
    };
  } else if (input.kind === "rectangle" || input.kind === "ellipse") {
    annotation = {
      ...base,
      annotation_type: "shape_drawing",
      shape: input.kind,
      corner_a: requirePoint(input.points, 0),
      corner_b: requirePoint(input.points, 1),
    };
  } else if (input.kind === "arrow") {
    annotation = {
      ...base,
      annotation_type: "arrow_drawing",
      start: requirePoint(input.points, 0),
      end: requirePoint(input.points, 1),
      head_size_ft: input.headSizeFt ?? input.style.stroke_width_ft * 2,
    };
  } else {
    annotation = {
      ...base,
      annotation_type: "text_drawing",
      anchor: requirePoint(input.points, 0),
      text: input.text ?? "Map note",
      font_size_ft: input.fontSizeFt ?? 3,
      background_color: input.backgroundColor ?? null,
    };
  }
  return parseVttAnnotation(annotation) as DrawingAnnotation;
}

interface ProjectedDrawingBase {
  annotation: DrawingAnnotation;
  strokeWidthPx: number;
  opacity: number;
  stroke: string;
  fill: string | null;
  dashed: boolean;
}

export interface ProjectedFreehandDrawing extends ProjectedDrawingBase {
  kind: "freehand";
  points: BoardPoint[];
}

interface ProjectedShapeDrawingBase extends ProjectedDrawingBase {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ProjectedRectangleDrawing extends ProjectedShapeDrawingBase {
  kind: "rectangle";
}

export interface ProjectedEllipseDrawing extends ProjectedShapeDrawingBase {
  kind: "ellipse";
}

export interface ProjectedArrowDrawing extends ProjectedDrawingBase {
  kind: "arrow";
  start: BoardPoint;
  end: BoardPoint;
  headSizePx: number;
}

export interface ProjectedTextDrawing extends ProjectedDrawingBase {
  kind: "text";
  anchor: BoardPoint;
  text: string;
  fontSizePx: number;
  backgroundColor: string | null;
}

export type ProjectedDrawing =
  | ProjectedFreehandDrawing
  | ProjectedRectangleDrawing
  | ProjectedEllipseDrawing
  | ProjectedArrowDrawing
  | ProjectedTextDrawing;

function projectPoint(
  point: AnnotationPoint,
  calibration: BoardCalibration,
  originFeet: FeetPoint,
): BoardPoint {
  return feetToBoardPixel(
    calibration,
    [point.x_ft, point.y_ft, point.z_ft],
    originFeet,
  );
}

function pxForFeet(value: number, calibration: BoardCalibration): number {
  return value / calibration.distance_ft * calibration.cell_extent_px;
}

function projectionBase(
  annotation: DrawingAnnotation,
  calibration: BoardCalibration,
): ProjectedDrawingBase {
  return {
    annotation,
    strokeWidthPx: pxForFeet(annotation.style.stroke_width_ft, calibration),
    opacity: annotation.style.opacity,
    stroke: annotation.style.stroke_color,
    fill: annotation.style.fill_color,
    dashed: annotation.style.line_style === "dashed",
  };
}

export function projectDrawingAnnotation(
  annotation: DrawingAnnotation,
  calibration: BoardCalibration,
  originFeet: FeetPoint,
): ProjectedDrawing {
  const base = projectionBase(annotation, calibration);
  if (annotation.annotation_type === "freehand_drawing") {
    return {
      ...base,
      kind: "freehand",
      points: annotation.points.map((point) =>
        projectPoint(point, calibration, originFeet),
      ),
    };
  }
  if (annotation.annotation_type === "shape_drawing") {
    const first = projectPoint(annotation.corner_a, calibration, originFeet);
    const second = projectPoint(annotation.corner_b, calibration, originFeet);
    return {
      ...base,
      kind: annotation.shape,
      x: Math.min(first.x_px, second.x_px),
      y: Math.min(first.y_px, second.y_px),
      width: Math.abs(second.x_px - first.x_px),
      height: Math.abs(second.y_px - first.y_px),
    };
  }
  if (annotation.annotation_type === "arrow_drawing") {
    return {
      ...base,
      kind: "arrow",
      start: projectPoint(annotation.start, calibration, originFeet),
      end: projectPoint(annotation.end, calibration, originFeet),
      headSizePx: pxForFeet(annotation.head_size_ft, calibration),
    };
  }
  return {
    ...base,
    kind: "text",
    anchor: projectPoint(annotation.anchor, calibration, originFeet),
    text: annotation.text,
    fontSizePx: pxForFeet(annotation.font_size_ft, calibration),
    backgroundColor: annotation.background_color,
  };
}

export function drawingLayer(
  annotations: DrawingAnnotation[],
  layer: DrawingAnnotation["layer"],
): DrawingAnnotation[] {
  const compareCodePoints = (left: string, right: string): number => {
    const leftPoints = Array.from(left, (character) => character.codePointAt(0) as number);
    const rightPoints = Array.from(right, (character) => character.codePointAt(0) as number);
    for (let index = 0; index < Math.min(leftPoints.length, rightPoints.length); index += 1) {
      if (leftPoints[index] !== rightPoints[index]) return leftPoints[index] - rightPoints[index];
    }
    return leftPoints.length - rightPoints.length;
  };
  return annotations
    .filter((annotation) => annotation.layer === layer)
    .sort((left, right) => compareCodePoints(left.annotation_id, right.annotation_id));
}
