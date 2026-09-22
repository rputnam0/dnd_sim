import type { AnnotationPoint } from "./vtt-annotations";
import type { DrawingKind } from "./vtt-drawings";

export interface DrawingDraftState {
  active: boolean;
  kind: DrawingKind;
  points: AnnotationPoint[];
}

export type DrawingDraftAction =
  | { type: "shortcut"; key: string }
  | { type: "select_kind"; kind: DrawingKind }
  | {
      type: "keyboard_point";
      key: "Enter" | " ";
      point: AnnotationPoint;
    }
  | { type: "finish" }
  | { type: "cancel" };

export interface DrawingDraftResult {
  state: DrawingDraftState;
  completed:
    | { kind: DrawingKind; points: AnnotationPoint[] }
    | null;
  error: string | null;
}

function samePoint(left: AnnotationPoint, right: AnnotationPoint): boolean {
  return (
    left.x_ft === right.x_ft &&
    left.y_ft === right.y_ft &&
    left.z_ft === right.z_ft
  );
}

export function advanceDrawingDraft(
  current: DrawingDraftState,
  action: DrawingDraftAction,
): DrawingDraftResult {
  if (action.type === "shortcut") {
    if (action.key.toLowerCase() !== "d") {
      return { state: current, completed: null, error: null };
    }
    return {
      state: { ...current, active: !current.active, points: [] },
      completed: null,
      error: null,
    };
  }
  if (action.type === "select_kind") {
    return {
      state: { ...current, kind: action.kind, points: [] },
      completed: null,
      error: null,
    };
  }
  if (action.type === "cancel") {
    return {
      state: { ...current, points: [] },
      completed: null,
      error: null,
    };
  }
  if (action.type === "finish") {
    if (!current.active || current.kind !== "freehand" || current.points.length < 2) {
      return {
        state: current,
        completed: null,
        error: "Choose at least two unique freehand points before finishing.",
      };
    }
    return {
      state: { ...current, points: [] },
      completed: { kind: current.kind, points: current.points },
      error: null,
    };
  }
  if (!current.active) {
    return {
      state: current,
      completed: null,
      error: "Turn on drawing mode before choosing a point.",
    };
  }
  if (current.points.some((point) => samePoint(point, action.point))) {
    return {
      state: current,
      completed: null,
      error: "Choose a globally unique drawing point.",
    };
  }
  if (current.points.length >= 512) {
    return {
      state: current,
      completed: null,
      error: "A freehand path supports at most 512 points.",
    };
  }

  const points = [...current.points, action.point];
  const completeImmediately = current.kind === "text";
  const completePair = current.kind !== "freehand" && points.length === 2;
  if (completeImmediately || completePair) {
    return {
      state: { ...current, points: [] },
      completed: { kind: current.kind, points },
      error: null,
    };
  }
  return {
    state: { ...current, points },
    completed: null,
    error: null,
  };
}
