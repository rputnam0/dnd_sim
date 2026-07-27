import {
  parseVttAnnotation,
  type CircleTemplateAnnotation,
  type ConeTemplateAnnotation,
  type CubeTemplateAnnotation,
  type LineTemplateAnnotation,
} from "./vtt-annotations";
import {
  cellToFeet,
  type GridCell,
  type SquareGridScene,
} from "./vtt-client";

export type AreaTemplateAnnotation =
  | CircleTemplateAnnotation
  | ConeTemplateAnnotation
  | LineTemplateAnnotation
  | CubeTemplateAnnotation;

export type AreaTemplateKind = "circle" | "cone" | "line" | "cube";

interface TemplateIdentity {
  scene: SquareGridScene;
  authorId: string;
  annotationId?: string;
  audience?: readonly string[];
}

export type AreaTemplatePlacement = TemplateIdentity &
  (
    | { kind: "circle"; center: GridCell; radiusFt: number }
    | { kind: "cube"; center: GridCell; sizeFt: number }
    | { kind: "line"; start: GridCell; end: GridCell; widthFt: number }
    | {
        kind: "cone";
        origin: GridCell;
        directionEnd: GridCell;
        angleDegrees: number;
      }
  );

export type AreaTemplateGridGeometry =
  | {
      kind: "circle";
      centerX: number;
      centerY: number;
      radius: number;
    }
  | {
      kind: "cube";
      x: number;
      y: number;
      width: number;
      height: number;
    }
  | {
      kind: "line";
      startX: number;
      startY: number;
      endX: number;
      endY: number;
      width: number;
    }
  | {
      kind: "cone";
      originX: number;
      originY: number;
      radius: number;
      directionDegrees: number;
      angleDegrees: number;
      startX: number;
      startY: number;
      endX: number;
      endY: number;
    };

const MAX_TEMPLATE_SIZE_FT = 100_000;

function templateDistance(value: number, field: string): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value <= 0 ||
    value > MAX_TEMPLATE_SIZE_FT
  ) {
    throw new Error(`${field} must be greater than 0 and at most 100000 feet`);
  }
  return value;
}

function coneAngle(value: number): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value <= 0 ||
    value > 180
  ) {
    throw new Error("angleDegrees must be greater than 0 and at most 180");
  }
  return value;
}

function sameCell(left: GridCell, right: GridCell): boolean {
  return left.column === right.column && left.row === right.row;
}

function templateIdentity(input: TemplateIdentity) {
  return {
    schema_version: "vtt.annotation.v1" as const,
    annotation_id: input.annotationId ?? crypto.randomUUID(),
    scene_id: input.scene.scene_id,
    author_id: input.authorId,
    audience: [...(input.audience ?? ["all"])],
  };
}

function requireAreaTemplate(annotation: unknown): AreaTemplateAnnotation {
  const parsed = parseVttAnnotation(annotation);
  if (
    parsed.annotation_type === "ping" ||
    parsed.annotation_type === "ruler"
  ) {
    throw new Error("annotation must be an area template");
  }
  return parsed;
}

export function buildAreaTemplateAnnotation(
  input: AreaTemplatePlacement,
): AreaTemplateAnnotation {
  const identity = templateIdentity(input);
  if (input.kind === "circle") {
    const [x_ft, y_ft, z_ft] = cellToFeet(input.scene, input.center);
    return requireAreaTemplate({
      ...identity,
      annotation_type: "circle_template",
      center: { x_ft, y_ft, z_ft },
      radius_ft: templateDistance(input.radiusFt, "radiusFt"),
    });
  }
  if (input.kind === "cube") {
    const [x_ft, y_ft, z_ft] = cellToFeet(input.scene, input.center);
    return requireAreaTemplate({
      ...identity,
      annotation_type: "cube_template",
      center: { x_ft, y_ft, z_ft },
      size_ft: templateDistance(input.sizeFt, "sizeFt"),
    });
  }
  if (input.kind === "line") {
    if (sameCell(input.start, input.end)) {
      throw new Error("Line endpoints must use different grid cells");
    }
    const [startX, startY, startZ] = cellToFeet(input.scene, input.start);
    const [endX, endY, endZ] = cellToFeet(input.scene, input.end);
    return requireAreaTemplate({
      ...identity,
      annotation_type: "line_template",
      start: { x_ft: startX, y_ft: startY, z_ft: startZ },
      end: { x_ft: endX, y_ft: endY, z_ft: endZ },
      width_ft: templateDistance(input.widthFt, "widthFt"),
    });
  }

  if (sameCell(input.origin, input.directionEnd)) {
    throw new Error("Cone endpoints must use different grid cells");
  }
  const [originX, originY, originZ] = cellToFeet(input.scene, input.origin);
  const [endX, endY] = cellToFeet(input.scene, input.directionEnd);
  const deltaX = endX - originX;
  const deltaY = endY - originY;
  const direction = (Math.atan2(deltaY, deltaX) * 180) / Math.PI;
  return requireAreaTemplate({
    ...identity,
    annotation_type: "cone_template",
    origin: { x_ft: originX, y_ft: originY, z_ft: originZ },
    direction_degrees: direction < 0 ? direction + 360 : direction,
    length_ft: templateDistance(Math.hypot(deltaX, deltaY), "lengthFt"),
    angle_degrees: coneAngle(input.angleDegrees),
  });
}

function pointToGrid(
  scene: SquareGridScene,
  point: { x_ft: number; y_ft: number },
): { x: number; y: number } {
  return {
    x: (point.x_ft - scene.origin_ft.x_ft) / scene.cell_size_ft,
    y: (point.y_ft - scene.origin_ft.y_ft) / scene.cell_size_ft,
  };
}

export function projectAreaTemplateToGrid(
  scene: SquareGridScene,
  annotation: AreaTemplateAnnotation,
): AreaTemplateGridGeometry {
  if (annotation.scene_id !== scene.scene_id) {
    throw new Error("Template scene_id does not match the rendered scene");
  }
  if (annotation.annotation_type === "circle_template") {
    const center = pointToGrid(scene, annotation.center);
    return {
      kind: "circle",
      centerX: center.x,
      centerY: center.y,
      radius: annotation.radius_ft / scene.cell_size_ft,
    };
  }
  if (annotation.annotation_type === "cube_template") {
    const center = pointToGrid(scene, annotation.center);
    const size = annotation.size_ft / scene.cell_size_ft;
    return {
      kind: "cube",
      x: center.x - size / 2,
      y: center.y - size / 2,
      width: size,
      height: size,
    };
  }
  if (annotation.annotation_type === "line_template") {
    const start = pointToGrid(scene, annotation.start);
    const end = pointToGrid(scene, annotation.end);
    return {
      kind: "line",
      startX: start.x,
      startY: start.y,
      endX: end.x,
      endY: end.y,
      width: annotation.width_ft / scene.cell_size_ft,
    };
  }

  const origin = pointToGrid(scene, annotation.origin);
  const radius = annotation.length_ft / scene.cell_size_ft;
  const startRadians =
    ((annotation.direction_degrees - annotation.angle_degrees / 2) * Math.PI) /
    180;
  const endRadians =
    ((annotation.direction_degrees + annotation.angle_degrees / 2) * Math.PI) /
    180;
  return {
    kind: "cone",
    originX: origin.x,
    originY: origin.y,
    radius,
    directionDegrees: annotation.direction_degrees,
    angleDegrees: annotation.angle_degrees,
    startX: origin.x + radius * Math.cos(startRadians),
    startY: origin.y + radius * Math.sin(startRadians),
    endX: origin.x + radius * Math.cos(endRadians),
    endY: origin.y + radius * Math.sin(endRadians),
  };
}
