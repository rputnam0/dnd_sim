import assert from "node:assert/strict";
import test from "node:test";
import {
  createElement,
  useState,
  type ComponentProps,
} from "react";
import TestRenderer, { act } from "react-test-renderer";

import { TacticalMap } from "../app/echo-vault-table";
import { advanceDrawingDraft } from "../app/vtt-drawing-workflow";
import { buildDrawingAnnotation, type DrawingKind } from "../app/vtt-drawings";
import { boardCellToFeet } from "../app/vtt-board-calibration";
import {
  isDrawingAnnotation,
  type AnnotationPoint,
  type DrawingAnnotation,
} from "../app/vtt-annotations";
import type { JournalDocument } from "../app/vtt-journal";

const reactTestEnvironment: typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean } = globalThis;
reactTestEnvironment.IS_REACT_ACT_ENVIRONMENT = true;

const scene = {
  schema_version: "vtt.scene.v1",
  scene_id: "scene-a",
  name: "Test Board",
  grid_type: "square",
  cell_size_ft: 5,
  columns: 4,
  rows: 4,
  origin_ft: { x_ft: 0, y_ft: 0, z_ft: 0 },
} as const;
const mapMetadata = {
  schema_version: "vtt.scene_map_metadata.v1",
  name: "Test Board",
  width_px: 200,
  height_px: 200,
  grid_size_px: 50,
  gridless: false,
  calibration: {
    schema_version: "vtt.board_calibration.v1",
    topology: "square",
    origin_x_px: 25,
    origin_y_px: 25,
    cell_extent_px: 50,
    distance_ft: 5,
  },
} as const;
const projection: ComponentProps<typeof TacticalMap>["projection"] = {
  phase: "awaiting_declaration",
  outcome: null,
  winner: null,
  current_index: 0,
  active_actor_id: null,
  round_number: 1,
  max_rounds: 1,
  initiative_order: [],
  actors: {},
  prompt: null,
  result: null,
  choices: null,
};

interface ObservedState {
  records: DrawingAnnotation[];
  unlocked: string[];
  updated: string[];
  removed: string[];
}

const pinnedHandout: JournalDocument = {
  schema_version: "vtt.journal_document.v1",
  document_id: "pinned-handout",
  document_type: "handout",
  folder_id: null,
  title: "Pinned clue",
  audience: ["all"],
  tags: [],
  favorite: false,
  blocks: [{ schema_version: "vtt.journal_block.v1", block_type: "paragraph", text: "Clue" }],
  map_pin: {
    schema_version: "vtt.journal_map_pin.v1",
    scene_id: "scene-a",
    position: { x_ft: 7.5, y_ft: 7.5, z_ft: 0 },
    color: "#5eead4",
  },
};

function DrawingInteractionHarness({ observe, onJournalPinOpen }: { observe: (value: ObservedState) => void; onJournalPinOpen: (documentId: string) => void }) {
  const [active, setActive] = useState(false);
  const [kind, setKind] = useState<DrawingKind>("freehand");
  const [points, setPoints] = useState<AnnotationPoint[]>([]);
  const [locked, setLocked] = useState(false);
  const [audience, setAudience] = useState<"all" | "self">("all");
  const [opacity, setOpacity] = useState(0.8);
  const [records, setRecords] = useState<DrawingAnnotation[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [unlocked, setUnlocked] = useState<string[]>([]);
  const [updated, setUpdated] = useState<string[]>([]);
  const [removed, setRemoved] = useState<string[]>([]);

  const report = (
    nextRecords = records,
    nextUnlocked = unlocked,
    nextUpdated = updated,
    nextRemoved = removed,
  ) => observe({
    records: nextRecords,
    unlocked: nextUnlocked,
    updated: nextUpdated,
    removed: nextRemoved,
  });

  const persist = (completedKind: DrawingKind, completedPoints: AnnotationPoint[]) => {
    const annotation = buildDrawingAnnotation({
      sceneId: "scene-a",
      authorId: "gm",
      audience: audience === "all" ? ["all"] : ["participant:gm"],
      annotationId: `draw-${completedKind}`,
      kind: completedKind,
      layer: "under_tokens",
      locked,
      style: {
        stroke_color: "#5eead4",
        fill_color: null,
        opacity,
        stroke_width_ft: 1,
        line_style: "solid",
      },
      points: completedPoints,
      text: "Private note",
      fontSizeFt: 3,
      headSizeFt: 2,
    });
    const next = [...records.filter((record) => record.annotation_id !== annotation.annotation_id), annotation];
    setRecords(next);
    setSelectedId(annotation.annotation_id);
    setPoints([]);
    report(next);
  };

  const choosePoint = (cell: { column: number; row: number }) => {
    const feet = boardCellToFeet(mapMetadata.calibration, cell, [2.5, 2.5, 0]);
    const point = { x_ft: feet[0], y_ft: feet[1], z_ft: feet[2] };
    const transition = advanceDrawingDraft(
      { active, kind, points },
      { type: "keyboard_point", key: "Enter", point },
    );
    setPoints(transition.state.points);
    if (transition.completed) persist(transition.completed.kind, transition.completed.points);
  };

  const selected = records.find((record) => record.annotation_id === selectedId);
  const props: ComponentProps<typeof TacticalMap> = {
    scene,
    mapMetadata,
    mapUrl: null,
    mapLoadError: null,
    projection,
    tokens: [],
    tokenStatus: "live",
    tokenError: null,
    visibilityProjection: null,
    visibilitySources: {
      sceneId: scene.scene_id,
      sceneRevision: 1,
      tokenRevision: 0,
      visibilityRevision: 0,
      encounterRevision: 0,
    },
    visibilityStatus: "live",
    visibilityError: null,
    showVisibilityMask: false,
    sharedCamera: null,
    followSharedCamera: false,
    selectedActorId: "",
    selectableTargetIds: new Set(),
    selectedTargetId: null,
    reachableCells: new Set(),
    movementPlan: null,
    measureMode: false,
    measurement: { start: null, end: null },
    pingMode: false,
    templateMode: false,
    templateKind: "circle",
    templateStart: null,
    templateDimensionFt: 5,
    templateAngleDegrees: 90,
    pings: [],
    templates: [],
    drawings: records,
    journalDocuments: [pinnedHandout],
    onJournalDocumentSelect: onJournalPinOpen,
    drawingTool: {
      active,
      kind,
      layer: "under_tokens",
      audience,
      strokeColor: "#5eead4",
      fillColor: "#1d4ed8",
      fillEnabled: false,
      opacity,
      strokeWidthFt: 1,
      lineStyle: "solid",
      locked,
      text: "Private note",
      fontSizeFt: 3,
      pointCount: points.length,
      error: null,
    },
    annotations: records,
    selectedAnnotationId: selectedId,
    annotationStatus: "live",
    annotationError: null,
    annotationOperation: null,
    annotationCanMutate: true,
    annotationCanManage: () => true,
    currentParticipantId: "gm",
    templatePlacementError: null,
    onTokenSelect: () => undefined,
    onTargetSelect: () => undefined,
    onCellSelect: choosePoint,
    onGridlessPointSelect: () => undefined,
    onMeasureToggle: () => undefined,
    onMeasureClear: () => undefined,
    onPingToggle: () => undefined,
    onTemplateToggle: () => undefined,
    onTemplateKindChange: () => undefined,
    onTemplateDimensionChange: () => undefined,
    onTemplateAngleChange: () => undefined,
    onTemplateCancelStart: () => undefined,
    onDrawingToggle: () => setActive((current) => !current),
    onDrawingSettingsChange: (changes) => {
      if (changes.kind !== undefined) {
        setKind(changes.kind);
        setPoints([]);
      }
      if (changes.locked !== undefined) setLocked(changes.locked);
      if (changes.audience !== undefined) setAudience(changes.audience);
      if (changes.opacity !== undefined) setOpacity(changes.opacity);
    },
    onDrawingFinish: () => {
      const transition = advanceDrawingDraft(
        { active, kind, points },
        { type: "finish" },
      );
      if (transition.completed) persist(transition.completed.kind, transition.completed.points);
    },
    onDrawingCancel: () => setPoints([]),
    onUpdateSelectedDrawing: () => {
      if (!selected || selected.locked) return;
      const next = records.map((record) =>
        record.annotation_id === selected.annotation_id
          ? { ...record, style: { ...record.style, opacity } }
          : record,
      );
      const nextUpdated = [...updated, selected.annotation_id];
      setRecords(next);
      setUpdated(nextUpdated);
      report(next, unlocked, nextUpdated);
    },
    onUnlockSelectedDrawing: () => {
      if (!selected || !selected.locked) return;
      const next = records.map((record) =>
        record.annotation_id === selected.annotation_id
          ? { ...record, locked: false }
          : record,
      );
      const nextUnlocked = [...unlocked, selected.annotation_id];
      setRecords(next);
      setUnlocked(nextUnlocked);
      report(next, nextUnlocked);
    },
    onAnnotationSelect: setSelectedId,
    onRemoveSelected: () => {
      if (!selected || selected.locked) return;
      const next = records.filter((record) => record.annotation_id !== selected.annotation_id);
      const nextRemoved = [...removed, selected.annotation_id];
      setRecords(next);
      setSelectedId(next[0]?.annotation_id ?? "");
      setRemoved(nextRemoved);
      report(next, unlocked, updated, nextRemoved);
    },
    onClearLocal: () => undefined,
    onAnnotationRetry: () => undefined,
  };
  return createElement(TacticalMap, props);
}

function buttonByText(root: TestRenderer.ReactTestInstance, text: string) {
  return root.findAllByType("button").find((button) =>
    button.children.some((child) => typeof child === "string" && child.includes(text)),
  );
}

test("mounted drawing controls create every variant then unlock update and remove", async () => {
  let observed: ObservedState = { records: [], unlocked: [], updated: [], removed: [] };
  const openedPins: string[] = [];
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(
      createElement(DrawingInteractionHarness, {
        observe: (value: ObservedState) => { observed = value; },
        onJournalPinOpen: (documentId: string) => openedPins.push(documentId),
      }),
    );
  });
  const root = renderer.root;
  const draw = root.findByProps({ "aria-keyshortcuts": "D" });
  await act(async () => draw.props.onClick());
  const pin = root.findByProps({ "aria-label": "Open handout Pinned clue" });
  await act(async () => pin.props.onClick());
  assert.deepEqual(openedPins, ["pinned-handout"]);

  const cells = () => root.findAllByProps({ role: "gridcell" });
  for (const kind of ["freehand", "rectangle", "ellipse", "arrow", "text"] as const) {
    const typeSelect = root.findAllByType("select").find(
      (select) => select.findAllByType("option").some(
        (option) => option.props.value === "freehand",
      ),
    );
    assert.ok(typeSelect);
    await act(async () => typeSelect.props.onChange({ target: { value: kind } }));
    if (kind === "arrow") {
      const lock = root.findAllByType("input").filter(
        (input) => input.props.type === "checkbox",
      ).at(-1);
      assert.ok(lock);
      await act(async () => lock.props.onChange({ target: { checked: true } }));
    }
    if (kind === "text") {
      const audienceSelect = root.findAllByType("select").find(
        (select) => select.findAllByType("option").some(
          (option) => option.props.value === "self",
        ),
      );
      assert.ok(audienceSelect);
      await act(async () => audienceSelect.props.onChange({ target: { value: "self" } }));
    }
    const required = kind === "text" ? 1 : kind === "freehand" ? 3 : 2;
    const cellIndexes = kind === "text"
      ? [8]
      : kind === "freehand"
        ? [0, 1, 2]
        : [0, 5];
    for (let index = 0; index < required; index += 1) {
      await act(async () => cells()[cellIndexes[index]].props.onKeyDown({
        key: index % 2 === 0 ? "Enter" : " ",
        preventDefault: () => undefined,
        stopPropagation: () => undefined,
      }));
    }
    if (kind === "freehand") {
      const finish = buttonByText(root, "Finish path");
      assert.ok(finish);
      await act(async () => finish.props.onClick());
    }
    if (kind === "arrow") {
      const unlock = buttonByText(root, "Unlock selected drawing");
      assert.ok(unlock);
      await act(async () => unlock.props.onClick());
      const opacityInput = root.findAllByType("input").find((input) => input.props.type === "number" && input.props.max === "1");
      assert.ok(opacityInput);
      await act(async () => opacityInput.props.onChange({ target: { value: "0.5" } }));
      const update = buttonByText(root, "Update selected drawing");
      assert.ok(update);
      await act(async () => update.props.onClick());
      const remove = buttonByText(root, "Remove selected");
      assert.ok(remove);
      await act(async () => remove.props.onClick());
    }
    if (kind === "arrow") {
      const lock = root.findAllByType("input").filter(
        (input) => input.props.type === "checkbox",
      ).at(-1);
      if (lock) await act(async () => lock.props.onChange({ target: { checked: false } }));
    }
  }

  assert.deepEqual(observed.unlocked, ["draw-arrow"]);
  assert.deepEqual(observed.updated, ["draw-arrow"]);
  assert.deepEqual(observed.removed, ["draw-arrow"]);
  assert.deepEqual(
    observed.records.map((record) => record.annotation_id).sort(),
    ["draw-ellipse", "draw-freehand", "draw-rectangle", "draw-text"],
  );
  const privateText = observed.records.find((record) => record.annotation_id === "draw-text");
  assert.ok(privateText && isDrawingAnnotation(privateText));
  assert.deepEqual(privateText.audience, ["participant:gm"]);

  await act(async () => renderer.unmount());
});
