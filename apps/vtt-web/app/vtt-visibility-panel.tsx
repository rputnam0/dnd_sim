"use client";

import { useMemo, useState, type FormEvent } from "react";

import type { VttTableView } from "./vtt-access";
import type { VttVisibilityController } from "./use-vtt-visibility";
import type { TokenRecord } from "./vtt-tokens";
import type { SceneMapMetadata } from "./vtt-scenes";
import type {
  FogOperation,
  LightEmitter,
  SceneEnvironment,
  SightBarrier,
  TokenVision,
  VisibilityRecord,
} from "./vtt-visibility";

function recordLabel(record: VisibilityRecord): string {
  if (record.record_type === "barrier") {
    return `${record.behavior} · ${record.portal_state ?? "fixed"}`;
  }
  if (record.record_type === "light") return `${record.shape} light · ${record.dim_radius_ft} ft`;
  if (record.record_type === "token_vision") return `token sense · ${record.token_id}`;
  if (record.record_type === "fog_operation") return `${record.operation} · step ${record.operation_index}`;
  return `${record.darkness} · ${record.shared_vision.replace("_", " ")}`;
}

function operationLabel(visibility: VttVisibilityController): string {
  if (visibility.operation === "saving") return "Saving visibility…";
  if (visibility.operation === "deleting") return "Deleting record…";
  if (visibility.operation === "toggling") return "Changing door…";
  if (visibility.operation === "undoing") return "Appending fog undo…";
  if (visibility.status === "live") return `Visibility live · revision ${visibility.catalog?.revision ?? 0}`;
  if (visibility.status === "loading") return "Loading visibility editor…";
  if (visibility.status === "connecting") return "Connecting visibility updates…";
  if (visibility.status === "reconnecting") return "Visibility updates reconnecting…";
  return visibility.error ?? "Visibility editor unavailable.";
}

function number(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function VttVisibilityPanel({
  table,
  mapMetadata,
  tokens,
  visibility,
}: {
  table: VttTableView;
  mapMetadata: SceneMapMetadata;
  tokens: TokenRecord[];
  visibility: VttVisibilityController;
}) {
  const [darkness, setDarkness] = useState<SceneEnvironment["darkness"]>("bright");
  const [sharedVision, setSharedVision] = useState<SceneEnvironment["shared_vision"]>("owned_only");
  const [barrier, setBarrier] = useState({ x1: "5", y1: "5", x2: "10", y2: "5", behavior: "wall" as SightBarrier["behavior"] });
  const [light, setLight] = useState({ x: "10", y: "10", bright: "10", dim: "20" });
  const [visionTokenId, setVisionTokenId] = useState("");
  const [vision, setVision] = useState({ normal: "60", darkvision: "0", bright: "0", dim: "0" });
  const [fog, setFog] = useState({ x1: "0", y1: "0", x2: "20", y2: "20", operation: "reveal" as FogOperation["operation"] });
  const records = visibility.catalog?.records ?? [];
  const doors = records.filter((record): record is SightBarrier =>
    record.record_type === "barrier" && record.behavior === "door");
  const fogOperations = records
    .filter((record): record is FogOperation => record.record_type === "fog_operation")
    .sort((left, right) => left.operation_index - right.operation_index);
  const latestFog = fogOperations.at(-1) ?? null;
  const playerChoices = table.participants.filter((participant) => participant.role === "player");
  const tokenChoices = useMemo(
    () => tokens.filter((token) => token.actor_id !== null),
    [tokens],
  );
  if (table.current_participant.role !== "gm") return null;

  const submit = (
    event: FormEvent,
    record: VisibilityRecord,
  ) => {
    event.preventDefault();
    void visibility.putRecord(record).catch(() => undefined);
  };
  const sceneId = visibility.catalog?.scene_id ?? "";

  return (
    <section className="panel visibility-panel" aria-labelledby="visibility-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Private scene preparation</p>
          <h2 id="visibility-title">Fog, light &amp; barriers</h2>
        </div>
        <span>{records.length} records</span>
      </div>
      <div className={`visibility-sync visibility-${visibility.status}`} role="status" aria-live="polite">
        {operationLabel(visibility)}
        {(visibility.status === "error" || visibility.status === "unavailable") ? (
          <button type="button" onClick={visibility.retry}>Retry</button>
        ) : null}
      </div>
      {visibility.error ? <p className="annotation-error" role="alert">{visibility.error}</p> : null}

      <div className="visibility-editor-grid">
        <form onSubmit={(event) => submit(event, {
          schema_version: "vtt.scene_environment.v1",
          record_type: "environment",
          record_id: "scene-environment",
          scene_id: sceneId,
          darkness,
          shared_vision: sharedVision,
        })}>
          <fieldset disabled={!visibility.canMutate}>
            <legend>Scene environment</legend>
            <label>Ambient light
              <select value={darkness} onChange={(event) => setDarkness(event.target.value as SceneEnvironment["darkness"])}>
                <option value="bright">Bright</option><option value="dim">Dim</option><option value="darkness">Darkness</option>
              </select>
            </label>
            <label>Shared sight
              <select value={sharedVision} onChange={(event) => setSharedVision(event.target.value as SceneEnvironment["shared_vision"])}>
                <option value="owned_only">Owned tokens only</option><option value="party">Share party sight</option>
              </select>
            </label>
            <button type="submit">Save environment</button>
          </fieldset>
        </form>

        <form onSubmit={(event) => {
          const behavior = barrier.behavior;
          submit(event, {
            schema_version: "vtt.sight_barrier.v1", record_type: "barrier",
            record_id: `barrier-${crypto.randomUUID()}`, scene_id: sceneId,
            start: { x_ft: number(barrier.x1, 0), y_ft: number(barrier.y1, 0) },
            end: { x_ft: number(barrier.x2, 5), y_ft: number(barrier.y2, 0) },
            behavior, blocks_sight: behavior !== "window", blocks_movement: true,
            portal_state: behavior === "door" ? "closed" : null,
          });
        }}>
          <fieldset disabled={!visibility.canMutate}>
            <legend>Barrier segment</legend>
            <div className="visibility-coordinate-row">
              {(["x1", "y1", "x2", "y2"] as const).map((field) => (
                <label key={field}>{field.toUpperCase()} ft
                  <input type="number" step="0.1" value={barrier[field]} onChange={(event) => setBarrier((current) => ({ ...current, [field]: event.target.value }))} />
                </label>
              ))}
            </div>
            <label>Kind
              <select value={barrier.behavior} onChange={(event) => setBarrier((current) => ({ ...current, behavior: event.target.value as SightBarrier["behavior"] }))}>
                <option value="wall">Wall</option><option value="window">Window</option><option value="door">Closed door</option>
              </select>
            </label>
            <button type="submit">Add barrier</button>
          </fieldset>
        </form>

        <form onSubmit={(event) => submit(event, {
          schema_version: "vtt.light_emitter.v1", record_type: "light",
          record_id: `light-${crypto.randomUUID()}`, scene_id: sceneId,
          origin: { x_ft: number(light.x, 0), y_ft: number(light.y, 0) },
          bright_radius_ft: number(light.bright, 0), dim_radius_ft: number(light.dim, 0),
          shape: "circle", direction_degrees: 0, angle_degrees: 360, audience: ["all"],
        } as LightEmitter)}>
          <fieldset disabled={!visibility.canMutate}>
            <legend>Light emitter</legend>
            <div className="visibility-coordinate-row">
              {(["x", "y", "bright", "dim"] as const).map((field) => (
                <label key={field}>{field === "x" || field === "y" ? field.toUpperCase() : field} ft
                  <input type="number" min={field === "x" || field === "y" ? undefined : 0} step="0.5" value={light[field]} onChange={(event) => setLight((current) => ({ ...current, [field]: event.target.value }))} />
                </label>
              ))}
            </div>
            <button type="submit">Add light</button>
          </fieldset>
        </form>

        <form onSubmit={(event) => {
          const tokenId = visionTokenId || tokenChoices[0]?.token_id || "";
          submit(event, {
            schema_version: "vtt.token_vision.v1", record_type: "token_vision",
            record_id: `vision-${tokenId}`, scene_id: sceneId, token_id: tokenId,
            enabled: true, normal_range_ft: number(vision.normal, 0),
            darkvision_range_ft: number(vision.darkvision, 0),
            emitted_bright_radius_ft: number(vision.bright, 0),
            emitted_dim_radius_ft: number(vision.dim, 0),
          } as TokenVision);
        }}>
          <fieldset disabled={!visibility.canMutate || tokenChoices.length === 0}>
            <legend>Token senses</legend>
            <label>Token
              <select value={visionTokenId} onChange={(event) => setVisionTokenId(event.target.value)}>
                {tokenChoices.map((token) => <option value={token.token_id} key={token.token_id}>{token.name}</option>)}
              </select>
            </label>
            <div className="visibility-coordinate-row">
              {(["normal", "darkvision", "bright", "dim"] as const).map((field) => (
                <label key={field}>{field} ft
                  <input type="number" min="0" step="0.5" value={vision[field]} onChange={(event) => setVision((current) => ({ ...current, [field]: event.target.value }))} />
                </label>
              ))}
            </div>
            <button type="submit">Save token senses</button>
          </fieldset>
        </form>

        <form onSubmit={(event) => {
          const x1 = number(fog.x1, 0); const y1 = number(fog.y1, 0);
          const x2 = number(fog.x2, 5); const y2 = number(fog.y2, 5);
          submit(event, {
            schema_version: "vtt.fog_operation.v1", record_type: "fog_operation",
            record_id: `fog-${crypto.randomUUID()}`, scene_id: sceneId,
            operation_index: fogOperations.length + 1, operation: fog.operation,
            polygon: [{ x_ft: x1, y_ft: y1 }, { x_ft: x2, y_ft: y1 }, { x_ft: x2, y_ft: y2 }, { x_ft: x1, y_ft: y2 }],
            inverse_of: null,
          });
        }}>
          <fieldset disabled={!visibility.canMutate}>
            <legend>Manual fog rectangle</legend>
            <label>Operation
              <select value={fog.operation} onChange={(event) => setFog((current) => ({ ...current, operation: event.target.value as FogOperation["operation"] }))}>
                <option value="reveal">Reveal</option><option value="hide">Hide</option>
              </select>
            </label>
            <div className="visibility-coordinate-row">
              {(["x1", "y1", "x2", "y2"] as const).map((field) => (
                <label key={field}>{field.toUpperCase()} ft
                  <input type="number" step="0.1" value={fog[field]} onChange={(event) => setFog((current) => ({ ...current, [field]: event.target.value }))} />
                </label>
              ))}
            </div>
            <div className="visibility-button-row">
              <button type="submit">Append fog operation</button>
              <button type="button" disabled={!latestFog || !visibility.canMutate} onClick={() => latestFog && void visibility.undoFog(latestFog.record_id).catch(() => undefined)}>Undo last fog</button>
            </div>
          </fieldset>
        </form>
      </div>

      <div className="visibility-preview-controls">
        <label>Preview participant
          <select value={visibility.previewParticipantId ?? ""} onChange={(event) => void visibility.loadPreview(event.target.value || null).catch(() => undefined)}>
            <option value="">GM editor view</option>
            {playerChoices.map((participant) => <option value={participant.participant_id} key={participant.participant_id}>{participant.display_name}</option>)}
          </select>
        </label>
        <span role="status">{visibility.preview ? `Preview mask ${visibility.preview.mask_width} × ${visibility.preview.mask_height}` : "No player preview selected"}</span>
      </div>

      <ul className="visibility-record-list" aria-label="Authored visibility records">
        {records.length === 0 ? <li>No visibility records yet. Player maps remain fully obscured.</li> : records.map((record) => (
          <li key={record.record_id}>
            <span><strong>{record.record_id}</strong><small>{recordLabel(record)}</small></span>
            <div>
              {doors.some((door) => door.record_id === record.record_id) && record.record_type === "barrier" ? (
                <button type="button" disabled={!visibility.canMutate} aria-label={`${record.portal_state === "open" ? "Close" : "Open"} door ${record.record_id}`} onClick={() => void visibility.toggleDoor(record.record_id, record.portal_state === "open" ? "closed" : "open").catch(() => undefined)}>
                  {record.portal_state === "open" ? "Close door" : "Open door"}
                </button>
              ) : null}
              {record.record_type !== "fog_operation" ? (
                <button type="button" disabled={!visibility.canMutate} onClick={() => void visibility.deleteRecord(record.record_id).catch(() => undefined)}>Delete</button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      <small className="visibility-budget-note">
        {mapMetadata.width_px} × {mapMetadata.height_px}px source · projection capped at 65,536 samples.
      </small>
    </section>
  );
}
