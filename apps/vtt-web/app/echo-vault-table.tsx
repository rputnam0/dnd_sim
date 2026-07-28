"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import {
  buildDeclarationCommand,
  buildStartCommand,
  cellToFeet,
  feetToCell,
  getSessionView,
  planGridMovement,
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
  gridMeasurementDistanceFeet,
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
import type { PingAnnotation, VttAnnotation } from "./vtt-annotations";
import {
  buildAreaTemplateAnnotation,
  projectAreaTemplateToGrid,
  type AreaTemplateAnnotation,
  type AreaTemplateGridGeometry,
  type AreaTemplateKind,
} from "./vtt-template-geometry";
import { VttChatPanel } from "./vtt-chat-panel";
import { VttAccessGate } from "./vtt-access-gate";
import {
  canControlActor,
  getTableView,
  type VttTableView,
} from "./vtt-access";

type PendingOperation = "start" | "preview" | "commit" | null;

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
    annotation.annotation_type === "circle_template"
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

function isInteractiveControl(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(
    target.closest(
      "input, textarea, select, button, a[href], summary, [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='button'], [role='combobox']",
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
  scene: SquareGridScene,
  measurement: GridMeasurement,
  measureMode: boolean,
): string {
  if (measurement.start === null) {
    return measureMode ? "Choose any start cell" : "Ruler ready";
  }
  if (measurement.end === null) {
    return measureMode
      ? `Start ${cellLabel(measurement.start)} · choose any end cell`
      : `Start ${cellLabel(measurement.start)} saved`;
  }
  const distance = gridMeasurementDistanceFeet(scene, measurement);
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
        <p className="eyebrow">Solo Table / Encounter 01</p>
        <h1>Synchronizing the Echo Vault</h1>
        <p>Reading the public table projection and calibrating the grid.</p>
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
        <h1>The vault is out of phase.</h1>
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
}: {
  projection: EncounterProjection;
  selectedActorId: string;
  onSelect: (actorId: string) => void;
  versions: VttSessionView["versions"];
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

function TacticalMap({
  scene,
  projection,
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
  onMeasureToggle,
  onMeasureClear,
  onPingToggle,
  onTemplateToggle,
  onTemplateKindChange,
  onTemplateDimensionChange,
  onTemplateAngleChange,
  onTemplateCancelStart,
  onAnnotationSelect,
  onRemoveSelected,
  onClearLocal,
  onAnnotationRetry,
}: {
  scene: SquareGridScene;
  projection: EncounterProjection;
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
  onMeasureToggle: () => void;
  onMeasureClear: () => void;
  onPingToggle: () => void;
  onTemplateToggle: () => void;
  onTemplateKindChange: (kind: AreaTemplateKind) => void;
  onTemplateDimensionChange: (value: number) => void;
  onTemplateAngleChange: (value: number) => void;
  onTemplateCancelStart: () => void;
  onAnnotationSelect: (annotationId: string) => void;
  onRemoveSelected: () => void;
  onClearLocal: () => void;
  onAnnotationRetry: () => void;
}) {
  const mapStyle = {
    "--grid-columns": scene.columns,
    "--grid-rows": scene.rows,
  } as CSSProperties;
  const cells = Array.from({ length: scene.columns * scene.rows });
  const measurePrompt = measurementStatus(scene, measurement, measureMode);
  const renderedPings = pings.flatMap((ping) => {
    try {
      return [{ ping, cell: feetToCell(scene, [ping.position.x_ft, ping.position.y_ft, ping.position.z_ft]) }];
    } catch {
      return [];
    }
  });
  const renderedTemplates = templates.flatMap((template) => {
    try {
      return [{ template, geometry: projectAreaTemplateToGrid(scene, template) }];
    } catch {
      return [];
    }
  });
  const selectedAnnotation = annotations.find(
    (annotation) => annotation.annotation_id === selectedAnnotationId,
  );
  const selectedCanManage = Boolean(
    selectedAnnotation && annotationCanManage(selectedAnnotation.author_id),
  );
  const ownedAnnotationCount = annotations.filter(
    (annotation) => annotation.author_id === currentParticipantId,
  ).length;

  return (
    <section className="map-panel" aria-labelledby="map-title">
      <div className="map-toolbar">
        <div>
          <p className="eyebrow">Tactical surface</p>
          <h2 id="map-title">{scene.name}</h2>
        </div>
        <div className="map-toolbar-tools">
          <div className="map-readouts" aria-label="Map measurements">
            <span>{scene.columns} × {scene.rows}</span>
            <span>{scene.cell_size_ft} ft / cell</span>
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
              disabled={measurement.start === null}
              onClick={onMeasureClear}
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
              disabled={!annotationCanMutate}
              onClick={onTemplateToggle}
            >
              <span aria-hidden="true">◇</span>
              Template
              <kbd>T</kbd>
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
          <output className="measure-output" aria-live="polite">
            {templateMode
              ? templatePrompt(templateKind, templateStart)
              : pingMode
              ? "Ping mode · choose any map cell"
              : measurePrompt}
          </output>
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
              disabled={!selectedCanManage || !annotationCanMutate}
              onClick={onRemoveSelected}
            >
              Remove selected
            </button>
            <button
              type="button"
              disabled={ownedAnnotationCount === 0 || !annotationCanMutate}
              onClick={onClearLocal}
            >
              Clear mine ({ownedAnnotationCount})
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
          className="square-grid"
          style={mapStyle}
          role="grid"
          aria-label={`${scene.name}, ${scene.columns} by ${scene.rows} square grid`}
        >
          {cells.map((_, index) => {
            const column = index % scene.columns;
            const row = Math.floor(index / scene.columns);
            const cell = { column, row };
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
            return (
              <button
                type="button"
                className={`grid-cell ${reachable ? "is-reachable" : ""} ${selected ? "is-destination" : ""} ${measureMode ? "is-measuring" : ""} ${pingMode ? "is-pinging" : ""} ${templateMode ? "is-templating" : ""} ${isTemplateStart ? "is-template-start" : ""} ${measureStart ? "is-measure-start" : ""} ${measureEnd ? "is-measure-end" : ""}`}
                role="gridcell"
                aria-label={`Cell ${cellLabel(cell)}${reachable ? ", reachable destination" : ", not a reachable destination"}${selected ? ", selected destination" : ""}${measureStart ? ", measure start" : ""}${measureEnd ? ", measure end" : ""}${isTemplateStart ? ", template start" : ""}${measureMode ? `, ${measureAction}` : ""}${pingAction}${templateAction}`}
                aria-selected={selected}
                disabled={!templateMode && !pingMode && !measureMode && !reachable}
                onClick={() => onCellSelect(cell)}
                key={`${column}-${row}`}
              >
                <span className="grid-coordinate" aria-hidden="true">
                  {row === scene.rows - 1 ? column + 1 : ""}
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

          {renderedPings.map(({ ping, cell }) => (
            <span
              className="ping-marker"
              style={{
                gridColumn: cell.column + 1,
                gridRow: cell.row + 1,
                "--ping-duration": `${ping.duration_ms}ms`,
              } as CSSProperties}
              role="img"
              aria-label={`Shared ping by ${ping.author_id} at cell ${cellLabel(cell)}`}
              key={ping.annotation_id}
            >
              <i aria-hidden="true" />
              <i aria-hidden="true" />
              <b aria-hidden="true" />
            </span>
          ))}

          {projection.initiative_order.map((actorId) => {
            const actor = projection.actors[actorId];
            const cell = feetToCell(scene, actor.position);
            const active = actorId === projection.active_actor_id;
            const selected = actorId === selectedActorId;
            const targetable = selectableTargetIds.has(actorId);
            const targeted = actorId === selectedTargetId;
            return (
              <button
                key={actorId}
                type="button"
                className={`map-token team-${actor.team} ${active ? "is-active" : ""} ${selected ? "is-selected" : ""} ${targetable ? "is-targetable" : ""} ${targeted ? "is-targeted" : ""} ${actor.dead ? "is-defeated" : ""} ${measureMode ? "is-measuring" : ""} ${pingMode ? "is-pinging" : ""} ${templateMode ? "is-templating" : ""}`}
                style={{ gridColumn: cell.column + 1, gridRow: cell.row + 1 }}
                onClick={() => {
                  if (pingMode || measureMode || templateMode) {
                    onCellSelect(cell);
                    return;
                  }
                  onTokenSelect(actorId);
                  if (targetable) onTargetSelect(actorId);
                }}
                aria-pressed={selected || targeted}
                aria-label={`${actor.name}, ${actor.hp} of ${actor.max_hp} hit points${active ? ", active turn" : ""}${targetable ? ", server-selectable target" : ""}${measureMode ? `, ${measurement.start !== null && measurement.end === null ? "select measure end" : "select measure start"} at ${cellLabel(cell)}` : ""}${pingMode ? `, place shared ping at ${cellLabel(cell)}` : ""}${templateMode ? `, ${templatePrompt(templateKind, templateStart).toLowerCase()} at ${cellLabel(cell)}` : ""}`}
              >
                <span className="token-orbit" aria-hidden="true" />
                <span className="token-face">{initials(actor.name)}</span>
                <span className="token-hp" aria-hidden="true">
                  <i style={{ width: `${Math.max(0, (actor.hp / actor.max_hp) * 100)}%` }} />
                </span>
                <span className="token-name">{actor.name.split(" ")[0]}</span>
              </button>
            );
          })}

          {measurement.start !== null && measurement.end !== null ? (
            <svg
              className="measurement-line"
              viewBox={`0 0 ${scene.columns} ${scene.rows}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <line
                x1={measurement.start.column + 0.5}
                y1={measurement.start.row + 0.5}
                x2={measurement.end.column + 0.5}
                y2={measurement.end.row + 0.5}
              />
            </svg>
          ) : null}
          {measurement.start !== null ? (
            <span
              className="measure-marker measure-marker-start"
              style={{
                gridColumn: measurement.start.column + 1,
                gridRow: measurement.start.row + 1,
              }}
              aria-hidden="true"
            >
              S
            </span>
          ) : null}
          {measurement.end !== null ? (
            <span
              className="measure-marker measure-marker-end"
              style={{
                gridColumn: measurement.end.column + 1,
                gridRow: measurement.end.row + 1,
              }}
              aria-hidden="true"
            >
              E
            </span>
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
          {templateMode
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
          events.map(({ id, source, event }, index) => (
            <article className={`event-entry event-${source}`} key={id}>
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
            </article>
          ))
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
  const [selectedAnnotationId, setSelectedAnnotationId] = useState("");
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
  const sharedAnnotations = useVttAnnotations({
    sessionId: view?.session_id ?? null,
    sceneId: view?.scene?.scene_id ?? null,
    bearerToken,
    participant: tableIdentity?.current_participant ?? null,
  });
  const activePingMode = pingMode && sharedAnnotations.available;
  const activeTemplateMode = templateMode && sharedAnnotations.available;
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

  const toggleMeasureMode = useCallback(() => {
    setMeasureMode((current) => !current);
    setPingMode(false);
    setTemplateMode(false);
    setTemplateStart(null);
    setTemplatePlacementError(null);
  }, []);

  const togglePingMode = useCallback(() => {
    if (!sharedAnnotations.canPlace) return;
    setPingMode((current) => !current);
    setMeasureMode(false);
    setTemplateMode(false);
    setTemplateStart(null);
    setTemplatePlacementError(null);
  }, [sharedAnnotations.canPlace]);

  const toggleTemplateMode = useCallback(() => {
    if (!sharedAnnotations.canMutate) return;
    setTemplateMode((current) => !current);
    setMeasureMode(false);
    setPingMode(false);
    setTemplateStart(null);
    setTemplatePlacementError(null);
  }, [sharedAnnotations.canMutate]);

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

    window.addEventListener("keydown", handleMeasureShortcut);
    window.addEventListener("keydown", handlePingShortcut);
    window.addEventListener("keydown", handleTemplateShortcut);
    return () => {
      window.removeEventListener("keydown", handleMeasureShortcut);
      window.removeEventListener("keydown", handlePingShortcut);
      window.removeEventListener("keydown", handleTemplateShortcut);
    };
  }, [
    sharedAnnotations.canMutate,
    sharedAnnotations.canPlace,
    toggleMeasureMode,
    togglePingMode,
    toggleTemplateMode,
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
      nextView.scene && actor
        ? feetToCell(
            nextView.scene,
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
  const scene = view?.scene ?? null;
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
  const movementPlan = useMemo(() => {
    if (!scene || !choices || !selectedDestination) return null;
    try {
      return planGridMovement({
        scene,
        start: choices.movement.origin,
        destination: selectedDestination,
        movementRemaining: choices.movement.remaining_ft,
      });
    } catch {
      return null;
    }
  }, [choices, scene, selectedDestination]);
  const reachableCells = useMemo(() => {
    const reachable = new Set<string>();
    if (
      !scene ||
      !activeActor ||
      !choices ||
      projection?.phase !== "awaiting_declaration"
    ) {
      return reachable;
    }
    const occupied = new Set(
      Object.values(projection.actors)
        .filter(
          (actor) =>
            actor.actor_id !== activeActor.actor_id && !actor.dead,
        )
        .map((actor) => cellKey(feetToCell(scene, actor.position))),
    );
    for (let row = 0; row < scene.rows; row += 1) {
      for (let column = 0; column < scene.columns; column += 1) {
        const destination = { column, row };
        if (occupied.has(cellKey(destination))) continue;
        try {
          planGridMovement({
            scene,
            start: choices.movement.origin,
            destination,
            movementRemaining: choices.movement.remaining_ft,
          });
          reachable.add(cellKey(destination));
        } catch {
          // The authoritative preview remains the final legality check.
        }
      }
    }
    return reachable;
  }, [activeActor, choices, projection, scene]);
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

  const handleMapCellSelect = (cell: GridCell) => {
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
      if (scene && sharedAnnotations.canPlace) {
        void sharedAnnotations
          .placePing(cellToFeet(scene, cell))
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
  if (!view.scene) {
    return (
      <ErrorView
        message="The service is online, but no square-grid scene is attached to this session."
        onRetry={() => void refresh(true).catch(() => undefined)}
      />
    );
  }

  const selectedActor =
    view.projection.actors[selectedActorId] ??
    Object.values(view.projection.actors)[0];

  return (
    <div className="table-app">
      <a className="skip-link" href="#tactical-map">Skip to tactical map</a>
      <header className="topbar">
        <div className="brand-lockup">
          <InstrumentMark />
          <div>
            <p>Solo Table / Encounter 01</p>
            <h1>Echo Vault</h1>
          </div>
        </div>

        <div className="session-strip" aria-label="Session status">
          <div>
            <span
              className={`signal-dot stream-${streamStatus}`}
              aria-hidden="true"
            />
            <span>
              {streamStatus === "live"
                ? "Events live"
                : streamStatus === "invalid"
                  ? "Stream invalid"
                  : streamStatus === "reconnecting"
                    ? "Reconnecting"
                    : "Connecting"}
            </span>
          </div>
          <i aria-hidden="true" />
          <div><span>Revision</span><strong>{view.revision}</strong></div>
          <i aria-hidden="true" />
          <div><span>Status</span><strong>{phaseLabel(view.projection.phase)}</strong></div>
          <i aria-hidden="true" />
          <div>
            <span>{titleCase(tableIdentity.current_participant.role)}</span>
            <strong>{tableIdentity.current_participant.display_name}</strong>
          </div>
        </div>

        <div className="topbar-round">
          <span>Round</span>
          <strong>{String(view.projection.round_number).padStart(2, "0")}</strong>
          <small>/ {String(view.projection.max_rounds).padStart(2, "0")}</small>
        </div>
      </header>

      {loadError ? (
        <div className="stale-banner" role="alert">
          <span>{loadError}</span>
          <button type="button" onClick={() => void refresh().catch(() => undefined)}>
            Retry refresh
          </button>
        </div>
      ) : null}

      <main className="table-layout">
        <InitiativePanel
          projection={view.projection}
          selectedActorId={selectedActor.actor_id}
          onSelect={setSelectedActorId}
          versions={view.versions}
        />

        <div className="center-column" id="tactical-map">
          <TacticalMap
            scene={view.scene}
            projection={view.projection}
            selectedActorId={selectedActor.actor_id}
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
            onAnnotationSelect={setSelectedAnnotationId}
            onRemoveSelected={() => {
              if (!resolvedSelectedAnnotationId) return;
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
          />
          <VttChatPanel
            sessionId={view.session_id}
            bearerToken={bearerToken}
            table={tableIdentity}
          />
          <EventLog events={events} />
        </div>

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
          canAdmin={tableIdentity.current_participant.role === "gm"}
          canControlActiveActor={canControlActiveActor}
          onActionSelect={handleActionSelect}
          onTargetSelect={handleTargetSelect}
          onStart={() => void handleStart()}
          onPreview={() => void handlePreview()}
          onCommit={() => void handleCommit()}
        />
      </main>

      <footer className="table-footer">
        <span>Echo Vault tactical link</span>
        <span>Engine projection only</span>
        <code>{view.session_id}</code>
      </footer>
    </div>
  );
}
