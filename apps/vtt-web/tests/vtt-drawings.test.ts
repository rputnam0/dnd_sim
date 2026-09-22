import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  buildDrawingAnnotation,
  projectDrawingAnnotation,
} from "../app/vtt-drawings";
import {
  advanceDrawingDraft,
  type DrawingDraftResult,
  type DrawingDraftState,
} from "../app/vtt-drawing-workflow";
import type { AnnotationPoint, DrawingAnnotation } from "../app/vtt-annotations";
import { clearUnlockedOwnedAnnotations } from "../app/vtt-annotation-workflow";
import type { BoardCalibration } from "../app/vtt-board-calibration";
import { VttDrawingLayer } from "../app/vtt-drawing-layer";

const originFeet = [0, 0, 0] as const;
const calibrations: BoardCalibration[] = [
  {
    schema_version: "vtt.board_calibration.v1",
    topology: "square",
    origin_x_px: 50,
    origin_y_px: 25,
    cell_extent_px: 50,
    distance_ft: 5,
  },
  {
    schema_version: "vtt.board_calibration.v1",
    topology: "hex_flat",
    origin_x_px: 50,
    origin_y_px: 25,
    cell_extent_px: 50,
    distance_ft: 5,
  },
  {
    schema_version: "vtt.board_calibration.v1",
    topology: "hex_pointy",
    origin_x_px: 50,
    origin_y_px: 25,
    cell_extent_px: 50,
    distance_ft: 5,
  },
  {
    schema_version: "vtt.board_calibration.v1",
    topology: "gridless",
    origin_x_px: 50,
    origin_y_px: 25,
    cell_extent_px: 50,
    distance_ft: 5,
  },
];

test("builds all drawing kinds from world-feet controls", () => {
  const common = {
    sceneId: "scene-a",
    authorId: "gm",
    audience: ["all"],
    layer: "under_tokens" as const,
    locked: false,
    style: {
      stroke_color: "#5eead4",
      fill_color: null,
      opacity: 0.8,
      stroke_width_ft: 1,
      line_style: "solid" as const,
    },
    points: [
      { x_ft: 5, y_ft: 10, z_ft: 0 },
      { x_ft: 15, y_ft: 20, z_ft: 0 },
    ],
  };
  assert.equal(buildDrawingAnnotation({ ...common, kind: "freehand", annotationId: "free" }).annotation_type, "freehand_drawing");
  assert.equal(buildDrawingAnnotation({ ...common, kind: "rectangle", annotationId: "rect" }).annotation_type, "shape_drawing");
  assert.equal(buildDrawingAnnotation({ ...common, kind: "ellipse", annotationId: "ellipse" }).annotation_type, "shape_drawing");
  assert.equal(buildDrawingAnnotation({ ...common, kind: "arrow", annotationId: "arrow", headSizeFt: 2 }).annotation_type, "arrow_drawing");
  assert.equal(buildDrawingAnnotation({ ...common, kind: "text", annotationId: "text", text: "North", fontSizeFt: 3 }).annotation_type, "text_drawing");
});

test("projects drawing feet identically through every calibrated topology", () => {
  const annotation = buildDrawingAnnotation({
    sceneId: "scene-a",
    authorId: "gm",
    audience: ["all"],
    annotationId: "arrow",
    kind: "arrow",
    layer: "over_tokens",
    locked: false,
    style: {
      stroke_color: "#5eead4",
      fill_color: null,
      opacity: 1,
      stroke_width_ft: 1,
      line_style: "dashed",
    },
    points: [
      { x_ft: 5, y_ft: 10, z_ft: 0 },
      { x_ft: 15, y_ft: 20, z_ft: 0 },
    ],
    headSizeFt: 2,
  });

  const projected = calibrations.map((calibration) =>
    projectDrawingAnnotation(annotation, calibration, originFeet),
  );
  for (const value of projected) {
    assert.equal(value.kind, "arrow");
    if (value.kind !== "arrow") throw new Error("expected arrow");
    assert.deepEqual(value.start, { x_px: 100, y_px: 125 });
    assert.deepEqual(value.end, { x_px: 200, y_px: 225 });
    assert.equal(value.strokeWidthPx, 10);
    assert.equal(value.headSizePx, 20);
  }
});

test("renders ordered layers while escaping plain text markup", () => {
  const annotation = buildDrawingAnnotation({
    sceneId: "scene-a",
    authorId: "gm",
    audience: ["all"],
    annotationId: "text-a",
    kind: "text",
    layer: "over_tokens",
    locked: true,
    style: {
      stroke_color: "#5eead4",
      fill_color: null,
      opacity: 1,
      stroke_width_ft: 1,
      line_style: "solid",
    },
    points: [{ x_ft: 5, y_ft: 10, z_ft: 0 }],
    text: "Hold <script>alert(1)</script>",
    fontSizeFt: 3,
    backgroundColor: "#112233",
  });
  const html = renderToStaticMarkup(
    createElement(VttDrawingLayer, {
      drawings: [annotation],
      layer: "over_tokens",
      calibration: calibrations[0],
      originFeet,
      widthPx: 500,
      heightPx: 300,
      selectedAnnotationId: "text-a",
    }),
  );
  assert.match(html, /drawing-over-tokens/);
  assert.match(html, /data-plain-text="true"/);
  assert.match(html, /Hold &lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("drives every drawing through keyboard placement and record-scoped persistence", () => {
  let draft: DrawingDraftState = {
    active: false,
    kind: "freehand",
    points: [],
  };
  draft = advanceDrawingDraft(draft, { type: "shortcut", key: "D" }).state;
  assert.equal(draft.active, true);

  let records: DrawingAnnotation[] = [];
  const positions: Record<string, AnnotationPoint[]> = {
    freehand: [
      { x_ft: 5, y_ft: 5, z_ft: 0 },
      { x_ft: 10, y_ft: 15, z_ft: 0 },
      { x_ft: 15, y_ft: 5, z_ft: 0 },
    ],
    rectangle: [
      { x_ft: 20, y_ft: 5, z_ft: 0 },
      { x_ft: 30, y_ft: 15, z_ft: 0 },
    ],
    ellipse: [
      { x_ft: 35, y_ft: 5, z_ft: 0 },
      { x_ft: 45, y_ft: 15, z_ft: 0 },
    ],
    arrow: [
      { x_ft: 5, y_ft: 25, z_ft: 0 },
      { x_ft: 20, y_ft: 30, z_ft: 0 },
    ],
    text: [{ x_ft: 30, y_ft: 30, z_ft: 0 }],
  };
  const kinds = ["freehand", "rectangle", "ellipse", "arrow", "text"] as const;
  for (const kind of kinds) {
    draft = advanceDrawingDraft(draft, { type: "select_kind", kind }).state;
    let completed: DrawingDraftResult["completed"] = null;
    for (const [index, point] of positions[kind].entries()) {
      const transition = advanceDrawingDraft(draft, {
        type: "keyboard_point",
        key: index % 2 === 0 ? "Enter" : " ",
        point,
      });
      draft = transition.state;
      completed = transition.completed;
    }
    if (kind === "freehand") {
      const transition = advanceDrawingDraft(draft, { type: "finish" });
      draft = transition.state;
      completed = transition.completed;
    }
    assert.ok(completed, `${kind} must complete through keyboard points`);
    assert.equal(completed.kind, kind);
    records.push(buildDrawingAnnotation({
      sceneId: "scene-a",
      authorId: "gm",
      audience: kind === "text" ? ["participant:gm"] : ["all"],
      annotationId: `keyboard-${kind}`,
      kind,
      layer: kind === "text" ? "over_tokens" : "under_tokens",
      locked: kind === "arrow",
      style: {
        stroke_color: "#5eead4",
        fill_color: null,
        opacity: 0.8,
        stroke_width_ft: 1,
        line_style: "solid",
      },
      points: completed.points,
      text: "Private keyboard note",
      fontSizeFt: 3,
      headSizeFt: 2,
    }));
  }
  assert.deepEqual(
    records.map((record) => record.annotation_type),
    [
      "freehand_drawing",
      "shape_drawing",
      "shape_drawing",
      "arrow_drawing",
      "text_drawing",
    ],
  );

  const arrowIndex = records.findIndex(
    (record) => record.annotation_id === "keyboard-arrow",
  );
  assert.equal(records[arrowIndex]?.locked, true);
  assert.throws(() => {
    const arrow = records[arrowIndex];
    if (!arrow || arrow.locked) throw new Error("unlock required");
  }, /unlock required/);

  records = records.map((record) =>
    record.annotation_id === "keyboard-arrow"
      ? { ...record, locked: false }
      : record,
  );
  const unlockedArrow = records[arrowIndex];
  assert.ok(unlockedArrow && !unlockedArrow.locked);
  records = records.map((record) =>
    record.annotation_id === unlockedArrow.annotation_id
      ? {
          ...unlockedArrow,
          style: { ...unlockedArrow.style, opacity: 0.5 },
        }
      : record,
  );
  assert.equal(records[arrowIndex]?.style.opacity, 0.5);
  records = records.filter(
    (record) => record.annotation_id !== unlockedArrow.annotation_id,
  );

  assert.deepEqual(
    records.map((record) => record.annotation_id),
    [
      "keyboard-freehand",
      "keyboard-rectangle",
      "keyboard-ellipse",
      "keyboard-text",
    ],
  );
  assert.deepEqual(records.at(-1)?.audience, ["participant:gm"]);
});

test("bulk clear rechecks a queued drawing lock after each awaited delete", async () => {
  const first = buildDrawingAnnotation({
    sceneId: "scene-a",
    authorId: "gm",
    audience: ["all"],
    annotationId: "first",
    kind: "arrow",
    layer: "under_tokens",
    locked: false,
    style: {
      stroke_color: "#5eead4",
      fill_color: null,
      opacity: 1,
      stroke_width_ft: 1,
      line_style: "solid",
    },
    points: [
      { x_ft: 5, y_ft: 5, z_ft: 0 },
      { x_ft: 10, y_ft: 10, z_ft: 0 },
    ],
  });
  const second = { ...first, annotation_id: "second" };
  let revision = 2;
  let current: DrawingAnnotation[] = [first, second];
  const deleted: string[] = [];

  await clearUnlockedOwnedAnnotations({
    participantId: "gm",
    readCurrentView: () => ({
      schema_version: "vtt.annotations_view.v1",
      session_id: "session-a",
      table_id: "table-a",
      scene_id: "scene-a",
      revision,
      annotations: current,
    }),
    remove: async (_view, annotation) => {
      deleted.push(annotation.annotation_id);
      current = current
        .filter((candidate) => candidate.annotation_id !== annotation.annotation_id)
        .map((candidate) =>
          candidate.annotation_id === "second"
            ? { ...candidate, locked: true }
            : candidate,
        );
      revision += 1;
      await Promise.resolve();
    },
  });

  assert.deepEqual(deleted, ["first"]);
  assert.equal(current[0]?.annotation_id, "second");
  assert.equal(current[0]?.locked, true);
});
