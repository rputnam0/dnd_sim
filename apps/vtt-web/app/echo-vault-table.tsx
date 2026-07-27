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
  feetToCell,
  getSessionView,
  parseVttEvent,
  planGridMovement,
  postCommand,
  VttApiError,
  vttEventsUrl,
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

function eligibleTargets(
  action: ActorAction | undefined,
  activeActor: ActorProjection | undefined,
  actors: Record<string, ActorProjection>,
): ActorProjection[] {
  if (!action || !activeActor) return [];
  const living = Object.values(actors).filter((actor) => !actor.dead);
  if (action.target_mode === "self") return [activeActor];
  if (action.target_mode.includes("enemy")) {
    return living.filter((actor) => actor.team !== activeActor.team);
  }
  if (action.target_mode.includes("ally")) {
    return living.filter((actor) => actor.team === activeActor.team);
  }
  if (action.target_mode === "none") return [];
  return living.filter((actor) => actor.actor_id !== activeActor.actor_id);
}

function selectedTargetsForAction(
  action: ActorAction | undefined,
  activeActor: ActorProjection | undefined,
  selectedTargetId: string | null,
): string[] {
  if (!action || !activeActor) return [];
  if (action.target_mode === "self") return [activeActor.actor_id];
  if (action.target_mode === "none") return [];
  return selectedTargetId ? [selectedTargetId] : [];
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
  eligibleTargetIds,
  selectedTargetId,
  reachableCells,
  movementPlan,
  onTokenSelect,
  onTargetSelect,
  onCellSelect,
}: {
  scene: SquareGridScene;
  projection: EncounterProjection;
  selectedActorId: string;
  eligibleTargetIds: Set<string>;
  selectedTargetId: string | null;
  reachableCells: Set<string>;
  movementPlan: GridMovementPlan | null;
  onTokenSelect: (actorId: string) => void;
  onTargetSelect: (actorId: string) => void;
  onCellSelect: (cell: GridCell) => void;
}) {
  const mapStyle = {
    "--grid-columns": scene.columns,
    "--grid-rows": scene.rows,
  } as CSSProperties;
  const cells = Array.from({ length: scene.columns * scene.rows });

  return (
    <section className="map-panel" aria-labelledby="map-title">
      <div className="map-toolbar">
        <div>
          <p className="eyebrow">Tactical surface</p>
          <h2 id="map-title">{scene.name}</h2>
        </div>
        <div className="map-readouts" aria-label="Map measurements">
          <span>{scene.columns} × {scene.rows}</span>
          <span>{scene.cell_size_ft} ft / cell</span>
          <span>Z 0</span>
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
            return (
              <button
                type="button"
                className={`grid-cell ${reachable ? "is-reachable" : ""} ${selected ? "is-destination" : ""}`}
                role="gridcell"
                aria-label={`Cell ${cellLabel(cell)}${reachable ? ", reachable destination" : ""}${selected ? ", selected destination" : ""}`}
                aria-selected={selected}
                disabled={!reachable}
                onClick={() => onCellSelect(cell)}
                key={`${column}-${row}`}
              >
                <span aria-hidden="true">
                  {row === scene.rows - 1 ? column + 1 : ""}
                </span>
              </button>
            );
          })}

          {projection.initiative_order.map((actorId) => {
            const actor = projection.actors[actorId];
            const cell = feetToCell(scene, actor.position);
            const active = actorId === projection.active_actor_id;
            const selected = actorId === selectedActorId;
            const targetable = eligibleTargetIds.has(actorId);
            const targeted = actorId === selectedTargetId;
            return (
              <button
                key={actorId}
                type="button"
                className={`map-token team-${actor.team} ${active ? "is-active" : ""} ${selected ? "is-selected" : ""} ${targetable ? "is-targetable" : ""} ${targeted ? "is-targeted" : ""} ${actor.dead ? "is-defeated" : ""}`}
                style={{ gridColumn: cell.column + 1, gridRow: cell.row + 1 }}
                onClick={() => {
                  onTokenSelect(actorId);
                  if (targetable) onTargetSelect(actorId);
                }}
                aria-pressed={selected || targeted}
                aria-label={`${actor.name}, ${actor.hp} of ${actor.max_hp} hit points${active ? ", active turn" : ""}${targetable ? ", valid target" : ""}`}
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
          {movementPlan
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
  const selectedAction = activeActor?.actions.find(
    (action) => action.name === selectedActionName,
  );
  const targets = eligibleTargets(selectedAction, activeActor, projection.actors);
  const targetRequired = selectedAction?.target_mode !== "none";
  const canPreview = Boolean(
    activeActor &&
      selectedAction &&
      movementPlan &&
      (!targetRequired || selectedTargetId || selectedAction.target_mode === "self"),
  );
  const canCommit = preview?.fingerprint === fingerprint;
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
            disabled={pending !== null}
            onClick={onStart}
          >
            <span className="play-glyph" aria-hidden="true" />
            {pending === "start" ? "Starting encounter…" : "Start encounter"}
          </button>
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
              {activeActor?.actions.map((action) => (
                <button
                  type="button"
                  key={action.name}
                  className={`action-choice ${action.name === selectedActionName ? "is-selected" : ""}`}
                  onClick={() => onActionSelect(action.name)}
                  aria-pressed={action.name === selectedActionName}
                >
                  <span className="action-symbol" aria-hidden="true">✦</span>
                  <span>
                    <strong>{action.name}</strong>
                    <small>{titleCase(action.action_type)} · {rangeLabel(action)}</small>
                  </span>
                  <i aria-hidden="true" />
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset className="choice-group target-group">
            <legend>3. Select target</legend>
            <div className="target-list">
              {targets.length > 0 ? (
                targets.map((target) => (
                  <button
                    type="button"
                    key={target.actor_id}
                    className={target.actor_id === selectedTargetId ? "is-selected" : ""}
                    onClick={() => onTargetSelect(target.actor_id)}
                    aria-pressed={target.actor_id === selectedTargetId}
                  >
                    <span className={`target-reticle team-${target.team}`} aria-hidden="true" />
                    <span>{target.name}</span>
                    <small>{target.hp} HP</small>
                  </button>
                ))
              ) : (
                <p className="no-targets">This action needs no external target.</p>
              )}
            </div>
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
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingOperation>(null);
  const [selectedActorId, setSelectedActorId] = useState("");
  const [selectedActionName, setSelectedActionName] = useState("");
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [selectedDestination, setSelectedDestination] = useState<GridCell | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [events, setEvents] = useState<LoggedEvent[]>([]);
  const [streamStatus, setStreamStatus] = useState<
    "connecting" | "live" | "reconnecting" | "invalid"
  >("connecting");
  const latestRevisionRef = useRef(0);
  const sessionIdRef = useRef<string | null>(null);
  const eventCursorRef = useRef(0);

  const adoptView = useCallback((nextView: VttSessionView) => {
    const projection = nextView.projection;
    const actorId = projection.active_actor_id ?? projection.initiative_order[0];
    const actor = projection.actors[actorId];
    const firstAction = actor?.actions[0];
    latestRevisionRef.current = nextView.revision;
    sessionIdRef.current = nextView.session_id;
    setView(nextView);
    setSelectedActorId(actorId);
    setSelectedActionName(firstAction?.name ?? "");
    setSelectedTargetId(
      eligibleTargets(firstAction, actor, projection.actors)[0]?.actor_id ?? null,
    );
    setSelectedDestination(
      nextView.scene && actor ? feetToCell(nextView.scene, actor.position) : null,
    );
    setPreview(null);
    setCommandError(null);
  }, []);

  const refresh = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);
    setLoadError(null);
    try {
      const nextView = await getSessionView();
      adoptView(nextView);
      return nextView;
    } catch (error) {
      const message = errorMessage(error);
      setLoadError(message);
      throw error;
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [adoptView]);

  useEffect(() => {
    let active = true;
    getSessionView()
      .then((nextView) => {
        if (active) adoptView(nextView);
      })
      .catch((error) => {
        if (active) setLoadError(errorMessage(error));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [adoptView]);

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
    let closed = false;
    const stream = new EventSource(vttEventsUrl(eventCursorRef.current));

    const receiveEvent = (rawEvent: Event) => {
      try {
        const message = rawEvent as MessageEvent<string>;
        const event = parseVttEvent(JSON.parse(message.data));
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
      } catch {
        setStreamStatus("invalid");
        setLoadError("The live event stream returned invalid public data.");
        stream.close();
      }
    };

    stream.addEventListener("vtt.event", receiveEvent);
    stream.onopen = () => {
      if (!closed) setStreamStatus("live");
    };
    stream.onerror = () => {
      if (!closed) setStreamStatus("reconnecting");
    };
    return () => {
      closed = true;
      stream.removeEventListener("vtt.event", receiveEvent);
      stream.close();
    };
  }, [refresh]);

  const projection = view?.projection;
  const scene = view?.scene ?? null;
  const activeActor =
    projection?.active_actor_id
      ? projection.actors[projection.active_actor_id]
      : undefined;
  const selectedAction = activeActor?.actions.find(
    (action) => action.name === selectedActionName,
  );
  const targetIds = selectedTargetsForAction(
    selectedAction,
    activeActor,
    selectedTargetId,
  );
  const movementPlan = useMemo(() => {
    if (!scene || !activeActor || !selectedDestination) return null;
    try {
      return planGridMovement({
        scene,
        start: activeActor.position,
        destination: selectedDestination,
        movementRemaining: activeActor.movement_remaining,
      });
    } catch {
      return null;
    }
  }, [activeActor, scene, selectedDestination]);
  const reachableCells = useMemo(() => {
    const reachable = new Set<string>();
    if (
      !scene ||
      !activeActor ||
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
            start: activeActor.position,
            destination,
            movementRemaining: activeActor.movement_remaining,
          });
          reachable.add(cellKey(destination));
        } catch {
          // The authoritative preview remains the final legality check.
        }
      }
    }
    return reachable;
  }, [activeActor, projection, scene]);
  const fingerprint = view && activeActor
    ? selectionFingerprint(
        view.revision,
        activeActor.actor_id,
        selectedActionName,
        targetIds,
        movementPlan?.path ?? [],
      )
    : "";
  const targetOptions = useMemo(
    () =>
      new Set(
        projection && activeActor
          ? eligibleTargets(selectedAction, activeActor, projection.actors).map(
              (actor) => actor.actor_id,
            )
          : [],
      ),
    [activeActor, projection, selectedAction],
  );

  const handleActionSelect = (name: string) => {
    if (!projection || !activeActor) return;
    const action = activeActor.actions.find((candidate) => candidate.name === name);
    setSelectedActionName(name);
    setSelectedTargetId(
      eligibleTargets(action, activeActor, projection.actors)[0]?.actor_id ?? null,
    );
    setPreview(null);
    setCommandError(null);
  };

  const handleTargetSelect = (actorId: string) => {
    setSelectedTargetId(actorId);
    setPreview(null);
    setCommandError(null);
  };

  const handleCellSelect = (destination: GridCell) => {
    if (!reachableCells.has(cellKey(destination))) return;
    setSelectedDestination(destination);
    setSelectedActorId(activeActor?.actor_id ?? selectedActorId);
    setPreview(null);
    setCommandError(null);
  };

  const handleStart = async () => {
    if (!view) return;
    setPending("start");
    setCommandError(null);
    try {
      const response = await postCommand(
        buildStartCommand({
          sessionId: view.session_id,
          expectedRevision: view.revision,
        }),
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
    if (!view || !activeActor || !selectedActionName) return;
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
      !selectedActionName ||
      preview?.fingerprint !== fingerprint
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
            eligibleTargetIds={targetOptions}
            selectedTargetId={selectedTargetId}
            reachableCells={reachableCells}
            movementPlan={movementPlan}
            onTokenSelect={setSelectedActorId}
            onTargetSelect={handleTargetSelect}
            onCellSelect={handleCellSelect}
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
