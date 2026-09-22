import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAreaTemplateAnnotation,
  projectAreaTemplateToGrid,
} from "../app/vtt-template-geometry";
import type { SquareGridScene } from "../app/vtt-client";

const scene: SquareGridScene = {
  schema_version: "vtt.scene.v1",
  scene_id: "echo-vault",
  name: "Echo Vault",
  grid_type: "square",
  cell_size_ft: 5,
  columns: 8,
  rows: 6,
  origin_ft: { x_ft: 10, y_ft: 20, z_ft: 0 },
};

const identity = {
  scene,
  authorId: "local",
  audience: ["all"],
} as const;

test("builds one-click circle and cube templates in canonical feet", () => {
  const circle = buildAreaTemplateAnnotation({
    ...identity,
    kind: "circle",
    annotationId: "circle-a",
    center: { column: 2, row: 1 },
    radiusFt: 10,
  });
  assert.deepEqual(circle, {
    schema_version: "vtt.annotation.v1",
    annotation_id: "circle-a",
    scene_id: "echo-vault",
    author_id: "local",
    audience: ["all"],
    annotation_type: "circle_template",
    center: { x_ft: 22.5, y_ft: 27.5, z_ft: 0 },
    radius_ft: 10,
  });
  assert.deepEqual(projectAreaTemplateToGrid(scene, circle), {
    kind: "circle",
    centerX: 2.5,
    centerY: 1.5,
    radius: 2,
  });

  const cube = buildAreaTemplateAnnotation({
    ...identity,
    kind: "cube",
    annotationId: "cube-a",
    center: { column: 2, row: 1 },
    sizeFt: 10,
  });
  assert.deepEqual(projectAreaTemplateToGrid(scene, cube), {
    kind: "cube",
    x: 1.5,
    y: 0.5,
    width: 2,
    height: 2,
  });
});

test("builds two-cell line and cone templates with derived bearing", () => {
  const line = buildAreaTemplateAnnotation({
    ...identity,
    kind: "line",
    annotationId: "line-a",
    start: { column: 0, row: 0 },
    end: { column: 2, row: 1 },
    widthFt: 5,
  });
  assert.deepEqual(projectAreaTemplateToGrid(scene, line), {
    kind: "line",
    startX: 0.5,
    startY: 0.5,
    endX: 2.5,
    endY: 1.5,
    width: 1,
  });

  const cone = buildAreaTemplateAnnotation({
    ...identity,
    kind: "cone",
    annotationId: "cone-a",
    origin: { column: 0, row: 0 },
    directionEnd: { column: 0, row: 2 },
    angleDegrees: 90,
  });
  assert.equal(cone.annotation_type, "cone_template");
  assert.equal(cone.direction_degrees, 90);
  assert.equal(cone.length_ft, 10);
  const coneGeometry = projectAreaTemplateToGrid(scene, cone);
  assert.equal(coneGeometry.kind, "cone");
  if (coneGeometry.kind !== "cone") assert.fail("expected cone geometry");
  const { startX, startY, endX, endY, ...coneFrame } = coneGeometry;
  assert.deepEqual(coneFrame, {
    kind: "cone",
    originX: 0.5,
    originY: 0.5,
    radius: 2,
    directionDegrees: 90,
    angleDegrees: 90,
  });
  assert.ok(Math.abs(startX - (0.5 + Math.SQRT2)) < 1e-12);
  assert.ok(Math.abs(startY - (0.5 + Math.SQRT2)) < 1e-12);
  assert.ok(Math.abs(endX - (0.5 - Math.SQRT2)) < 1e-12);
  assert.ok(Math.abs(endY - (0.5 + Math.SQRT2)) < 1e-12);
});

test("rejects degenerate or out-of-contract template placement", () => {
  assert.throws(
    () =>
      buildAreaTemplateAnnotation({
        ...identity,
        kind: "line",
        annotationId: "line-a",
        start: { column: 1, row: 1 },
        end: { column: 1, row: 1 },
        widthFt: 5,
      }),
    /different grid cells/i,
  );
  assert.throws(
    () =>
      buildAreaTemplateAnnotation({
        ...identity,
        kind: "circle",
        annotationId: "circle-a",
        center: { column: 1, row: 1 },
        radiusFt: 0,
      }),
    /radiusFt/i,
  );
  assert.throws(
    () =>
      buildAreaTemplateAnnotation({
        ...identity,
        kind: "cone",
        annotationId: "cone-a",
        origin: { column: 1, row: 1 },
        directionEnd: { column: 2, row: 1 },
        angleDegrees: 181,
      }),
    /angleDegrees/i,
  );
});
