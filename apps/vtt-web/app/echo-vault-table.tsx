"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";

import {
  buildDeclarationCommand,
  buildStartCommand,
  getSessionView,
  postCommand,
  streamVttEvents,
  VttApiError,
  type ActorAction,
  type ActorProjection,
  type DisplayEvent,
  type EncounterOutcome,
  type EncounterProjection,
  type GridCell,
  type GridMovementPlan,
  type JsonValue,
  type Position3,
  type SquareGridScene,
  type VttCommandResponse,
  type VttPreviewResponse,
  type VttSessionView,
} from "./vtt-client";
import {
  EMPTY_GRID_MEASUREMENT,
  nextGridMeasurement,
  type GridMeasurement,
} from "./grid-ruler";
import {
  initialTurnSelection,
  selectedTargetIdsForChoice,
} from "./turn-choice-selection";
import {
  useVttAnnotations,
  type AnnotationConnectionStatus,
  type AnnotationMutationOperation,
} from "./use-vtt-annotations";
import { useVttScenes } from "./use-vtt-scenes";
import {
  useVttTokens,
  type TokenConnectionStatus,
} from "./use-vtt-tokens";
import {
  useVttVisibility,
  type VisibilityConnectionStatus,
} from "./use-vtt-visibility";
import {
  useVttMapAssets,
  useVttMapAssetUrl,
} from "./use-vtt-map-assets";
import {
  isDrawingAnnotation,
  isLockedDrawingAnnotation,
  type AnnotationPoint,
  type DrawingAnnotation,
  type PingAnnotation,
  type VttAnnotation,
} from "./vtt-annotations";
import {
  buildDrawingAnnotation,
  type DrawingKind,
} from "./vtt-drawings";
import { advanceDrawingDraft } from "./vtt-drawing-workflow";
import { VttDrawingLayer } from "./vtt-drawing-layer";
import type { SceneMapMetadata } from "./vtt-scenes";
import { selectActiveBoardPresentation } from "./vtt-active-board";
import {
  boardCellDistanceFeet,
  activateGridlessMeasurementPoint,
  boardCellToFeet,
  boardCellToPixel,
  enumerateBoardCells,
  feetToBoardCell,
  moveGridlessCursor,
  pixelDistanceFeet,
  pixelToBoardFeet,
  type BoardCalibration,
  type BoardCell,
  type BoardPoint,
  type GridlessMeasurementState,
} from "./vtt-board-calibration";
import {
  buildAreaTemplateAnnotation,
  projectAreaTemplateToGrid,
  type AreaTemplateAnnotation,
  type AreaTemplateGridGeometry,
  type AreaTemplateKind,
} from "./vtt-template-geometry";
import { VttChatPanel } from "./vtt-chat-panel";
import { VttJournalPanel } from "./vtt-journal-panel";
import { useVttPresentation } from "./use-vtt-presentation";
import { VttPresentationPanel } from "./vtt-presentation-panel";
import type { SharedCamera } from "./vtt-presentation";
import { VttCombatTrackerPanel } from "./vtt-combat-tracker-panel";
import {
  buildCombatControlCommand,
  type CombatControlPayload,
} from "./vtt-combat-tracker";
import { useVttJournal } from "./use-vtt-journal";
import type { JournalDocument } from "./vtt-journal";
import { VttPresencePanel } from "./vtt-presence-panel";
import { VttScenesPanel } from "./vtt-scenes-panel";
import { VttTokensPanel } from "./vtt-tokens-panel";
import { VttVisibilityPanel } from "./vtt-visibility-panel";
import { VttVisibilityMask } from "./vtt-visibility-mask";
import { VttRollCardArticle } from "./vtt-roll-card";
import { rollCardFromEvent } from "./vtt-roll-cards";
import type {
  VisibilityProjection,
  VisibilityProjectionSources,
} from "./vtt-visibility";
import type { TokenRecord } from "./vtt-tokens";
import { VttAccessGate } from "./vtt-access-gate";
import { VttShell, type VttShellPanel } from "./vtt-shell";
import {
  canControlActor,
  getTableView,
  type VttTableView,
} from "./vtt-access";

type PendingOperation = "start" | "preview" | "commit" | "combat" | null;

interface LoggedEvent {
  id: string;
  source: "preview" | "commit" | "stream";
  event: DisplayEvent;
}

interface PreviewState {
  fingerprint: string;
  response: VttPreviewResponse;
}

function appendUniqueEvents(
  current: LoggedEvent[],
  incoming: LoggedEvent[],
): LoggedEvent[] {
  const known = new Set(current.map((entry) => entry.id));
  const merged = [...current];
  for (const entry of incoming) {
    if (known.has(entry.id)) continue;
    known.add(entry.id);
    merged.push(entry);
  }
  return merged.slice(-80);
}

function titleCase(value: string): string {
  return value
    .replace(/^dnd\./, "")
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function phaseLabel(phase: EncounterProjection["phase"]): string {
  if (phase === "unstarted") return "Ready to begin";
  if (phase === "awaiting_declaration") return "Awaiting declaration";
  return "Encounter complete";
}

function annotationStatusLabel(
  status: AnnotationConnectionStatus,
  count: number,
  operation: AnnotationMutationOperation,
): string {
  if (operation === "placing") return "Saving shared annotation…";
  if (operation === "removing") return "Removing shared annotation…";
  if (operation === "clearing") return "Clearing local annotations…";
  if (status === "loading") return "Loading shared annotations…";
  if (status === "connecting") return "Connecting shared annotations…";
  if (status === "reconnecting") return "Shared annotations reconnecting…";
  if (status === "unavailable") return "Shared annotations unavailable";
  if (status === "error") return "Shared annotation sync interrupted";
  return `${count} shared ${count === 1 ? "annotation" : "annotations"} synced`;
}

function annotationLabel(annotation: VttAnnotation): string {
  const kind = titleCase(annotation.annotation_type.replace("_template", ""));
  const dimensions =
    isDrawingAnnotation(annotation)
      ? `${annotation.layer.replace("_", " ")} · ${annotation.locked ? "locked" : "editable"}`
      : annotation.annotation_type === "circle_template"
      ? `radius ${annotation.radius_ft} ft`
      : annotation.annotation_type === "cube_template"
        ? `${annotation.size_ft} ft side`
        : annotation.annotation_type === "line_template"
          ? `${annotation.width_ft} ft wide`
          : annotation.annotation_type === "cone_template"
            ? `${annotation.length_ft.toFixed(1)} ft · ${annotation.direction_degrees.toFixed(1)}° · ${annotation.angle_degrees}° arc`
            : annotation.annotation_type === "ping"
              ? `${annotation.duration_ms} ms pulse`
              : `${annotation.total_distance_ft} ft`;
  return `${kind} · ${dimensions} · ${annotation.author_id}`;
}

interface DrawingToolSettings {
  kind: DrawingKind;
  layer: DrawingAnnotation["layer"];
  audience: "all" | "self";
  strokeColor: string;
  fillColor: string;
  fillEnabled: boolean;
  opacity: number;
  strokeWidthFt: number;
  lineStyle: "solid" | "dashed";
  locked: boolean;
  text: string;
  fontSizeFt: number;
}

interface DrawingToolPresentation extends DrawingToolSettings {
  active: boolean;
  pointCount: number;
  error: string | null;
}

function settingsFromDrawing(
  annotation: DrawingAnnotation,
): DrawingToolSettings {
  const kind: DrawingKind =
    annotation.annotation_type === "freehand_drawing"
      ? "freehand"
      : annotation.annotation_type === "shape_drawing"
        ? annotation.shape
        : annotation.annotation_type === "arrow_drawing"
          ? "arrow"
          : "text";
  const optionalColor =
    annotation.annotation_type === "text_drawing"
      ? annotation.background_color ?? annotation.style.fill_color
      : annotation.style.fill_color;
  return {
    kind,
    layer: annotation.layer,
    audience: annotation.audience.length === 1 && annotation.audience[0] === "all"
      ? "all"
      : "self",
    strokeColor: annotation.style.stroke_color,
    fillColor: optionalColor ?? "#1d4ed8",
    fillEnabled: optionalColor !== null,
    opacity: annotation.style.opacity,
    strokeWidthFt: annotation.style.stroke_width_ft,
    lineStyle: annotation.style.line_style,
    locked: annotation.locked,
    text: annotation.annotation_type === "text_drawing"
      ? annotation.text
      : "Map note",
    fontSizeFt: annotation.annotation_type === "text_drawing"
      ? annotation.font_size_ft
      : 3,
  };
}

function templateControlLabel(kind: AreaTemplateKind): string {
  if (kind === "circle") return "Radius";
  if (kind === "cube") return "Side length";
  if (kind === "line") return "Width";
  return "Angle";
}

function templatePrompt(
  kind: AreaTemplateKind,
  start: GridCell | null,
): string {
  if (kind === "circle" || kind === "cube") {
    return `Template mode · choose the ${kind} center`;
  }
  if (start === null) {
    return `Template mode · choose ${kind === "line" ? "line start" : "cone origin"}`;
  }
  return `Start ${cellLabel(start)} · choose ${kind === "line" ? "line end" : "direction endpoint"}`;
}

function conePath(geometry: Extract<AreaTemplateGridGeometry, { kind: "cone" }>): string {
  return [
    `M ${geometry.originX} ${geometry.originY}`,
    `L ${geometry.startX} ${geometry.startY}`,
    `A ${geometry.radius} ${geometry.radius} 0 0 1 ${geometry.endX} ${geometry.endY}`,
    "Z",
  ].join(" ");
}

function outcomeCopy(outcome: EncounterOutcome | null): {
  eyebrow: string;
  title: string;
  body: string;
} {
  if (outcome === "party_victory") {
    return {
      eyebrow: "Vault secured",
      title: "The echo answers to Vela.",
      body: "The Hushglass Sentry is silent. The encounter is complete and the table is sealed at its final revision.",
    };
  }
  if (outcome === "enemy_victory") {
    return {
      eyebrow: "Party defeated",
      title: "The signal goes dark.",
      body: "The sentry holds the vault. Review the rules trace below, then reset the backend session to try another line.",
    };
  }
  return {
    eyebrow: "Time expired",
    title: "The vault closes unresolved.",
    body: "The final round elapsed without a victor. The terminal state remains available for review.",
  };
}

function rangeLabel(action: ActorAction): string {
  if (action.reach_ft !== null) return `${action.reach_ft} ft reach`;
  if (action.range_normal_ft !== null) {
    return action.range_long_ft === null
      ? `${action.range_normal_ft} ft range`
      : `${action.range_normal_ft}/${action.range_long_ft} ft`;
  }
  return titleCase(action.target_mode);
}

function selectionFingerprint(
  revision: number,
  actorId: string,
  actionName: string,
  targetIds: string[],
  movementPath: Position3[],
): string {
  return JSON.stringify([
    revision,
    actorId,
    actionName,
    targetIds,
    movementPath,
  ]);
}

function cellKey(cell: GridCell): string {
  return `${cell.column}:${cell.row}`;
}

function cellLabel(cell: GridCell): string {
  return `${String.fromCharCode(65 + cell.row)}${cell.column + 1}`;
}

function sameCell(left: GridCell | null, right: GridCell): boolean {
  return left?.column === right.column && left.row === right.row;
}

function presentedCalibration(
  metadata: SceneMapMetadata,
): BoardCalibration {
  return metadata.calibration;
}

function boardCellFromGrid(
  calibration: BoardCalibration,
  cell: GridCell,
): BoardCell {
  return calibration.topology.startsWith("hex_")
    ? { q: cell.column, r: cell.row }
    : cell;
}

function gridCellFromBoard(cell: BoardCell): GridCell {
  return "q" in cell
    ? { column: cell.q, row: cell.r }
    : cell;
}

function boardOriginFeet(
  scene: SquareGridScene,
  calibration: BoardCalibration,
): Position3 {
  const halfStep = calibration.distance_ft / 2;
  return [
    scene.origin_ft.x_ft + halfStep,
    scene.origin_ft.y_ft + halfStep,
    scene.origin_ft.z_ft,
  ];
}

function presentedFeetToCell(
  scene: SquareGridScene,
  calibration: BoardCalibration,
  position: Position3,
): GridCell {
  return gridCellFromBoard(
    feetToBoardCell(calibration, position, boardOriginFeet(scene, calibration)),
  );
}

function presentedCellToFeet(
  scene: SquareGridScene,
  calibration: BoardCalibration,
  cell: GridCell,
): Position3 {
  return boardCellToFeet(
    calibration,
    boardCellFromGrid(calibration, cell),
    boardOriginFeet(scene, calibration),
  );
}

function planPresentedMovement(input: {
  scene: SquareGridScene;
  calibration: BoardCalibration;
  start: Position3;
  destination: GridCell;
  movementRemaining: number;
}): GridMovementPlan {
  if (input.calibration.topology === "gridless") {
    throw new Error("gridless movement requires a free-position command surface");
  }
  const startCell = boardCellFromGrid(
    input.calibration,
    presentedFeetToCell(input.scene, input.calibration, input.start),
  );
  const destinationCell = boardCellFromGrid(
    input.calibration,
    input.destination,
  );
  const distanceFt = boardCellDistanceFeet(
    input.calibration,
    startCell,
    destinationCell,
  );
  if (distanceFt > input.movementRemaining + 1e-6) {
    throw new Error("Destination exceeds remaining movement");
  }
  const projected = presentedCellToFeet(
    input.scene,
    input.calibration,
    input.destination,
  );
  const end: Position3 = [projected[0], projected[1], input.start[2]];
  return {
    destination: input.destination,
    distanceFt,
    end,
    path: distanceFt <= 1e-6 ? [] : [[...input.start] as Position3, end],
  };
}

function presentedCells(
  metadata: SceneMapMetadata,
): GridCell[] {
  return enumerateBoardCells(
    metadata.calibration,
    metadata.width_px,
    metadata.height_px,
  ).map(gridCellFromBoard);
}

function squareTemplatesAreSupported(
  scene: SquareGridScene,
  metadata: SceneMapMetadata,
): boolean {
  const calibration = presentedCalibration(metadata);
  const widthPx = metadata.width_px;
  const heightPx = metadata.height_px;
  return calibration.topology === "square" &&
    calibration.origin_x_px === calibration.cell_extent_px / 2 &&
    calibration.origin_y_px === calibration.cell_extent_px / 2 &&
    calibration.distance_ft === scene.cell_size_ft &&
    widthPx === scene.columns * calibration.cell_extent_px &&
    heightPx === scene.rows * calibration.cell_extent_px;
}

function presentedCellStyle(
  calibration: BoardCalibration,
  cell: GridCell,
  widthPx: number,
  heightPx: number,
  includeExtent = true,
): CSSProperties {
  const center = boardCellToPixel(
    calibration,
    boardCellFromGrid(calibration, cell),
  );
  const cellWidthPx = calibration.topology === "hex_flat"
    ? 2 * calibration.cell_extent_px / Math.sqrt(3)
    : calibration.cell_extent_px;
  const cellHeightPx = calibration.topology === "hex_pointy"
    ? 2 * calibration.cell_extent_px / Math.sqrt(3)
    : calibration.cell_extent_px;
  return {
    left: `${center.x_px / widthPx * 100}%`,
    top: `${center.y_px / heightPx * 100}%`,
    ...(includeExtent
      ? {
          width: `${cellWidthPx / widthPx * 100}%`,
          height: `${cellHeightPx / heightPx * 100}%`,
        }
      : {}),
  };
}

function presentedFeetStyle(
  scene: SquareGridScene,
  calibration: BoardCalibration,
  position: Position3,
  widthPx: number,
  heightPx: number,
): CSSProperties {
  const origin = boardOriginFeet(scene, calibration);
  const xPx = calibration.origin_x_px +
    (position[0] - origin[0]) / calibration.distance_ft * calibration.cell_extent_px;
  const yPx = calibration.origin_y_px +
    (position[1] - origin[1]) / calibration.distance_ft * calibration.cell_extent_px;
  return {
    left: `${xPx / widthPx * 100}%`,
    top: `${yPx / heightPx * 100}%`,
  };
}

function isInteractiveControl(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(
    target.closest(
      "input, textarea, select, button, a[href], summary, [tabindex]:not([tabindex='-1']), [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='button'], [role='combobox']",
    ),
  );
}

function waitForEventReconnect(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = window.setTimeout(finish, 750);
    signal.addEventListener("abort", finish, { once: true });
  });
}

async function loadTableConnection(
  bearerToken: string | null,
): Promise<{ identity: VttTableView; view: VttSessionView }> {
  const identity = await getTableView({ bearerToken });
  const view = await getSessionView(undefined, bearerToken);
  return { identity, view };
}

function measurementStatus(
  calibration: BoardCalibration,
  measurement: GridMeasurement,
  measureMode: boolean,
): string {
  if (calibration.topology === "gridless") {
    return "Gridless calibrated scale · cell snapping disabled";
  }
  if (measurement.start === null) {
    return measureMode ? "Choose any start cell" : "Ruler ready";
  }
  if (measurement.end === null) {
    return measureMode
      ? `Start ${cellLabel(measurement.start)} · choose any end cell`
      : `Start ${cellLabel(measurement.start)} saved`;
  }
  const distance = boardCellDistanceFeet(
    calibration,
    boardCellFromGrid(calibration, measurement.start),
    boardCellFromGrid(calibration, measurement.end),
  );
  const resetHint = measureMode ? " · choose a cell to start again" : "";
  return `${cellLabel(measurement.start)} → ${cellLabel(measurement.end)} · ${distance} ft${resetHint}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof VttApiError) {
    if (error.code === "stale_revision") {
      return "The table advanced elsewhere. Refreshing the current revision will restore your controls.";
    }
    return error.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return "The table could not complete that operation.";
}

function eventSummary(event: DisplayEvent): string {
  const payload = event.payload;
  if (event.kind === "dnd.encounter.started") {
    const round = payload.round_number;
    const order = payload.initiative_order;
    return `Round ${String(round)} · ${Array.isArray(order) ? order.length : 0} combatants entered initiative.`;
  }
  if (event.kind === "dnd.turn.prepared") {
    return `${titleCase(String(payload.actor_id ?? "actor"))} is ready for a declaration.`;
  }
  if (event.kind === "dnd.turn.resolved") {
    const status = payload.status ?? payload.strategy_name ?? "resolved";
    return `${titleCase(String(payload.actor_id ?? "turn"))} · ${titleCase(String(status))}`;
  }
  if (event.kind === "dnd.encounter.completed") {
    return `${titleCase(String(payload.outcome ?? "complete"))} in round ${String(payload.round_number ?? "—")}.`;
  }
  const entries = Object.entries(payload).slice(0, 2);
  if (entries.length === 0) return "No public payload details.";
  return entries
    .map(([key, value]) => `${titleCase(key)}: ${compactValue(value)}`)
    .join(" · ");
}

function compactValue(value: JsonValue): string {
  if (value === null) return "none";
  if (Array.isArray(value)) return value.map(compactValue).join(", ");
  if (typeof value === "object") return "details recorded";
  return String(value);
}

function HealthBar({ actor }: { actor: ActorProjection }) {
  const percentage = Math.max(
    0,
    Math.min(100, (actor.hp / Math.max(actor.max_hp, 1)) * 100),
  );
  return (
    <div
      className="health-track"
      role="progressbar"
      aria-label={`${actor.name} hit points`}
      aria-valuemin={0}
      aria-valuemax={actor.max_hp}
      aria-valuenow={actor.hp}
    >
      <span style={{ width: `${percentage}%` }} />
    </div>
  );
}

function InstrumentMark() {
  return (
    <span className="instrument-mark" aria-hidden="true">
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

function LoadingView() {
  return (
    <main className="state-screen state-screen-loading">
      <div className="state-card" role="status" aria-live="polite">
        <InstrumentMark />
        <p className="eyebrow">Standalone tabletop</p>
        <h1>Joining the active table</h1>
        <p>Reading your authorized table projection and calibrating the board.</p>
        <div className="signal-line" aria-hidden="true">
          <span />
        </div>
      </div>
    </main>
  );
}

function ErrorView({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <main className="state-screen">
      <div className="state-card state-card-error" role="alert">
        <span className="error-glyph" aria-hidden="true">
          !
        </span>
        <p className="eyebrow">Connection interrupted</p>
        <h1>The table could not synchronize.</h1>
        <p>{message}</p>
        <button className="button button-primary" type="button" onClick={onRetry}>
          Retry connection
        </button>
      </div>
    </main>
  );
}

function InitiativePanel({
  projection,
  selectedActorId,
  onSelect,
  versions,
  canManage,
  pending,
  error,
  onCombatControl,
}: {
  projection: EncounterProjection;
  selectedActorId: string;
  onSelect: (actorId: string) => void;
  versions: VttSessionView["versions"];
  canManage: boolean;
  pending: boolean;
  error: string | null;
  onCombatControl: (payload: CombatControlPayload) => Promise<void>;
}) {
  return (
    <aside className="panel initiative-panel" aria-labelledby="initiative-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Turn sequence</p>
          <h2 id="initiative-title">Initiative</h2>
        </div>
        <span className="round-badge">R{projection.round_number}</span>
      </div>

      <ol className="initiative-list">
        {projection.initiative_order.map((actorId, index) => {
          const actor = projection.actors[actorId];
          const active = actorId === projection.active_actor_id;
          const selected = actorId === selectedActorId;
          return (
            <li key={actorId}>
              <button
                type="button"
                className={`initiative-entry ${active ? "is-active" : ""} ${selected ? "is-selected" : ""}`}
                onClick={() => onSelect(actorId)}
                aria-current={active ? "step" : undefined}
                aria-pressed={selected}
              >
                <span className="initiative-index">{String(index + 1).padStart(2, "0")}</span>
                <span className={`mini-token team-${actor.team}`}>
                  {initials(actor.name)}
                </span>
                <span className="initiative-copy">
                  <strong>{actor.name}</strong>
                  <span>
                    {actor.dead ? "Defeated" : `${actor.hp}/${actor.max_hp} HP`}
                  </span>
                </span>
                {active ? <span className="active-pip" aria-label="Active turn" /> : null}
              </button>
              <HealthBar actor={actor} />
            </li>
          );
        })}
      </ol>

      <VttCombatTrackerPanel
        key={[
          projection.round_number,
          projection.active_actor_id ?? "none",
          projection.initiative_order.join("|"),
        ].join(":")}
        projection={projection}
        canManage={canManage}
        pending={pending}
        error={error}
        onControl={onCombatControl}
      />

      <div className="round-meter" aria-label={`Round ${projection.round_number} of ${projection.max_rounds}`}>
        <span>
          Round {projection.round_number} / {projection.max_rounds}
        </span>
        <div className="meter-dots" aria-hidden="true">
          {Array.from({ length: projection.max_rounds }, (_, index) => (
            <i
              key={index}
              className={index < projection.round_number ? "is-lit" : ""}
            />
          ))}
        </div>
      </div>

      <div className="version-stack">
        <span>Rules pin</span>
        <code title={versions.rules}>{versions.rules.split("@")[1] ?? versions.rules}</code>
        <span>Content pin</span>
        <code title={versions.content}>{versions.content.split("@")[1] ?? versions.content}</code>
      </div>
    </aside>
  );
}

export function TacticalMap({
  scene,
  mapMetadata,
  mapUrl,
  mapLoadError,
  projection,
  tokens,
  tokenStatus,
  tokenError,
  visibilityProjection,
  visibilitySources,
  visibilityStatus,
  visibilityError,
  showVisibilityMask,
  selectedActorId,
  selectableTargetIds,
  selectedTargetId,
  reachableCells,
  movementPlan,
  measureMode,
  measurement,
  pingMode,
  templateMode,
  templateKind,
  templateStart,
  templateDimensionFt,
  templateAngleDegrees,
  pings,
  templates,
  drawings,
  journalDocuments,
  onJournalDocumentSelect,
  sharedCamera,
  followSharedCamera,
  drawingTool,
  annotations,
  selectedAnnotationId,
  annotationStatus,
  annotationError,
  annotationOperation,
  annotationCanMutate,
  annotationCanManage,
  currentParticipantId,
  templatePlacementError,
  onTokenSelect,
  onTargetSelect,
  onCellSelect,
  onGridlessPointSelect,
  onMeasureToggle,
  onMeasureClear,
  onPingToggle,
  onTemplateToggle,
  onTemplateKindChange,
  onTemplateDimensionChange,
  onTemplateAngleChange,
  onTemplateCancelStart,
  onDrawingToggle,
  onDrawingSettingsChange,
  onDrawingFinish,
  onDrawingCancel,
  onUpdateSelectedDrawing,
  onUnlockSelectedDrawing,
  onAnnotationSelect,
  onRemoveSelected,
  onClearLocal,
  onAnnotationRetry,
}: {
  scene: SquareGridScene;
  mapMetadata: SceneMapMetadata;
  mapUrl: string | null;
  mapLoadError: string | null;
  projection: EncounterProjection;
  tokens: TokenRecord[];
  tokenStatus: TokenConnectionStatus;
  tokenError: string | null;
  visibilityProjection: VisibilityProjection | null;
  visibilitySources: VisibilityProjectionSources;
  visibilityStatus: VisibilityConnectionStatus;
  visibilityError: string | null;
  showVisibilityMask: boolean;
  selectedActorId: string;
  selectableTargetIds: Set<string>;
  selectedTargetId: string | null;
  reachableCells: Set<string>;
  movementPlan: GridMovementPlan | null;
  measureMode: boolean;
  measurement: GridMeasurement;
  pingMode: boolean;
  templateMode: boolean;
  templateKind: AreaTemplateKind;
  templateStart: GridCell | null;
  templateDimensionFt: number;
  templateAngleDegrees: number;
  pings: PingAnnotation[];
  templates: AreaTemplateAnnotation[];
  drawings: DrawingAnnotation[];
  journalDocuments: JournalDocument[];
  onJournalDocumentSelect: (documentId: string) => void;
  sharedCamera: SharedCamera | null;
  followSharedCamera: boolean;
  drawingTool: DrawingToolPresentation;
  annotations: VttAnnotation[];
  selectedAnnotationId: string;
  annotationStatus: AnnotationConnectionStatus;
  annotationError: string | null;
  annotationOperation: AnnotationMutationOperation;
  annotationCanMutate: boolean;
  annotationCanManage: (authorId: string) => boolean;
  currentParticipantId: string;
  templatePlacementError: string | null;
  onTokenSelect: (actorId: string) => void;
  onTargetSelect: (actorId: string) => void;
  onCellSelect: (cell: GridCell) => void;
  onGridlessPointSelect: (position: Position3) => void;
  onMeasureToggle: () => void;
  onMeasureClear: () => void;
  onPingToggle: () => void;
  onTemplateToggle: () => void;
  onTemplateKindChange: (kind: AreaTemplateKind) => void;
  onTemplateDimensionChange: (value: number) => void;
  onTemplateAngleChange: (value: number) => void;
  onTemplateCancelStart: () => void;
  onDrawingToggle: () => void;
  onDrawingSettingsChange: (settings: Partial<DrawingToolSettings>) => void;
  onDrawingFinish: () => void;
  onDrawingCancel: () => void;
  onUpdateSelectedDrawing: () => void;
  onUnlockSelectedDrawing: () => void;
  onAnnotationSelect: (annotationId: string) => void;
  onRemoveSelected: () => void;
  onClearLocal: () => void;
  onAnnotationRetry: () => void;
}) {
  const [gridlessMeasurement, setGridlessMeasurement] =
    useState<GridlessMeasurementState | null>(null);
  const [gridlessCursor, setGridlessCursor] = useState<{
    calibrationKey: string;
    point: BoardPoint;
  } | null>(null);
  const mapAsset = mapMetadata.asset ?? null;
  const calibration = presentedCalibration(mapMetadata);
  const mapWidthPx = mapMetadata.width_px;
  const mapHeightPx = mapMetadata.height_px;
  const cameraZoom = followSharedCamera && sharedCamera?.enabled ? sharedCamera.zoom : null;
  const cameraXPercent = cameraZoom && sharedCamera && sharedCamera.center_x_ft !== null
    ? (calibration.origin_x_px + ((sharedCamera.center_x_ft - scene.origin_ft.x_ft) / calibration.distance_ft) * calibration.cell_extent_px) / mapWidthPx * 100
    : null;
  const cameraYPercent = cameraZoom && sharedCamera && sharedCamera.center_y_ft !== null
    ? (calibration.origin_y_px + ((sharedCamera.center_y_ft - scene.origin_ft.y_ft) / calibration.distance_ft) * calibration.cell_extent_px) / mapHeightPx * 100
    : null;
  const mapStyle = {
    aspectRatio: `${mapWidthPx} / ${mapHeightPx}`,
    backgroundImage: mapUrl ? `url(${JSON.stringify(mapUrl)})` : undefined,
    backgroundPosition: "center",
    backgroundRepeat: "no-repeat",
    backgroundSize: "100% 100%",
    transform: cameraZoom && cameraXPercent !== null && cameraYPercent !== null
      ? `translate(${50 - cameraXPercent * cameraZoom}%, ${50 - cameraYPercent * cameraZoom}%) scale(${cameraZoom})`
      : undefined,
    transformOrigin: cameraZoom ? "top left" : undefined,
  } as CSSProperties;
  let cells: GridCell[] = [];
  let cellPresentationError: string | null = null;
  try {
    cells = presentedCells(mapMetadata);
  } catch (error) {
    cellPresentationError = errorMessage(error);
  }
  const squareTemplatesSupported = squareTemplatesAreSupported(scene, mapMetadata);
  const calibrationKey = JSON.stringify(calibration);
  const currentGridlessCursor = gridlessCursor?.calibrationKey === calibrationKey
    ? gridlessCursor.point
    : {
        x_px: calibration.origin_x_px,
        y_px: calibration.origin_y_px,
      };
  const currentGridlessMeasurement =
    gridlessMeasurement?.calibrationKey === calibrationKey
      ? gridlessMeasurement
      : null;
  const measurePrompt = calibration.topology === "gridless"
    ? currentGridlessMeasurement?.end
      ? `Gridless ruler · ${pixelDistanceFeet(
          calibration,
          currentGridlessMeasurement.start,
          currentGridlessMeasurement.end,
        ).toFixed(1)} ft${measureMode ? " · choose a point to start again" : ""}`
      : currentGridlessMeasurement
        ? "Gridless ruler · choose an end point"
        : measureMode
          ? "Gridless ruler · choose a start point"
          : "Gridless calibrated scale · ruler ready"
    : measurementStatus(calibration, measurement, measureMode);
  const renderedPings = pings.flatMap((ping) => {
    try {
      const position: Position3 = [
        ping.position.x_ft,
        ping.position.y_ft,
        ping.position.z_ft,
      ];
      return [{
        ping,
        cell: calibration.topology === "gridless"
          ? null
          : presentedFeetToCell(scene, calibration, position),
        style: presentedFeetStyle(
          scene,
          calibration,
          position,
          mapWidthPx,
          mapHeightPx,
        ),
      }];
    } catch {
      return [];
    }
  });
  const renderedJournalPins = journalDocuments.flatMap((document) => {
    const pin = document.map_pin;
    if (pin === null || pin.scene_id !== scene.scene_id) return [];
    try {
      return [{
        document,
        style: presentedFeetStyle(
          scene,
          calibration,
          [pin.position.x_ft, pin.position.y_ft, pin.position.z_ft],
          mapWidthPx,
          mapHeightPx,
        ),
      }];
    } catch {
      return [];
    }
  });
  const renderedTemplates = squareTemplatesSupported ? templates.flatMap((template) => {
    try {
      return [{ template, geometry: projectAreaTemplateToGrid(scene, template) }];
    } catch {
      return [];
    }
  }) : [];
  const drawingOriginFeet = boardOriginFeet(scene, calibration);
  const selectedAnnotation = annotations.find(
    (annotation) => annotation.annotation_id === selectedAnnotationId,
  );
  const selectedCanManage = Boolean(
    selectedAnnotation && annotationCanManage(selectedAnnotation.author_id),
  );
  const selectedIsLocked = Boolean(
    selectedAnnotation && isLockedDrawingAnnotation(selectedAnnotation),
  );
  const unlockedOwnedAnnotationCount = annotations.filter(
    (annotation) =>
      annotation.author_id === currentParticipantId &&
      !isLockedDrawingAnnotation(annotation),
  ).length;
  const authoritativeTokens = tokens.flatMap((token) => {
    try {
      const position: Position3 = [
        token.pose.position_ft.x_ft,
        token.pose.position_ft.y_ft,
        token.pose.position_ft.z_ft,
      ];
      const cell = calibration.topology === "gridless"
        ? null
        : presentedFeetToCell(scene, calibration, position);
      return [{
        token,
        actor: token.actor_id ? projection.actors[token.actor_id] : undefined,
        cell,
        style: presentedFeetStyle(
          scene,
          calibration,
          position,
          mapWidthPx,
          mapHeightPx,
        ),
      }];
    } catch {
      return [];
    }
  });
  const activateGridlessPoint = (point: BoardPoint) => {
    if (measureMode) {
      setGridlessMeasurement((current) =>
        activateGridlessMeasurementPoint(current, calibrationKey, point),
      );
      return;
    }
    onGridlessPointSelect(
      pixelToBoardFeet(
        calibration,
        point,
        boardOriginFeet(scene, calibration),
      ),
    );
  };
  const handleGridlessBoardClick = (
    event: ReactMouseEvent<HTMLDivElement>,
  ) => {
    if (
      calibration.topology !== "gridless" ||
      (!measureMode && !pingMode && !drawingTool.active) ||
      (event.target instanceof Element && event.target.closest("button"))
    ) {
      return;
    }
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    const point: BoardPoint = {
      x_px: Math.min(
        mapWidthPx,
        Math.max(0, (event.clientX - bounds.left) / bounds.width * mapWidthPx),
      ),
      y_px: Math.min(
        mapHeightPx,
        Math.max(0, (event.clientY - bounds.top) / bounds.height * mapHeightPx),
      ),
    };
    setGridlessCursor({ calibrationKey, point });
    activateGridlessPoint(point);
  };
  const handleGridlessBoardKeyDown = (
    event: ReactKeyboardEvent<HTMLDivElement>,
  ) => {
    if (calibration.topology !== "gridless") return;
    if (
      event.key === "ArrowLeft" ||
      event.key === "ArrowRight" ||
      event.key === "ArrowUp" ||
      event.key === "ArrowDown"
    ) {
      event.preventDefault();
      event.stopPropagation();
      const point = moveGridlessCursor(
        currentGridlessCursor,
        event.key,
        mapWidthPx,
        mapHeightPx,
        event.shiftKey ? 10 : 1,
      );
      setGridlessCursor({ calibrationKey, point });
      return;
    }
    if (
      (event.key === "Enter" || event.key === " ") &&
      (measureMode || pingMode || drawingTool.active)
    ) {
      event.preventDefault();
      event.stopPropagation();
      activateGridlessPoint(currentGridlessCursor);
    }
  };

  return (
    <section className="map-panel" aria-labelledby="map-title">
      <div className="map-toolbar">
        <div>
          <p className="eyebrow">Tactical surface</p>
          <h2 id="map-title">{mapMetadata?.name ?? scene.name}</h2>
        </div>
        <div className="map-toolbar-tools">
          <div className="map-readouts" aria-label="Map measurements">
            <span>{mapWidthPx} × {mapHeightPx}px</span>
            <span>{calibration.topology.replace("_", "-")}</span>
            <span>{calibration.distance_ft} ft / step</span>
            <span>Z 0</span>
          </div>
          <div className="measure-controls" role="group" aria-label="Map tools">
            <button
              type="button"
              className={`measure-toggle ${measureMode ? "is-active" : ""}`}
              aria-pressed={measureMode}
              aria-keyshortcuts="M"
              aria-controls="echo-vault-grid"
              onClick={onMeasureToggle}
            >
              <span aria-hidden="true">↗</span>
              Measure
              <kbd>M</kbd>
            </button>
            <button
              type="button"
              className="measure-clear"
              disabled={
                calibration.topology === "gridless"
                  ? currentGridlessMeasurement === null
                  : measurement.start === null
              }
              onClick={() => {
                onMeasureClear();
                setGridlessMeasurement(null);
              }}
            >
              Clear measure
            </button>
            <button
              type="button"
              className={`ping-toggle ${pingMode ? "is-active" : ""}`}
              aria-pressed={pingMode}
              aria-keyshortcuts="P"
              aria-controls="echo-vault-grid"
              disabled={!annotationCanMutate}
              onClick={onPingToggle}
            >
              <span aria-hidden="true">◎</span>
              Ping
              <kbd>P</kbd>
            </button>
            <button
              type="button"
              className={`template-toggle ${templateMode ? "is-active" : ""}`}
              aria-pressed={templateMode}
              aria-keyshortcuts="T"
              aria-controls="echo-vault-grid template-controls"
              disabled={!annotationCanMutate || !squareTemplatesSupported}
              onClick={onTemplateToggle}
            >
              <span aria-hidden="true">◇</span>
              Template
              <kbd>T</kbd>
            </button>
            <button
              type="button"
              className={`drawing-toggle ${drawingTool.active ? "is-active" : ""}`}
              aria-pressed={drawingTool.active}
              aria-keyshortcuts="D"
              aria-controls="echo-vault-grid drawing-controls"
              disabled={!annotationCanMutate}
              onClick={onDrawingToggle}
            >
              <span aria-hidden="true">✎</span>
              Draw
              <kbd>D</kbd>
            </button>
          </div>
          {templateMode ? (
            <fieldset className="template-controls" id="template-controls">
              <legend>Shared area template</legend>
              <label>
                Shape
                <select
                  value={templateKind}
                  onChange={(event) =>
                    onTemplateKindChange(event.target.value as AreaTemplateKind)
                  }
                >
                  <option value="circle">Circle</option>
                  <option value="cone">Cone</option>
                  <option value="line">Line</option>
                  <option value="cube">Cube</option>
                </select>
              </label>
              <label>
                {templateControlLabel(templateKind)}
                <span className="template-number-control">
                  <input
                    type="number"
                    min={templateKind === "cone" ? 1 : 0.1}
                    max={templateKind === "cone" ? 180 : 100000}
                    step={templateKind === "cone" ? 1 : 0.5}
                    value={
                      templateKind === "cone"
                        ? templateAngleDegrees
                        : templateDimensionFt
                    }
                    onChange={(event) => {
                      const value = Number(event.target.value);
                      if (templateKind === "cone") onTemplateAngleChange(value);
                      else onTemplateDimensionChange(value);
                    }}
                  />
                  <span>{templateKind === "cone" ? "°" : "ft"}</span>
                </span>
              </label>
              {templateStart ? (
                <button type="button" onClick={onTemplateCancelStart}>
                  Cancel {templateKind === "line" ? "start" : "origin"}
                </button>
              ) : null}
              <small>
                {templateKind === "cone"
                  ? "The second cell sets cone length and world-space direction."
                  : templateKind === "line"
                    ? "Choose two cell centers; width stays in feet."
                    : "Choose one cell center; dimensions stay in feet."}
              </small>
            </fieldset>
          ) : null}
          {drawingTool.active ? (
            <fieldset className="drawing-controls" id="drawing-controls">
              <legend>Shared drawing</legend>
              <label>
                Type
                <select
                  value={drawingTool.kind}
                  onChange={(event) =>
                    onDrawingSettingsChange({ kind: event.target.value as DrawingKind })
                  }
                >
                  <option value="freehand">Freehand path</option>
                  <option value="rectangle">Rectangle</option>
                  <option value="ellipse">Ellipse</option>
                  <option value="arrow">Arrow</option>
                  <option value="text">Text label</option>
                </select>
              </label>
              <label>
                Layer
                <select
                  value={drawingTool.layer}
                  onChange={(event) =>
                    onDrawingSettingsChange({
                      layer: event.target.value as DrawingAnnotation["layer"],
                    })
                  }
                >
                  <option value="under_tokens">Under tokens</option>
                  <option value="over_tokens">Over tokens</option>
                </select>
              </label>
              <label>
                Audience
                <select
                  value={drawingTool.audience}
                  onChange={(event) =>
                    onDrawingSettingsChange({
                      audience: event.target.value as "all" | "self",
                    })
                  }
                >
                  <option value="all">Everyone</option>
                  <option value="self">Only me</option>
                </select>
              </label>
              <label>
                Stroke
                <input
                  type="color"
                  value={drawingTool.strokeColor}
                  onChange={(event) =>
                    onDrawingSettingsChange({ strokeColor: event.target.value })
                  }
                />
              </label>
              <label className="drawing-check">
                <input
                  type="checkbox"
                  checked={drawingTool.fillEnabled}
                  onChange={(event) =>
                    onDrawingSettingsChange({ fillEnabled: event.target.checked })
                  }
                />
                Fill
              </label>
              <label>
                Fill color
                <input
                  type="color"
                  value={drawingTool.fillColor}
                  disabled={!drawingTool.fillEnabled}
                  onChange={(event) =>
                    onDrawingSettingsChange({ fillColor: event.target.value })
                  }
                />
              </label>
              <label>
                Opacity
                <input
                  type="number"
                  min="0.05"
                  max="1"
                  step="0.05"
                  value={drawingTool.opacity}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    if (Number.isFinite(value)) onDrawingSettingsChange({ opacity: value });
                  }}
                />
              </label>
              <label>
                Width (ft)
                <input
                  type="number"
                  min="0.1"
                  max="1000"
                  step="0.1"
                  value={drawingTool.strokeWidthFt}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    if (Number.isFinite(value)) onDrawingSettingsChange({ strokeWidthFt: value });
                  }}
                />
              </label>
              <label>
                Line
                <select
                  value={drawingTool.lineStyle}
                  onChange={(event) =>
                    onDrawingSettingsChange({
                      lineStyle: event.target.value as "solid" | "dashed",
                    })
                  }
                >
                  <option value="solid">Solid</option>
                  <option value="dashed">Dashed</option>
                </select>
              </label>
              <label className="drawing-check">
                <input
                  type="checkbox"
                  checked={drawingTool.locked}
                  onChange={(event) =>
                    onDrawingSettingsChange({ locked: event.target.checked })
                  }
                />
                Lock after save
              </label>
              {drawingTool.kind === "text" ? (
                <>
                  <label className="drawing-text-control">
                    Plain text
                    <textarea
                      maxLength={500}
                      value={drawingTool.text}
                      onChange={(event) =>
                        onDrawingSettingsChange({ text: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Font (ft)
                    <input
                      type="number"
                      min="0.1"
                      max="1000"
                      step="0.1"
                      value={drawingTool.fontSizeFt}
                      onChange={(event) => {
                        const value = Number(event.target.value);
                        if (Number.isFinite(value)) onDrawingSettingsChange({ fontSizeFt: value });
                      }}
                    />
                  </label>
                </>
              ) : null}
              {drawingTool.kind === "freehand" ? (
                <button
                  type="button"
                  disabled={drawingTool.pointCount < 2}
                  onClick={onDrawingFinish}
                >
                  Finish path ({drawingTool.pointCount})
                </button>
              ) : null}
              {drawingTool.pointCount > 0 ? (
                <button type="button" onClick={onDrawingCancel}>
                  Cancel points
                </button>
              ) : null}
              <small>
                {drawingTool.kind === "text"
                  ? "Choose one map position. Text is stored and rendered as inert plain text."
                  : drawingTool.kind === "freehand"
                    ? "Choose two or more map positions, then finish the path."
                    : "Choose a start and end position."}
              </small>
            </fieldset>
          ) : null}
          <output className="measure-output" aria-live="polite">
            {drawingTool.active
              ? `Drawing ${drawingTool.kind} · ${drawingTool.pointCount} point${drawingTool.pointCount === 1 ? "" : "s"} selected`
              : templateMode
              ? templatePrompt(templateKind, templateStart)
              : pingMode
              ? "Ping mode · choose any map cell"
              : measurePrompt}
          </output>
          {calibration.topology === "gridless" ? (
            <p id="gridless-keyboard-instructions" className="board-tool-note" role="status" aria-live="polite">
              Focus the map, move the free cursor with arrow keys (Shift moves 10 px),
              then press Enter or Space to {measureMode ? "set the ruler point" : pingMode ? "place the ping" : drawingTool.active ? "add a drawing point" : "activate the selected map tool"}.
              {` Cursor ${currentGridlessCursor.x_px.toFixed(1)}, ${currentGridlessCursor.y_px.toFixed(1)} px.`}
            </p>
          ) : null}
          {mapLoadError ? (
            <p className="annotation-error" role="alert">{mapLoadError}</p>
          ) : null}
          {cellPresentationError ? (
            <p className="annotation-error" role="alert">
              Board calibration cannot be presented: {cellPresentationError}
            </p>
          ) : null}
          {!squareTemplatesSupported && calibration.topology !== "gridless" ? (
            <p className="board-tool-note" role="status">
              Shared area templates remain square-board tools; hex movement, tokens,
              pings, and measurement use the calibrated axial lattice.
            </p>
          ) : null}
          {tokenStatus !== "live" ? (
            <p className={`token-board-state token-board-state-${tokenStatus}`} role="status">
              {tokenError ??
                (tokenStatus === "loading"
                  ? "Loading authoritative token projection…"
                  : tokenStatus === "connecting"
                    ? "Connecting authoritative token projection…"
                    : tokenStatus === "reconnecting"
                      ? "Authoritative tokens reconnecting…"
                      : "Authoritative token projection unavailable.")}
            </p>
          ) : null}
          <div className="annotation-sync-state" role="status" aria-live="polite">
            <span className={`annotation-sync-dot annotation-${annotationStatus}`} aria-hidden="true" />
            <span>
              {annotationStatusLabel(
                annotationStatus,
                annotations.length,
                annotationOperation,
              )}
            </span>
            {annotationStatus === "error" || annotationStatus === "unavailable" ? (
              <button type="button" onClick={onAnnotationRetry}>Retry</button>
            ) : null}
          </div>
          <div className="annotation-manager">
            <label>
              Persisted annotation
              <select
                value={selectedAnnotationId}
                disabled={annotations.length === 0}
                onChange={(event) => onAnnotationSelect(event.target.value)}
              >
                {annotations.length === 0 ? (
                  <option value="">No annotations</option>
                ) : (
                  annotations.map((annotation) => (
                    <option
                      value={annotation.annotation_id}
                      key={annotation.annotation_id}
                    >
                      {annotationLabel(annotation)}
                    </option>
                  ))
                )}
              </select>
            </label>
            <button
              type="button"
              disabled={
                !selectedCanManage || selectedIsLocked || !annotationCanMutate
              }
              onClick={onRemoveSelected}
            >
              Remove selected
            </button>
            <button
              type="button"
              disabled={
                !drawingTool.active ||
                !selectedCanManage ||
                !selectedAnnotation ||
                !isDrawingAnnotation(selectedAnnotation) ||
                selectedIsLocked ||
                !annotationCanMutate
              }
              onClick={onUpdateSelectedDrawing}
            >
              Update selected drawing
            </button>
            {selectedIsLocked && selectedCanManage ? (
              <button
                type="button"
                disabled={!annotationCanMutate}
                onClick={onUnlockSelectedDrawing}
              >
                Unlock selected drawing
              </button>
            ) : null}
            <button
              type="button"
              disabled={
                unlockedOwnedAnnotationCount === 0 || !annotationCanMutate
              }
              onClick={onClearLocal}
            >
              Clear mine ({unlockedOwnedAnnotationCount})
            </button>
          </div>
          {selectedAnnotation && !selectedCanManage ? (
            <p className="annotation-owner-note">
              This marker belongs to {selectedAnnotation.author_id}; removal is disabled.
            </p>
          ) : null}
          {templatePlacementError ? (
            <p className="annotation-error" role="alert">{templatePlacementError}</p>
          ) : null}
          {drawingTool.error ? (
            <p className="annotation-error" role="alert">{drawingTool.error}</p>
          ) : null}
          {annotationError ? (
            <p className="annotation-error" role="alert">{annotationError}</p>
          ) : null}
        </div>
      </div>

      <div className="map-frame">
        <div className="map-corner map-corner-nw" aria-hidden="true" />
        <div className="map-corner map-corner-ne" aria-hidden="true" />
        <div className="map-corner map-corner-sw" aria-hidden="true" />
        <div className="map-corner map-corner-se" aria-hidden="true" />
        <div className="vault-sigil" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
        <div
          id="echo-vault-grid"
          className={`square-grid calibrated-board topology-${calibration.topology}`}
          style={mapStyle}
          role={calibration.topology === "gridless" ? "application" : "grid"}
          tabIndex={calibration.topology === "gridless" ? 0 : undefined}
          aria-describedby={calibration.topology === "gridless" ? "gridless-keyboard-instructions" : undefined}
          data-map-asset-id={mapAsset?.asset_id}
          data-board-topology={calibration.topology}
          onClick={handleGridlessBoardClick}
          onKeyDown={handleGridlessBoardKeyDown}
          aria-label={`${mapMetadata?.name ?? scene.name}, calibrated ${calibration.topology.replace("_", "-")} board${mapAsset ? `. ${mapAsset.alt_text}` : ""}`}
        >
          {calibration.topology === "gridless" ? (
            <span
              className="gridless-keyboard-cursor"
              style={{
                left: `${currentGridlessCursor.x_px / mapWidthPx * 100}%`,
                top: `${currentGridlessCursor.y_px / mapHeightPx * 100}%`,
              }}
              aria-hidden="true"
            />
          ) : null}
          <VttDrawingLayer
            drawings={drawings}
            layer="under_tokens"
            calibration={calibration}
            originFeet={drawingOriginFeet}
            widthPx={mapWidthPx}
            heightPx={mapHeightPx}
            selectedAnnotationId={selectedAnnotationId}
          />
          {cells.map((cell) => {
            const { column, row } = cell;
            const reachable = reachableCells.has(cellKey(cell));
            const selected =
              movementPlan?.destination.column === column &&
              movementPlan.destination.row === row;
            const measureStart = sameCell(measurement.start, cell);
            const measureEnd = sameCell(measurement.end, cell);
            const isTemplateStart = sameCell(templateStart, cell);
            const measureAction =
              measurement.start !== null && measurement.end === null
                ? "select measure end"
                : "select measure start";
            const pingAction = pingMode ? ", place shared ping" : "";
            const templateAction = templateMode
              ? `, ${templatePrompt(templateKind, templateStart).toLowerCase()}`
              : "";
            const drawingAction = drawingTool.active
              ? ", add shared drawing point"
              : "";
            return (
              <button
                type="button"
                className={`grid-cell ${reachable ? "is-reachable" : ""} ${selected ? "is-destination" : ""} ${measureMode ? "is-measuring" : ""} ${pingMode ? "is-pinging" : ""} ${templateMode ? "is-templating" : ""} ${drawingTool.active ? "is-drawing" : ""} ${isTemplateStart ? "is-template-start" : ""} ${measureStart ? "is-measure-start" : ""} ${measureEnd ? "is-measure-end" : ""}`}
                style={presentedCellStyle(
                  calibration,
                  cell,
                  mapWidthPx,
                  mapHeightPx,
                )}
                role="gridcell"
                aria-label={`Cell ${cellLabel(cell)}${reachable ? ", reachable destination" : ", not a reachable destination"}${selected ? ", selected destination" : ""}${measureStart ? ", measure start" : ""}${measureEnd ? ", measure end" : ""}${isTemplateStart ? ", template start" : ""}${measureMode ? `, ${measureAction}` : ""}${pingAction}${templateAction}${drawingAction}`}
                aria-selected={selected}
                disabled={!drawingTool.active && !templateMode && !pingMode && !measureMode && !reachable}
                onClick={() => onCellSelect(cell)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  event.stopPropagation();
                  onCellSelect(cell);
                }}
                key={cellKey(cell)}
              >
                <span className="grid-coordinate" aria-hidden="true">
                  {calibration.topology.startsWith("hex_")
                    ? `${column},${row}`
                    : cellLabel(cell)}
                </span>
              </button>
            );
          })}

          {renderedTemplates.length > 0 ? (
            <svg
              className="template-overlay"
              viewBox={`0 0 ${scene.columns} ${scene.rows}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              {renderedTemplates.map(({ template, geometry }) => {
                const className = `template-shape template-${geometry.kind} ${template.annotation_id === selectedAnnotationId ? "is-selected" : ""}`;
                if (geometry.kind === "circle") {
                  return (
                    <circle
                      className={className}
                      cx={geometry.centerX}
                      cy={geometry.centerY}
                      r={geometry.radius}
                      key={template.annotation_id}
                    />
                  );
                }
                if (geometry.kind === "cube") {
                  return (
                    <rect
                      className={className}
                      x={geometry.x}
                      y={geometry.y}
                      width={geometry.width}
                      height={geometry.height}
                      key={template.annotation_id}
                    />
                  );
                }
                if (geometry.kind === "line") {
                  return (
                    <line
                      className={className}
                      x1={geometry.startX}
                      y1={geometry.startY}
                      x2={geometry.endX}
                      y2={geometry.endY}
                      strokeWidth={geometry.width}
                      key={template.annotation_id}
                    />
                  );
                }
                return (
                  <path
                    className={className}
                    d={conePath(geometry)}
                    key={template.annotation_id}
                  />
                );
              })}
            </svg>
          ) : null}

          {renderedPings.map(({ ping, cell, style }) => (
            <span
              className="ping-marker"
              style={{
                ...style,
                "--ping-duration": `${ping.duration_ms}ms`,
              } as CSSProperties}
              role="img"
              aria-label={`Shared ping by ${ping.author_id}${cell ? ` at cell ${cellLabel(cell)}` : " on the calibrated gridless board"}`}
              key={ping.annotation_id}
            >
              <i aria-hidden="true" />
              <i aria-hidden="true" />
              <b aria-hidden="true" />
            </span>
          ))}

          {renderedJournalPins.map(({ document, style }) => (
            <button
              type="button"
              className="journal-map-pin"
              style={{
                ...style,
                "--journal-pin-color": document.map_pin?.color,
              } as CSSProperties}
              onClick={() => onJournalDocumentSelect(document.document_id)}
              aria-label={`Open handout ${document.title}`}
              key={`journal-pin:${document.document_id}`}
            >
              <span aria-hidden="true">◆</span>
            </button>
          ))}

          {authoritativeTokens.map(({ token, actor, cell, style }) => {
                const actorId = token.actor_id;
                const active = actorId !== null && actorId === projection.active_actor_id;
                const selected = actorId !== null && actorId === selectedActorId;
                const targetable = actorId !== null && selectableTargetIds.has(actorId);
                const targeted = actorId !== null && actorId === selectedTargetId;
                const team = actor?.team ?? "neutral";
                const hpPercent = actor
                  ? Math.max(0, (actor.hp / Math.max(actor.max_hp, 1)) * 100)
                  : 0;
                const conditionCopy = token.condition_labels.length
                  ? `, ${token.condition_labels.join(", ")}`
                  : "";
                return (
                  <button
                    key={token.token_id}
                    type="button"
                    className={`map-token authoritative-token team-${team} nameplate-${token.nameplate} ${active ? "is-active" : ""} ${selected ? "is-selected" : ""} ${targetable ? "is-targetable" : ""} ${targeted ? "is-targeted" : ""} ${actor?.dead ? "is-defeated" : ""} ${token.locked ? "is-locked" : ""} ${measureMode ? "is-measuring" : ""} ${pingMode ? "is-pinging" : ""} ${templateMode ? "is-templating" : ""} ${drawingTool.active ? "is-drawing" : ""}`}
                    style={{
                      ...style,
                      width: `${token.pose.width_ft / calibration.distance_ft * calibration.cell_extent_px / mapWidthPx * 100}%`,
                      height: `${token.pose.height_ft / calibration.distance_ft * calibration.cell_extent_px / mapHeightPx * 100}%`,
                      zIndex: 108 + token.pose.layer,
                      "--token-rotation": `${token.pose.rotation_degrees}deg`,
                      "--token-aura-cells": token.aura_radius_ft / calibration.distance_ft,
                      "--token-aura-color": token.aura_color,
                    } as CSSProperties}
                    onClick={() => {
                      if (pingMode || measureMode || templateMode || drawingTool.active) {
                        if (cell) onCellSelect(cell);
                        return;
                      }
                      if (actorId !== null) {
                        onTokenSelect(actorId);
                        if (targetable) onTargetSelect(actorId);
                      }
                    }}
                    aria-pressed={selected || targeted}
                    aria-label={`${token.name}${actor ? `, ${actor.hp} of ${actor.max_hp} hit points` : ""}${token.locked ? ", locked" : ""}${conditionCopy}${active ? ", active turn" : ""}${targetable ? ", server-selectable target" : ""}`}
                  >
                    {token.aura_radius_ft > 0 ? <span className="token-aura" aria-hidden="true" /> : null}
                    <span className="token-orbit" aria-hidden="true" />
                    <span className="token-face">{initials(token.name)}</span>
                    {token.show_hp_bar && actor ? (
                      <span className="token-hp" aria-hidden="true"><i style={{ width: `${hpPercent}%` }} /></span>
                    ) : null}
                    <span className="token-name">{token.name}</span>
                    {token.locked ? <span className="token-lock" aria-hidden="true">◇</span> : null}
                  </button>
                );
              })}

          <VttDrawingLayer
            drawings={drawings}
            layer="over_tokens"
            calibration={calibration}
            originFeet={drawingOriginFeet}
            widthPx={mapWidthPx}
            heightPx={mapHeightPx}
            selectedAnnotationId={selectedAnnotationId}
          />

          {calibration.topology === "gridless" && currentGridlessMeasurement?.end ? (
            <svg
              className="measurement-line"
              viewBox={`0 0 ${mapWidthPx} ${mapHeightPx}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <line
                x1={currentGridlessMeasurement.start.x_px}
                y1={currentGridlessMeasurement.start.y_px}
                x2={currentGridlessMeasurement.end.x_px}
                y2={currentGridlessMeasurement.end.y_px}
              />
            </svg>
          ) : measurement.start !== null && measurement.end !== null ? (
            <svg
              className="measurement-line"
              viewBox={`0 0 ${mapWidthPx} ${mapHeightPx}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <line
                x1={boardCellToPixel(calibration, boardCellFromGrid(calibration, measurement.start)).x_px}
                y1={boardCellToPixel(calibration, boardCellFromGrid(calibration, measurement.start)).y_px}
                x2={boardCellToPixel(calibration, boardCellFromGrid(calibration, measurement.end)).x_px}
                y2={boardCellToPixel(calibration, boardCellFromGrid(calibration, measurement.end)).y_px}
              />
            </svg>
          ) : null}
          {calibration.topology === "gridless" && currentGridlessMeasurement ? (
            <span
              className="measure-marker measure-marker-start"
              style={{
                left: `${currentGridlessMeasurement.start.x_px / mapWidthPx * 100}%`,
                top: `${currentGridlessMeasurement.start.y_px / mapHeightPx * 100}%`,
              }}
              aria-hidden="true"
            >
              S
            </span>
          ) : measurement.start !== null ? (
            <span
              className="measure-marker measure-marker-start"
              style={presentedCellStyle(
                calibration,
                measurement.start,
                mapWidthPx,
                mapHeightPx,
                false,
              )}
              aria-hidden="true"
            >
              S
            </span>
          ) : null}
          {calibration.topology === "gridless" && currentGridlessMeasurement?.end ? (
            <span
              className="measure-marker measure-marker-end"
              style={{
                left: `${currentGridlessMeasurement.end.x_px / mapWidthPx * 100}%`,
                top: `${currentGridlessMeasurement.end.y_px / mapHeightPx * 100}%`,
              }}
              aria-hidden="true"
            >
              E
            </span>
          ) : measurement.end !== null ? (
            <span
              className="measure-marker measure-marker-end"
              style={presentedCellStyle(
                calibration,
                measurement.end,
                mapWidthPx,
                mapHeightPx,
                false,
              )}
              aria-hidden="true"
            >
              E
            </span>
          ) : null}
          {showVisibilityMask ? (
            <VttVisibilityMask
              projection={visibilityProjection}
              sources={visibilitySources}
              status={visibilityStatus}
              error={visibilityError}
            />
          ) : null}
        </div>

        {projection.phase === "terminal" ? (
          <div className={`terminal-overlay outcome-${projection.outcome}`} role="status">
            <p className="eyebrow">{outcomeCopy(projection.outcome).eyebrow}</p>
            <h3>{outcomeCopy(projection.outcome).title}</h3>
            <p>{outcomeCopy(projection.outcome).body}</p>
          </div>
        ) : null}
      </div>

      <div className="map-footer">
        <span><i className="legend-dot legend-party" /> Party</span>
        <span><i className="legend-dot legend-enemy" /> Hostile</span>
        <span><i className="legend-ring" /> Active</span>
        <p>
          {drawingTool.active
            ? `Drawing mode · ${titleCase(drawingTool.kind)} · ${drawingTool.layer.replace("_", " ")}`
            : templateMode
            ? `Template mode · ${titleCase(templateKind)} · persisted shared area`
            : pingMode
            ? "Ping mode · shared server annotation"
            : measureMode
            ? "Measure mode · local presentation only"
            : movementPlan
              ? `Plan ${cellLabel(movementPlan.destination)} · ${movementPlan.distanceFt} ft`
              : "Authoritative positions · engine feet"}
        </p>
      </div>
    </section>
  );
}

function ActorInspector({ actor }: { actor: ActorProjection }) {
  return (
    <section className="actor-inspector" aria-labelledby="actor-inspector-title">
      <div className="actor-identity">
        <span className={`portrait-token team-${actor.team}`}>{initials(actor.name)}</span>
        <div>
          <p className="eyebrow">Selected / {titleCase(actor.team)}</p>
          <h2 id="actor-inspector-title">{actor.name}</h2>
        </div>
        <span className="armor-readout" title="Armor class">
          <small>AC</small>
          {actor.ac}
        </span>
      </div>
      <div className="actor-vitals">
        <div className="vital-label">
          <span>Hit points</span>
          <strong>{actor.hp} <small>/ {actor.max_hp}</small></strong>
        </div>
        <HealthBar actor={actor} />
      </div>
      <div className="actor-stats">
        <div><span>Move</span><strong>{actor.movement_remaining} ft</strong></div>
        <div><span>Temp HP</span><strong>{actor.temp_hp}</strong></div>
        <div><span>Reaction</span><strong>{actor.reaction_available ? "Ready" : "Spent"}</strong></div>
      </div>
      <div className="condition-row">
        {actor.conditions.length > 0 ? (
          actor.conditions.map((condition) => (
            <span className="condition-chip" key={condition}>{titleCase(condition)}</span>
          ))
        ) : (
          <span className="condition-empty">No active conditions</span>
        )}
      </div>
    </section>
  );
}

function CommandPanel({
  view,
  selectedActor,
  selectedActionName,
  selectedTargetId,
  movementPlan,
  preview,
  fingerprint,
  pending,
  commandError,
  canAdmin,
  canControlActiveActor,
  onActionSelect,
  onTargetSelect,
  onStart,
  onPreview,
  onCommit,
}: {
  view: VttSessionView;
  selectedActor: ActorProjection;
  selectedActionName: string;
  selectedTargetId: string | null;
  movementPlan: GridMovementPlan | null;
  preview: PreviewState | null;
  fingerprint: string;
  pending: PendingOperation;
  commandError: string | null;
  canAdmin: boolean;
  canControlActiveActor: boolean;
  onActionSelect: (name: string) => void;
  onTargetSelect: (actorId: string) => void;
  onStart: () => void;
  onPreview: () => void;
  onCommit: () => void;
}) {
  const projection = view.projection;
  const activeActor = projection.active_actor_id
    ? projection.actors[projection.active_actor_id]
    : undefined;
  const choices = projection.choices;
  const selectedChoice = choices?.actions.find(
    (choice) => choice.action_name === selectedActionName,
  );
  const targets = (selectedChoice?.selectable_target_ids ?? []).map(
    (actorId) => projection.actors[actorId],
  );
  const selectedTargetIsSelectable = Boolean(
    selectedTargetId &&
      selectedChoice?.selectable_target_ids.includes(selectedTargetId),
  );
  const selectedTargetIsLegalNow = Boolean(
    selectedTargetId &&
      selectedChoice?.legal_target_ids.includes(selectedTargetId),
  );
  const requiresMovement = Boolean(
    selectedChoice?.requires_explicit_targets &&
      selectedTargetIsSelectable &&
      !selectedTargetIsLegalNow,
  );
  const canPreview = Boolean(
    canControlActiveActor &&
      activeActor &&
      choices &&
      selectedChoice &&
      movementPlan &&
      (!selectedChoice.requires_explicit_targets || selectedTargetIsSelectable) &&
      (!requiresMovement || movementPlan.distanceFt > 0),
  );
  const canCommit = canPreview && preview?.fingerprint === fingerprint;
  const previewDeltas = preview
    ? Object.values(projection.actors)
        .map((actor) => {
          const projected = preview.response.projection.actors[actor.actor_id];
          return projected ? { actor, hpDelta: projected.hp - actor.hp } : null;
        })
        .filter((entry): entry is { actor: ActorProjection; hpDelta: number } =>
          Boolean(entry && entry.hpDelta !== 0),
        )
    : [];

  return (
    <aside className="panel command-panel" aria-labelledby="command-title">
      <ActorInspector actor={selectedActor} />

      <div className="command-divider" />

      {projection.phase === "unstarted" ? (
        <section className="start-module">
          <p className="eyebrow">Admin control</p>
          <h2 id="command-title">Bring the vault online</h2>
          <p>
            Lock the fixed initiative order, prepare Vela’s opening turn, and begin
            the encounter at revision {view.revision}.
          </p>
          <button
            type="button"
            className="button button-primary button-wide"
            disabled={!canAdmin || pending !== null}
            onClick={onStart}
          >
            <span className="play-glyph" aria-hidden="true" />
            {pending === "start" ? "Starting encounter…" : "Start encounter"}
          </button>
          {!canAdmin ? (
            <p className="command-permission-note">
              Only a Game Master can start the encounter.
            </p>
          ) : null}
        </section>
      ) : projection.phase === "terminal" ? (
        <section className="terminal-module">
          <p className="eyebrow">Final state</p>
          <h2 id="command-title">{titleCase(projection.outcome ?? "complete")}</h2>
          <p>
            Revision {view.revision} is terminal. Actions are disabled while the
            public event record remains available below.
          </p>
          <div className="terminal-stamp">{projection.winner ?? "No winner"}</div>
        </section>
      ) : (
        <section className="action-module">
          <div className="module-heading">
            <div>
              <p className="eyebrow">Active instrument</p>
              <h2 id="command-title">Declare {activeActor?.name ?? "turn"}</h2>
            </div>
            <span className="step-count">01—04</span>
          </div>

          <fieldset className="choice-group movement-group">
            <legend>1. Choose destination</legend>
            <div className="movement-choice">
              <span className="movement-symbol" aria-hidden="true">⌖</span>
              <span>
                <strong>
                  {movementPlan
                    ? `Cell ${cellLabel(movementPlan.destination)}`
                    : "Select a reachable cell"}
                </strong>
                <small>
                  {movementPlan
                    ? movementPlan.distanceFt === 0
                      ? "Hold position"
                      : `${movementPlan.distanceFt} ft · direct path`
                    : "Use the highlighted cells on the tactical map"}
                </small>
              </span>
              <i aria-hidden="true" />
            </div>
          </fieldset>

          <fieldset className="choice-group">
            <legend>2. Select action</legend>
            <div className="action-list">
              {choices && choices.actions.length > 0 ? (
                choices.actions.map((choice) => {
                  const action = activeActor?.actions.find(
                    (candidate) => candidate.name === choice.action_name,
                  );
                  if (!action) return null;
                  const unavailable =
                    choice.requires_explicit_targets &&
                    choice.selectable_target_ids.length === 0;
                  return (
                    <button
                      type="button"
                      key={choice.action_name}
                      className={`action-choice ${choice.action_name === selectedActionName ? "is-selected" : ""}`}
                      onClick={() => onActionSelect(choice.action_name)}
                      aria-pressed={choice.action_name === selectedActionName}
                      disabled={unavailable}
                    >
                      <span className="action-symbol" aria-hidden="true">✦</span>
                      <span>
                        <strong>{choice.action_name}</strong>
                        <small>
                          {titleCase(action.action_type)} · {rangeLabel(action)}
                        </small>
                      </span>
                      <i aria-hidden="true" />
                    </button>
                  );
                })
              ) : (
                <p className="no-targets">No available actions for this turn.</p>
              )}
            </div>
          </fieldset>

          <fieldset className="choice-group target-group">
            <legend>3. Select target</legend>
            <div className="target-list">
              {selectedChoice?.requires_explicit_targets && targets.length > 0 ? (
                targets.map((target) => (
                  <button
                    type="button"
                    key={target.actor_id}
                    className={`${target.actor_id === selectedTargetId ? "is-selected" : ""} ${selectedChoice.legal_target_ids.includes(target.actor_id) ? "is-legal-now" : "needs-movement"}`}
                    onClick={() => onTargetSelect(target.actor_id)}
                    aria-pressed={target.actor_id === selectedTargetId}
                    title={`${target.hp} hit points`}
                  >
                    <span className={`target-reticle team-${target.team}`} aria-hidden="true" />
                    <span>{target.name}</span>
                    <small>
                      {selectedChoice.legal_target_ids.includes(target.actor_id)
                        ? "Legal now"
                        : "Requires movement"}
                    </small>
                  </button>
                ))
              ) : selectedChoice?.requires_explicit_targets ? (
                <p className="no-targets">
                  No selectable targets are available for this action.
                </p>
              ) : selectedChoice ? (
                <p className="no-targets">
                  No target selection required. The engine resolves recipients.
                </p>
              ) : (
                <p className="no-targets">Choose an available action first.</p>
              )}
            </div>
            {requiresMovement ? (
              <p className="target-guidance" role="status">
                Requires movement from the current position. Choose a destination,
                then preview for the authoritative legality result.
              </p>
            ) : null}
          </fieldset>

          <div className="preview-module">
            <div className="preview-heading">
              <div>
                <p className="eyebrow">4. Verify & commit</p>
                <h3>{preview ? "Preview resolved" : "Stage a safe preview"}</h3>
              </div>
              {preview ? <span className="verified-badge">Verified</span> : null}
            </div>

            {preview ? (
              <div className="preview-result" aria-live="polite">
                {movementPlan && movementPlan.distanceFt > 0 ? (
                  <div>
                    <span>Movement</span>
                    <strong>
                      {cellLabel(movementPlan.destination)} · {movementPlan.distanceFt} ft
                    </strong>
                  </div>
                ) : null}
                {previewDeltas.length > 0 ? (
                  previewDeltas.map(({ actor, hpDelta }) => (
                    <div key={actor.actor_id}>
                      <span>{actor.name}</span>
                      <strong className={hpDelta < 0 ? "delta-damage" : "delta-heal"}>
                        {hpDelta > 0 ? "+" : ""}{hpDelta} HP
                      </strong>
                    </div>
                  ))
                ) : (
                  <p>No hit-point change in this preview.</p>
                )}
                <small>Revision {preview.response.revision} remains unchanged.</small>
              </div>
            ) : (
              <p className="preview-empty">
                Preview uses the pinned seed without mutating the authoritative table.
              </p>
            )}

            <div className="command-buttons">
              <button
                className="button button-secondary"
                type="button"
                onClick={onPreview}
                disabled={!canPreview || pending !== null}
              >
                {pending === "preview" ? "Calculating…" : preview ? "Preview again" : "Preview turn"}
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={onCommit}
                disabled={!canCommit || pending !== null}
              >
                {pending === "commit" ? "Committing…" : "Commit turn"}
              </button>
            </div>
            {!canControlActiveActor ? (
              <p className="command-permission-note">
                You can inspect this turn, but only its owner or a Game Master can act.
              </p>
            ) : null}
          </div>
        </section>
      )}

      {commandError ? (
        <p className="command-error" role="alert">{commandError}</p>
      ) : null}
    </aside>
  );
}

function EventLog({ events }: { events: LoggedEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [events.length]);

  return (
    <section className="panel event-panel" aria-labelledby="event-log-title">
      <div className="panel-heading event-heading">
        <div>
          <p className="eyebrow">Public rules trace</p>
          <h2 id="event-log-title">Event log</h2>
        </div>
        <span className="event-count">{events.length} signals</span>
      </div>
      <div className="event-stream" aria-live="polite">
        {events.length === 0 ? (
          <div className="empty-log">
            <span aria-hidden="true">⌁</span>
            <p>Start the encounter to record its first public rule event.</p>
          </div>
        ) : (
          events.map(({ id, source, event }, index) => {
            const rollCard = rollCardFromEvent(event);
            if (rollCard !== null) {
              return <VttRollCardArticle key={id} card={rollCard} source={source} />;
            }
            return <article className={`event-entry event-${source}`} key={id}>
              <span className="event-sequence">
                {"sequence" in event ? String(event.sequence).padStart(3, "0") : `P${String(index + 1).padStart(2, "0")}`}
              </span>
              <div>
                <div className="event-title-row">
                  <h3>{titleCase(event.kind)}</h3>
                  <span>{source}</span>
                </div>
                <p>{eventSummary(event)}</p>
              </div>
            </article>;
          })
        )}
        <div ref={endRef} />
      </div>
    </section>
  );
}

export function EchoVaultTable() {
  const [view, setView] = useState<VttSessionView | null>(null);
  const [tableIdentity, setTableIdentity] = useState<VttTableView | null>(null);
  const [bearerToken, setBearerToken] = useState<string | null>(null);
  const [credentialRequired, setCredentialRequired] = useState(false);
  const [credentialPending, setCredentialPending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [combatControlError, setCombatControlError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingOperation>(null);
  const [selectedActorId, setSelectedActorId] = useState("");
  const [selectedActionName, setSelectedActionName] = useState("");
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [selectedDestination, setSelectedDestination] = useState<GridCell | null>(null);
  const [measureMode, setMeasureMode] = useState(false);
  const [pingMode, setPingMode] = useState(false);
  const [templateMode, setTemplateMode] = useState(false);
  const [templateKind, setTemplateKind] =
    useState<AreaTemplateKind>("circle");
  const [templateStart, setTemplateStart] = useState<GridCell | null>(null);
  const [templateDimensionFt, setTemplateDimensionFt] = useState(10);
  const [templateAngleDegrees, setTemplateAngleDegrees] = useState(90);
  const [templatePlacementError, setTemplatePlacementError] = useState<
    string | null
  >(null);
  const [drawingMode, setDrawingMode] = useState(false);
  const [drawingSettings, setDrawingSettings] = useState<DrawingToolSettings>({
    kind: "freehand",
    layer: "under_tokens",
    audience: "all",
    strokeColor: "#5eead4",
    fillColor: "#1d4ed8",
    fillEnabled: false,
    opacity: 0.8,
    strokeWidthFt: 0.5,
    lineStyle: "solid",
    locked: false,
    text: "Map note",
    fontSizeFt: 3,
  });
  const [drawingPoints, setDrawingPoints] = useState<AnnotationPoint[]>([]);
  const [drawingPlacementError, setDrawingPlacementError] = useState<
    string | null
  >(null);
  const [selectedAnnotationId, setSelectedAnnotationId] = useState("");
  const [selectedJournalDocumentId, setSelectedJournalDocumentId] = useState("");
  const [measurement, setMeasurement] = useState<GridMeasurement>(
    EMPTY_GRID_MEASUREMENT,
  );
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [events, setEvents] = useState<LoggedEvent[]>([]);
  const [streamStatus, setStreamStatus] = useState<
    "connecting" | "live" | "reconnecting" | "invalid"
  >("connecting");
  const latestRevisionRef = useRef(0);
  const sessionIdRef = useRef<string | null>(null);
  const eventCursorRef = useRef(0);
  const sharedScenes = useVttScenes({
    sessionId: view?.session_id ?? null,
    tableId: tableIdentity?.table_id ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
  });
  const boardPresentation = selectActiveBoardPresentation(
    view,
    loadError,
    sharedScenes.view,
  );
  const activeBoard = boardPresentation.board;
  const sharedAnnotations = useVttAnnotations({
    sessionId: view?.session_id ?? null,
    tableId: tableIdentity?.table_id ?? null,
    sceneId: activeBoard?.scene.scene_id ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
  });
  const sharedMapAssets = useVttMapAssets({
    sessionId: view?.session_id ?? null,
    tableId: tableIdentity?.table_id ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
  });
  const sharedTokens = useVttTokens({
    sessionId: view?.session_id ?? null,
    tableId: tableIdentity?.table_id ?? null,
    sceneId: activeBoard?.scene.scene_id ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
  });
  const sharedJournal = useVttJournal({
    sessionId: view?.session_id ?? null,
    tableId: tableIdentity?.table_id ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
  });
  const sharedPresentation = useVttPresentation({
    sessionId: view?.session_id ?? null,
    tableId: tableIdentity?.table_id ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
    activeSceneId: activeBoard?.scene.scene_id ?? null,
  });
  const sharedVisibility = useVttVisibility({
    sessionId: view?.session_id ?? null,
    tableId: tableIdentity?.table_id ?? null,
    sceneId: activeBoard?.scene.scene_id ?? null,
    sceneRevision: activeBoard?.scene_revision ?? null,
    tokenRevision: sharedTokens.view?.revision ?? null,
    encounterRevision: view?.revision ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
  });
  const activeSceneMetadata = view?.active_board?.map_metadata ?? null;
  const activeMapAsset = useVttMapAssetUrl(
    activeSceneMetadata?.asset ?? null,
    bearerToken,
  );
  const activePingMode = pingMode && sharedAnnotations.available;
  const activeDrawingMode = drawingMode && sharedAnnotations.available;
  const gmVisibilityPreview = tableIdentity?.current_participant.role === "gm"
    ? sharedVisibility.preview
    : null;
  const tacticalVisibility = gmVisibilityPreview ?? sharedVisibility.projection;
  const tacticalTokens = gmVisibilityPreview
    ? gmVisibilityPreview.tokens
    : tableIdentity?.current_participant.role === "gm"
      ? sharedTokens.view?.tokens ?? []
      : sharedVisibility.projection?.tokens ?? [];
  const showVisibilityMask = Boolean(
    tableIdentity &&
      (tableIdentity.current_participant.role !== "gm" ||
        sharedVisibility.previewParticipantId !== null),
  );
  const activeTemplateMode = Boolean(
    templateMode &&
      sharedAnnotations.available &&
      view?.active_board &&
      squareTemplatesAreSupported(
        view.active_board.scene,
        view.active_board.map_metadata,
      ),
  );
  const resolvedSelectedAnnotationId =
    sharedAnnotations.annotations.find(
      (annotation) => annotation.annotation_id === selectedAnnotationId,
    )?.annotation_id ??
    sharedAnnotations.annotations.find(
      (annotation) =>
        annotation.author_id === tableIdentity?.current_participant.participant_id,
    )?.annotation_id ??
    sharedAnnotations.annotations[0]?.annotation_id ??
    "";
  const resolvedSelectedAnnotation = sharedAnnotations.annotations.find(
    (annotation) => annotation.annotation_id === resolvedSelectedAnnotationId,
  );

  const toggleMeasureMode = useCallback(() => {
    setMeasureMode((current) => !current);
    setPingMode(false);
    setTemplateMode(false);
    setTemplateStart(null);
    setTemplatePlacementError(null);
    setDrawingMode(false);
    setDrawingPoints([]);
    setDrawingPlacementError(null);
  }, []);

  const togglePingMode = useCallback(() => {
    if (!sharedAnnotations.canPlace) return;
    setPingMode((current) => !current);
    setMeasureMode(false);
    setTemplateMode(false);
    setTemplateStart(null);
    setTemplatePlacementError(null);
    setDrawingMode(false);
    setDrawingPoints([]);
    setDrawingPlacementError(null);
  }, [sharedAnnotations.canPlace]);

  const toggleTemplateMode = useCallback(() => {
    if (!sharedAnnotations.canMutate) return;
    setTemplateMode((current) => !current);
    setMeasureMode(false);
    setPingMode(false);
    setTemplateStart(null);
    setTemplatePlacementError(null);
    setDrawingMode(false);
    setDrawingPoints([]);
    setDrawingPlacementError(null);
  }, [sharedAnnotations.canMutate]);

  const toggleDrawingMode = useCallback(() => {
    if (!sharedAnnotations.canMutate) return;
    const transition = advanceDrawingDraft(
      {
        active: drawingMode,
        kind: drawingSettings.kind,
        points: drawingPoints,
      },
      { type: "shortcut", key: "D" },
    );
    if (
      transition.state.active &&
      resolvedSelectedAnnotation &&
      isDrawingAnnotation(resolvedSelectedAnnotation)
    ) {
      setDrawingSettings(settingsFromDrawing(resolvedSelectedAnnotation));
    }
    setDrawingMode(transition.state.active);
    setMeasureMode(false);
    setPingMode(false);
    setTemplateMode(false);
    setTemplateStart(null);
    setTemplatePlacementError(null);
    setDrawingPoints([]);
    setDrawingPlacementError(null);
  }, [
    drawingMode,
    drawingPoints,
    drawingSettings.kind,
    resolvedSelectedAnnotation,
    sharedAnnotations.canMutate,
  ]);

  const changeDrawingSettings = useCallback(
    (changes: Partial<DrawingToolSettings>) => {
      setDrawingSettings((current) => ({ ...current, ...changes }));
      if (changes.kind !== undefined) {
        const transition = advanceDrawingDraft(
          {
            active: drawingMode,
            kind: drawingSettings.kind,
            points: drawingPoints,
          },
          { type: "select_kind", kind: changes.kind },
        );
        setDrawingPoints(transition.state.points);
      }
      setDrawingPlacementError(null);
    },
    [drawingMode, drawingPoints, drawingSettings.kind],
  );

  const selectTemplateKind = useCallback((kind: AreaTemplateKind) => {
    setTemplateKind(kind);
    setTemplateStart(null);
    setTemplatePlacementError(null);
  }, []);

  useEffect(() => {
    const handleMeasureShortcut = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.repeat ||
        event.key.toLowerCase() !== "m" ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        isInteractiveControl(event.target) ||
        isInteractiveControl(document.activeElement)
      ) {
        return;
      }
      event.preventDefault();
      toggleMeasureMode();
    };

    const handlePingShortcut = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.repeat ||
        event.key.toLowerCase() !== "p" ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        !sharedAnnotations.canPlace ||
        isInteractiveControl(event.target) ||
        isInteractiveControl(document.activeElement)
      ) {
        return;
      }
      event.preventDefault();
      togglePingMode();
    };

    const handleTemplateShortcut = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.repeat ||
        event.key.toLowerCase() !== "t" ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        !sharedAnnotations.canMutate ||
        isInteractiveControl(event.target) ||
        isInteractiveControl(document.activeElement)
      ) {
        return;
      }
      event.preventDefault();
      toggleTemplateMode();
    };

    const handleDrawingShortcut = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.repeat ||
        event.key.toLowerCase() !== "d" ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        !sharedAnnotations.canMutate ||
        isInteractiveControl(event.target) ||
        isInteractiveControl(document.activeElement)
      ) {
        return;
      }
      event.preventDefault();
      toggleDrawingMode();
    };

    window.addEventListener("keydown", handleMeasureShortcut);
    window.addEventListener("keydown", handlePingShortcut);
    window.addEventListener("keydown", handleTemplateShortcut);
    window.addEventListener("keydown", handleDrawingShortcut);
    return () => {
      window.removeEventListener("keydown", handleMeasureShortcut);
      window.removeEventListener("keydown", handlePingShortcut);
      window.removeEventListener("keydown", handleTemplateShortcut);
      window.removeEventListener("keydown", handleDrawingShortcut);
    };
  }, [
    sharedAnnotations.canMutate,
    sharedAnnotations.canPlace,
    toggleMeasureMode,
    togglePingMode,
    toggleTemplateMode,
    toggleDrawingMode,
  ]);

  const adoptView = useCallback((nextView: VttSessionView) => {
    const projection = nextView.projection;
    const choices = projection.choices;
    const actorId =
      choices?.actor_id ??
      projection.active_actor_id ??
      projection.initiative_order[0];
    const actor = projection.actors[actorId];
    const selection = initialTurnSelection(choices);
    latestRevisionRef.current = nextView.revision;
    sessionIdRef.current = nextView.session_id;
    setView(nextView);
    setSelectedActorId(actorId);
    setSelectedActionName(selection.actionName);
    setSelectedTargetId(selection.targetId);
    setSelectedDestination(
      nextView.active_board && actor
        ? presentedFeetToCell(
            nextView.active_board.scene,
            presentedCalibration(nextView.active_board.map_metadata),
            choices?.movement.origin ?? actor.position,
          )
        : null,
    );
    setPreview(null);
    setCommandError(null);
  }, []);

  const adoptConnection = useCallback((connection: {
    identity: VttTableView;
    view: VttSessionView;
  }, nextBearerToken: string | null) => {
    setBearerToken(nextBearerToken);
    setTableIdentity(connection.identity);
    setCredentialRequired(false);
    adoptView(connection.view);
  }, [adoptView]);

  const refresh = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    setLoadError(null);
    try {
      const nextView = await getSessionView(undefined, bearerToken);
      adoptView(nextView);
      return nextView;
    } catch (error) {
      const message = errorMessage(error);
      setLoadError(message);
      if (error instanceof VttApiError && error.status === 401) {
        setCredentialRequired(true);
      }
      throw error;
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [adoptView, bearerToken]);

  useEffect(() => {
    const library = sharedScenes.view;
    const board = view?.active_board;
    if (
      library === null ||
      library.active_scene_id === null ||
      board === null ||
      board === undefined ||
      (library.revision === board.scene_revision &&
        library.active_scene_id === board.scene.scene_id)
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      void refresh().catch(() => undefined);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh, sharedScenes.view, view?.active_board]);

  const activeBoardIdentity = view?.active_board
    ? `${view.active_board.scene.scene_id}:${view.active_board.scene_revision}`
    : "unavailable";
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSelectedDestination(null);
      setMeasurement({ ...EMPTY_GRID_MEASUREMENT });
      setMeasureMode(false);
      setPingMode(false);
      setTemplateMode(false);
      setTemplateStart(null);
      setTemplatePlacementError(null);
      setDrawingMode(false);
      setDrawingPoints([]);
      setDrawingPlacementError(null);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [activeBoardIdentity]);

  useEffect(() => {
    let active = true;
    loadTableConnection(null)
      .then((connection) => {
        if (active) adoptConnection(connection, null);
      })
      .catch((error) => {
        if (!active) return;
        if (error instanceof VttApiError && error.status === 401) {
          setCredentialRequired(true);
          setLoadError("Enter the private credential supplied by your Game Master.");
        } else {
          setLoadError(errorMessage(error));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [adoptConnection]);

  const appendEvents = useCallback((response: VttCommandResponse) => {
    const source = response.response_type;
    const nextEvents = response.events.map((event, index) => ({
      id:
        "event_id" in event
          ? event.event_id
          : `${response.command_id}:${source}:${index}`,
      source,
      event,
    }));
    setEvents((current) => appendUniqueEvents(current, nextEvents));
  }, []);

  useEffect(() => {
    if (view === null || tableIdentity === null) return;
    const controller = new AbortController();
    let active = true;

    const synchronize = async () => {
      setStreamStatus("connecting");
      while (active && !controller.signal.aborted) {
        try {
          const cursor = await streamVttEvents({
            after: eventCursorRef.current,
            bearerToken,
            signal: controller.signal,
            onOpen: () => {
              if (active) setStreamStatus("live");
            },
            onEvent: (event) => {
              if (
                sessionIdRef.current !== null &&
                event.session_id !== sessionIdRef.current
              ) {
                throw new Error("Live event belongs to another VTT session");
              }
              if (event.sequence <= eventCursorRef.current) return;
              eventCursorRef.current = event.sequence;
              setEvents((current) =>
                appendUniqueEvents(current, [
                  { id: event.event_id, source: "stream", event },
                ]),
              );
              if (event.revision > latestRevisionRef.current) {
                void refresh().catch(() => undefined);
              }
            },
          });
          eventCursorRef.current = Math.max(eventCursorRef.current, cursor);
          if (!active || controller.signal.aborted) return;
          setStreamStatus("reconnecting");
        } catch (streamError) {
          if (
            !active ||
            (streamError instanceof DOMException &&
              streamError.name === "AbortError")
          ) return;
          if (streamError instanceof VttApiError && streamError.status === 401) {
            setCredentialRequired(true);
            setLoadError("Your table credential is no longer accepted.");
            return;
          }
          if (streamError instanceof TypeError) {
            setStreamStatus("reconnecting");
            setLoadError("The live event stream is reconnecting.");
          } else {
            setStreamStatus("invalid");
            setLoadError("The live event stream returned invalid public data.");
            return;
          }
        }
        await waitForEventReconnect(controller.signal);
      }
    };

    void synchronize();
    return () => {
      active = false;
      controller.abort();
    };
  }, [bearerToken, refresh, tableIdentity, view]);

  const projection = view?.projection;
  const scene = activeBoard?.scene ?? null;
  const activeActor =
    projection?.active_actor_id
      ? projection.actors[projection.active_actor_id]
      : undefined;
  const canControlActiveActor = Boolean(
    activeActor &&
      tableIdentity &&
      canControlActor(tableIdentity.current_participant, activeActor.actor_id),
  );
  const choices = projection?.choices ?? null;
  const selectedChoice = choices?.actions.find(
    (choice) => choice.action_name === selectedActionName,
  );
  const targetIds = selectedTargetIdsForChoice(
    selectedChoice,
    selectedTargetId,
  );
  const boardCalibration = activeBoard
    ? presentedCalibration(activeBoard.map_metadata)
    : null;
  const movementPlan = (() => {
    if (!scene || !boardCalibration || !choices) return null;
    if (boardCalibration.topology === "gridless") {
      return {
        destination: { column: 0, row: 0 },
        distanceFt: 0,
        end: [...choices.movement.origin] as Position3,
        path: [],
      };
    }
    if (!selectedDestination) return null;
    try {
      return planPresentedMovement({
        scene,
        calibration: boardCalibration,
        start: choices.movement.origin,
        destination: selectedDestination,
        movementRemaining: choices.movement.remaining_ft,
      });
    } catch {
      return null;
    }
  })();
  const reachableCells = (() => {
    const reachable = new Set<string>();
    if (
      !scene ||
      !activeBoard ||
      !boardCalibration ||
      boardCalibration.topology === "gridless" ||
      !activeActor ||
      !choices ||
      projection?.phase !== "awaiting_declaration"
    ) {
      return reachable;
    }
    const occupied = new Set<string>();
    for (const actor of Object.values(projection.actors)) {
      if (actor.actor_id === activeActor.actor_id || actor.dead) continue;
      try {
        occupied.add(
          cellKey(presentedFeetToCell(scene, boardCalibration, actor.position)),
        );
      } catch {
        // An off-presentation actor cannot occupy a presented destination.
      }
    }
    let candidates: GridCell[] = [];
    try {
      candidates = presentedCells(activeBoard.map_metadata);
    } catch {
      return reachable;
    }
    for (const destination of candidates) {
      if (occupied.has(cellKey(destination))) continue;
      try {
        planPresentedMovement({
          scene,
          calibration: boardCalibration,
          start: choices.movement.origin,
          destination,
          movementRemaining: choices.movement.remaining_ft,
        });
        reachable.add(cellKey(destination));
      } catch {
        // The authoritative preview remains the final legality check.
      }
    }
    return reachable;
  })();
  const fingerprint = view && activeActor && choices
    ? selectionFingerprint(
        view.revision,
        activeActor.actor_id,
        selectedActionName,
        targetIds,
        movementPlan?.path ?? [],
      )
    : "";
  const targetOptions = useMemo(
    () => new Set(selectedChoice?.selectable_target_ids ?? []),
    [selectedChoice],
  );
  const selectedTargetNeedsMovement = Boolean(
    selectedChoice?.requires_explicit_targets &&
      selectedTargetId &&
      !selectedChoice.legal_target_ids.includes(selectedTargetId),
  );
  const declarationReady = Boolean(
    activeActor &&
      selectedChoice &&
      movementPlan &&
      (!selectedChoice.requires_explicit_targets || targetIds.length === 1) &&
      (!selectedTargetNeedsMovement || movementPlan.distanceFt > 0),
  );

  const handleActionSelect = (name: string) => {
    const choice = choices?.actions.find(
      (candidate) => candidate.action_name === name,
    );
    if (!choice) return;
    setSelectedActionName(name);
    setSelectedTargetId(
      choice.requires_explicit_targets
        ? choice.selectable_target_ids[0] ?? null
        : null,
    );
    setPreview(null);
    setCommandError(null);
  };

  const handleTargetSelect = (actorId: string) => {
    if (!selectedChoice?.selectable_target_ids.includes(actorId)) return;
    setSelectedTargetId(actorId);
    setPreview(null);
    setCommandError(null);
  };

  const handleMovementCellSelect = (destination: GridCell) => {
    if (!reachableCells.has(cellKey(destination))) return;
    setSelectedDestination(destination);
    setSelectedActorId(activeActor?.actor_id ?? selectedActorId);
    setPreview(null);
    setCommandError(null);
  };

  const drawingAudience = (): string[] =>
    drawingSettings.audience === "all"
      ? ["all"]
      : tableIdentity
        ? [`participant:${tableIdentity.current_participant.participant_id}`]
        : [];

  const persistNewDrawing = async (points: AnnotationPoint[]) => {
    if (!activeBoard || !tableIdentity) {
      throw new Error("The active drawing board is unavailable.");
    }
    const annotation = buildDrawingAnnotation({
      sceneId: activeBoard.scene.scene_id,
      authorId: tableIdentity.current_participant.participant_id,
      audience: drawingAudience(),
      kind: drawingSettings.kind,
      layer: drawingSettings.layer,
      locked: drawingSettings.locked,
      style: {
        stroke_color: drawingSettings.strokeColor,
        fill_color: drawingSettings.fillEnabled ? drawingSettings.fillColor : null,
        opacity: drawingSettings.opacity,
        stroke_width_ft: drawingSettings.strokeWidthFt,
        line_style: drawingSettings.lineStyle,
      },
      points,
      text: drawingSettings.text,
      fontSizeFt: drawingSettings.fontSizeFt,
      backgroundColor: drawingSettings.fillEnabled
        ? drawingSettings.fillColor
        : null,
      headSizeFt: Math.min(
        1_000,
        Math.max(0.1, drawingSettings.strokeWidthFt * 2),
      ),
    });
    await sharedAnnotations.placeAnnotation(annotation);
    setDrawingPoints([]);
    setDrawingPlacementError(null);
  };

  const handleDrawingPointSelect = (position: Position3) => {
    if (!activeDrawingMode || !sharedAnnotations.canMutate) return;
    const point: AnnotationPoint = {
      x_ft: position[0],
      y_ft: position[1],
      z_ft: position[2],
    };
    const transition = advanceDrawingDraft(
      {
        active: activeDrawingMode,
        kind: drawingSettings.kind,
        points: drawingPoints,
      },
      { type: "keyboard_point", key: "Enter", point },
    );
    if (transition.error) {
      setDrawingPlacementError(transition.error);
      return;
    }
    setDrawingPoints(transition.state.points);
    setDrawingPlacementError(null);
    if (transition.completed) {
      void persistNewDrawing(transition.completed.points).catch((error) =>
        setDrawingPlacementError(errorMessage(error)),
      );
    }
  };

  const finishFreehandDrawing = () => {
    const transition = advanceDrawingDraft(
      {
        active: activeDrawingMode,
        kind: drawingSettings.kind,
        points: drawingPoints,
      },
      { type: "finish" },
    );
    if (transition.error || transition.completed === null) {
      setDrawingPlacementError(transition.error);
      return;
    }
    setDrawingPoints(transition.state.points);
    void persistNewDrawing(transition.completed.points).catch((error) =>
      setDrawingPlacementError(errorMessage(error)),
    );
  };

  const updateSelectedDrawing = () => {
    if (
      !resolvedSelectedAnnotation ||
      !isDrawingAnnotation(resolvedSelectedAnnotation) ||
      isLockedDrawingAnnotation(resolvedSelectedAnnotation) ||
      !sharedAnnotations.canManageAnnotation(resolvedSelectedAnnotation.author_id)
    ) {
      return;
    }
    const style = {
      stroke_color: drawingSettings.strokeColor,
      fill_color: drawingSettings.fillEnabled ? drawingSettings.fillColor : null,
      opacity: drawingSettings.opacity,
      stroke_width_ft: drawingSettings.strokeWidthFt,
      line_style: drawingSettings.lineStyle,
    } as const;
    const common = {
      ...resolvedSelectedAnnotation,
      audience: drawingAudience(),
      layer: drawingSettings.layer,
      locked: drawingSettings.locked,
      style,
    };
    const updated: DrawingAnnotation =
      resolvedSelectedAnnotation.annotation_type === "text_drawing"
        ? {
            ...common,
            annotation_type: "text_drawing",
            anchor: resolvedSelectedAnnotation.anchor,
            text: drawingSettings.text,
            font_size_ft: drawingSettings.fontSizeFt,
            background_color: drawingSettings.fillEnabled
              ? drawingSettings.fillColor
              : null,
          }
        : common;
    void sharedAnnotations
      .placeAnnotation(updated)
      .catch((error) => setDrawingPlacementError(errorMessage(error)));
  };

  const unlockSelectedDrawing = () => {
    if (
      !resolvedSelectedAnnotation ||
      !isLockedDrawingAnnotation(resolvedSelectedAnnotation) ||
      !sharedAnnotations.canManageAnnotation(resolvedSelectedAnnotation.author_id)
    ) {
      return;
    }
    void sharedAnnotations
      .unlockDrawing(resolvedSelectedAnnotation.annotation_id)
      .catch((error) => setDrawingPlacementError(errorMessage(error)));
  };

  const selectManagedAnnotation = (annotationId: string) => {
    setSelectedAnnotationId(annotationId);
    const annotation = sharedAnnotations.annotations.find(
      (candidate) => candidate.annotation_id === annotationId,
    );
    if (annotation && isDrawingAnnotation(annotation)) {
      setDrawingSettings(settingsFromDrawing(annotation));
      setDrawingPoints([]);
      setDrawingPlacementError(null);
    }
  };

  const handleMapCellSelect = (cell: GridCell) => {
    if (activeDrawingMode) {
      if (scene && boardCalibration) {
        handleDrawingPointSelect(
          presentedCellToFeet(scene, boardCalibration, cell),
        );
      }
      return;
    }
    if (activeTemplateMode) {
      if (!scene || !sharedAnnotations.canMutate) return;
      try {
        const needsEndpoint = templateKind === "line" || templateKind === "cone";
        if (needsEndpoint && templateStart === null) {
          setTemplateStart(cell);
          setTemplatePlacementError(null);
          return;
        }
        const identity = {
          scene,
          authorId:
            tableIdentity?.current_participant.participant_id ?? "local",
          audience: ["all"],
        } as const;
        const annotation =
          templateKind === "circle"
            ? buildAreaTemplateAnnotation({
                ...identity,
                kind: "circle",
                center: cell,
                radiusFt: templateDimensionFt,
              })
            : templateKind === "cube"
              ? buildAreaTemplateAnnotation({
                  ...identity,
                  kind: "cube",
                  center: cell,
                  sizeFt: templateDimensionFt,
                })
              : templateKind === "line" && templateStart
                ? buildAreaTemplateAnnotation({
                    ...identity,
                    kind: "line",
                    start: templateStart,
                    end: cell,
                    widthFt: templateDimensionFt,
                  })
                : templateStart
                  ? buildAreaTemplateAnnotation({
                      ...identity,
                      kind: "cone",
                      origin: templateStart,
                      directionEnd: cell,
                      angleDegrees: templateAngleDegrees,
                    })
                  : null;
        if (annotation === null) return;
        setTemplatePlacementError(null);
        void sharedAnnotations
          .placeAnnotation(annotation)
          .then(() => setTemplateStart(null))
          .catch(() => undefined);
      } catch (placementError) {
        setTemplatePlacementError(errorMessage(placementError));
      }
      return;
    }
    if (activePingMode) {
      if (scene && boardCalibration && sharedAnnotations.canPlace) {
        void sharedAnnotations
          .placePing(presentedCellToFeet(scene, boardCalibration, cell))
          .catch(() => undefined);
      }
      return;
    }
    if (measureMode) {
      setMeasurement((current) => nextGridMeasurement(current, cell));
      return;
    }
    handleMovementCellSelect(cell);
  };

  const handleGridlessPointSelect = (position: Position3) => {
    if (activeDrawingMode) {
      handleDrawingPointSelect(position);
      return;
    }
    if (!activePingMode || !sharedAnnotations.canPlace) return;
    void sharedAnnotations.placePing(position).catch(() => undefined);
  };

  const handleStart = async () => {
    if (!view || tableIdentity?.current_participant.role !== "gm") return;
    setPending("start");
    setCommandError(null);
    try {
      const response = await postCommand(
        buildStartCommand({
          sessionId: view.session_id,
          expectedRevision: view.revision,
        }),
        undefined,
        bearerToken,
      );
      appendEvents(response);
      await refresh();
    } catch (error) {
      setCommandError(errorMessage(error));
    } finally {
      setPending(null);
    }
  };

  const handleCombatControl = async (payload: CombatControlPayload) => {
    if (!view || tableIdentity?.current_participant.role !== "gm") return;
    setPending("combat");
    setCombatControlError(null);
    try {
      const response = await postCommand(
        buildCombatControlCommand({
          sessionId: view.session_id,
          expectedRevision: view.revision,
          payload,
        }),
        undefined,
        bearerToken,
      );
      appendEvents(response);
      setPreview(null);
      await refresh();
    } catch (error) {
      setCombatControlError(errorMessage(error));
      if (error instanceof VttApiError && error.code === "stale_revision") {
        await refresh().catch(() => undefined);
      }
    } finally {
      setPending(null);
    }
  };

  const handlePreview = async () => {
    if (
      !view ||
      !activeActor ||
      !selectedChoice ||
      !declarationReady ||
      !canControlActiveActor
    ) return;
    setPending("preview");
    setCommandError(null);
    try {
      const response = await postCommand(
        buildDeclarationCommand({
          sessionId: view.session_id,
          expectedRevision: view.revision,
          actorId: activeActor.actor_id,
          actionName: selectedActionName,
          targetIds,
          movementPath: movementPlan?.path ?? [],
          mode: "preview",
        }),
        undefined,
        bearerToken,
      );
      if (response.response_type !== "preview") {
        throw new Error("The service returned a commit for a preview request.");
      }
      appendEvents(response);
      setPreview({ fingerprint, response });
    } catch (error) {
      setPreview(null);
      setCommandError(errorMessage(error));
    } finally {
      setPending(null);
    }
  };

  const handleCommit = async () => {
    if (
      !view ||
      !activeActor ||
      !selectedChoice ||
      !declarationReady ||
      preview?.fingerprint !== fingerprint
      || !canControlActiveActor
    ) {
      return;
    }
    setPending("commit");
    setCommandError(null);
    try {
      const response = await postCommand(
        buildDeclarationCommand({
          sessionId: view.session_id,
          expectedRevision: view.revision,
          actorId: activeActor.actor_id,
          actionName: selectedActionName,
          targetIds,
          movementPath: movementPlan?.path ?? [],
          mode: "commit",
        }),
        undefined,
        bearerToken,
      );
      appendEvents(response);
      setPreview(null);
      await refresh();
    } catch (error) {
      setCommandError(errorMessage(error));
      if (error instanceof VttApiError && error.code === "stale_revision") {
        await refresh().catch(() => undefined);
      }
    } finally {
      setPending(null);
    }
  };

  if (loading) return <LoadingView />;
  if (credentialRequired) {
    return (
      <VttAccessGate
        error={loadError}
        pending={credentialPending}
        onConnect={async (nextBearerToken) => {
          setCredentialPending(true);
          setLoadError(null);
          try {
            const connection = await loadTableConnection(nextBearerToken);
            adoptConnection(connection, nextBearerToken);
          } catch (error) {
            const message =
              error instanceof VttApiError && error.status === 401
                ? "That credential is not recognized for this table."
                : errorMessage(error);
            setLoadError(message);
            throw new Error(message);
          } finally {
            setCredentialPending(false);
          }
        }}
      />
    );
  }
  if (loadError && !view) {
    return (
      <ErrorView
        message={loadError}
        onRetry={() => {
          void refresh(true).catch(() => undefined);
        }}
      />
    );
  }
  if (!view) {
    return <ErrorView message="No session view was returned." onRetry={() => void refresh(true)} />;
  }
  if (!tableIdentity) {
    return (
      <ErrorView
        message="The service did not return a participant identity."
        onRetry={() =>
          void loadTableConnection(bearerToken)
            .then((connection) => adoptConnection(connection, bearerToken))
            .catch(() => undefined)
        }
      />
    );
  }
  const selectedActor =
    view.projection.actors[selectedActorId] ??
    Object.values(view.projection.actors)[0];
  const visibleSelectedActorId = selectedActor?.actor_id ?? "";

  const role = tableIdentity.current_participant.role;
  const canManage = role === "gm";
  const initiativeSlot = (
    <InitiativePanel
          projection={view.projection}
          selectedActorId={visibleSelectedActorId}
          onSelect={setSelectedActorId}
          versions={view.versions}
          canManage={canManage}
          pending={pending === "combat"}
          error={combatControlError}
          onCombatControl={handleCombatControl}
        />
  );
  const mapSlot = activeBoard ? <TacticalMap
            scene={activeBoard.scene}
            mapMetadata={activeBoard.map_metadata}
            mapUrl={activeMapAsset.url}
            mapLoadError={activeMapAsset.error}
            projection={view.projection}
            tokens={tacticalTokens}
            tokenStatus={
              tableIdentity.current_participant.role === "gm"
                ? sharedTokens.status
                : sharedVisibility.status
            }
            tokenError={
              tableIdentity.current_participant.role === "gm"
                ? sharedTokens.error
                : sharedVisibility.error
            }
            visibilityProjection={tacticalVisibility}
            visibilitySources={sharedVisibility.sources}
            visibilityStatus={sharedVisibility.status}
            visibilityError={sharedVisibility.error}
            showVisibilityMask={showVisibilityMask}
            selectedActorId={visibleSelectedActorId}
            selectableTargetIds={targetOptions}
            selectedTargetId={selectedTargetId}
            reachableCells={reachableCells}
            movementPlan={movementPlan}
            measureMode={measureMode}
            measurement={measurement}
            pingMode={activePingMode}
            templateMode={activeTemplateMode}
            templateKind={templateKind}
            templateStart={templateStart}
            templateDimensionFt={templateDimensionFt}
            templateAngleDegrees={templateAngleDegrees}
            pings={sharedAnnotations.pings}
            templates={sharedAnnotations.templates}
            drawings={sharedAnnotations.drawings}
            journalDocuments={sharedJournal.documents}
            onJournalDocumentSelect={setSelectedJournalDocumentId}
            sharedCamera={sharedPresentation.camera}
            followSharedCamera={sharedPresentation.followCamera}
            drawingTool={{
              ...drawingSettings,
              active: activeDrawingMode,
              pointCount: drawingPoints.length,
              error: drawingPlacementError,
            }}
            annotations={sharedAnnotations.annotations}
            selectedAnnotationId={resolvedSelectedAnnotationId}
            annotationStatus={sharedAnnotations.status}
            annotationError={sharedAnnotations.error}
            annotationOperation={sharedAnnotations.operation}
            annotationCanMutate={sharedAnnotations.canMutate}
            annotationCanManage={sharedAnnotations.canManageAnnotation}
            currentParticipantId={
              tableIdentity.current_participant.participant_id
            }
            templatePlacementError={templatePlacementError}
            onTokenSelect={setSelectedActorId}
            onTargetSelect={handleTargetSelect}
            onCellSelect={handleMapCellSelect}
            onGridlessPointSelect={handleGridlessPointSelect}
            onMeasureToggle={toggleMeasureMode}
            onMeasureClear={() =>
              setMeasurement({ ...EMPTY_GRID_MEASUREMENT })
            }
            onPingToggle={togglePingMode}
            onTemplateToggle={toggleTemplateMode}
            onTemplateKindChange={selectTemplateKind}
            onTemplateDimensionChange={setTemplateDimensionFt}
            onTemplateAngleChange={setTemplateAngleDegrees}
            onTemplateCancelStart={() => {
              setTemplateStart(null);
              setTemplatePlacementError(null);
            }}
            onDrawingToggle={toggleDrawingMode}
            onDrawingSettingsChange={changeDrawingSettings}
            onDrawingFinish={finishFreehandDrawing}
            onDrawingCancel={() => {
              setDrawingPoints([]);
              setDrawingPlacementError(null);
            }}
            onUpdateSelectedDrawing={updateSelectedDrawing}
            onUnlockSelectedDrawing={unlockSelectedDrawing}
            onAnnotationSelect={selectManagedAnnotation}
            onRemoveSelected={() => {
              if (
                !resolvedSelectedAnnotationId ||
                (resolvedSelectedAnnotation &&
                  isLockedDrawingAnnotation(resolvedSelectedAnnotation))
              ) return;
              void sharedAnnotations
                .removeAnnotation(resolvedSelectedAnnotationId)
                .catch(() => undefined);
            }}
            onClearLocal={() => {
              void sharedAnnotations
                .clearLocalAnnotations()
                .catch(() => undefined);
            }}
            onAnnotationRetry={sharedAnnotations.retry}
          /> : (
            <section
              className="panel board-unavailable"
              role={boardPresentation.status === "error" ? "alert" : "status"}
              aria-live="polite"
            >
              <p className="eyebrow">Tactical surface</p>
              <h2>{boardPresentation.status === "error" ? "Board unavailable" : "Loading active board…"}</h2>
              <p>
                Grid, tokens, movement, and map tools remain disabled until the
                authoritative active-scene calibration is available.
              </p>
            </section>
          );
  const actionSlot = selectedActor ? (
    <CommandPanel
      view={view}
      selectedActor={selectedActor}
      selectedActionName={selectedActionName}
      selectedTargetId={selectedTargetId}
      movementPlan={movementPlan}
      preview={preview}
      fingerprint={fingerprint}
      pending={pending}
      commandError={commandError}
      canAdmin={canManage}
      canControlActiveActor={canControlActiveActor}
      onActionSelect={handleActionSelect}
      onTargetSelect={handleTargetSelect}
      onStart={() => void handleStart()}
      onPreview={() => void handlePreview()}
      onCommit={() => void handleCommit()}
    />
  ) : (
    <aside className="panel command-panel perception-limited-panel" role="status">
      <p className="eyebrow">Player view</p>
      <h2>No combatant is currently perceptible.</h2>
      <p>
        The board remains live. Combat identities and controls appear only
        when the server-authoritative token projection makes them visible.
      </p>
    </aside>
  );
  const workspacePanels: VttShellPanel[] = [
    {
      id: "events",
      label: "Rules",
      modes: ["play"],
      content: <EventLog events={events} />,
    },
    {
      id: "chat",
      label: "Chat",
      modes: ["play"],
      content: (
        <VttChatPanel
          sessionId={view.session_id}
          bearerToken={bearerToken}
          table={tableIdentity}
        />
      ),
    },
    {
      id: "participants",
      label: "People",
      modes: ["play"],
      content: (
        <VttPresencePanel
          sessionId={view.session_id}
          bearerToken={bearerToken}
          table={tableIdentity}
        />
      ),
    },
    {
      id: "journal",
      label: "Journal",
      modes: ["play", "prepare"],
      content: (
        <VttJournalPanel
          sessionId={view.session_id}
          bearerToken={bearerToken}
          table={tableIdentity}
          controller={sharedJournal}
          requestedDocumentId={selectedJournalDocumentId}
          activeSceneId={activeBoard?.scene.scene_id}
          activeSceneOriginFt={activeBoard ? [
            activeBoard.scene.origin_ft.x_ft,
            activeBoard.scene.origin_ft.y_ft,
            activeBoard.scene.origin_ft.z_ft,
          ] : undefined}
          onDocumentSelect={setSelectedJournalDocumentId}
        />
      ),
    },
    {
      id: "sound",
      label: "Sound & view",
      modes: ["play", "prepare"],
      content: (
        <VttPresentationPanel
          table={tableIdentity}
          bearerToken={bearerToken}
          activeSceneId={activeBoard?.scene.scene_id ?? null}
          controller={sharedPresentation}
        />
      ),
    },
    {
      id: "scenes",
      label: "Scenes",
      modes: ["prepare"],
      roles: ["gm"],
      content: (
        <VttScenesPanel
            table={tableIdentity}
            scenes={sharedScenes}
            assets={sharedMapAssets}
          />
      ),
    },
    {
      id: "tokens",
      label: "Tokens",
      modes: ["prepare"],
      roles: ["gm"],
      content: activeBoard ? <VttTokensPanel
            table={tableIdentity}
            scene={activeBoard.scene}
            mapMetadata={activeBoard.map_metadata}
            actors={view.projection.actors}
            tokens={sharedTokens}
          /> : <p role="status">Tokens are available after the active board loads.</p>,
    },
    {
      id: "visibility",
      label: "Lighting & fog",
      modes: ["prepare"],
      roles: ["gm"],
      content: activeBoard ? <VttVisibilityPanel
            table={tableIdentity}
            mapMetadata={activeBoard.map_metadata}
            tokens={sharedTokens.view?.tokens ?? []}
            visibility={sharedVisibility}
          /> : <p role="status">Visibility tools are available after the active board loads.</p>,
    },
  ];
  const connectionLabel = [
    streamStatus === "live"
      ? "Events live"
      : streamStatus === "invalid"
        ? "Stream invalid"
        : streamStatus === "reconnecting"
          ? "Reconnecting"
          : "Connecting",
    `Revision ${view.revision}`,
    phaseLabel(view.projection.phase),
    `${titleCase(role)} ${tableIdentity.current_participant.display_name}`,
    `Round ${view.projection.round_number} of ${view.projection.max_rounds}`,
  ].join(" · ");

  return (
    <div className="table-app">
      {loadError ? (
        <div className="stale-banner" role="alert">
          <span>{loadError}</span>
          <button type="button" onClick={() => void refresh().catch(() => undefined)}>
            Retry refresh
          </button>
        </div>
      ) : null}
      <VttShell
        role={role}
        worldName="Echo Vault"
        sceneName={activeBoard?.scene.name ?? null}
        connectionLabel={connectionLabel}
        mapSlot={mapSlot}
        actionSlot={actionSlot}
        initiativeSlot={initiativeSlot}
        panels={workspacePanels}
      />
    </div>
  );
}
