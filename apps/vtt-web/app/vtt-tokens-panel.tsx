"use client";

import { useId, useState, type FormEvent } from "react";

import type { VttTableView } from "./vtt-access";
import type { ActorProjection, SquareGridScene } from "./vtt-client";
import type { VttTokensController } from "./use-vtt-tokens";
import type { TokenRecord } from "./vtt-tokens";
import type { SceneMapMetadata } from "./vtt-scenes";
import {
  boardCellToFeet,
  enumerateBoardCells,
  feetToBoardCell,
  pixelToBoardFeet,
} from "./vtt-board-calibration";

function statusLabel(tokens: VttTokensController): string {
  if (tokens.operation !== null) return `${tokens.operation} token…`;
  if (tokens.status === "loading") return "Loading tokens…";
  if (tokens.status === "connecting") return "Connecting token sync…";
  if (tokens.status === "reconnecting") return "Tokens reconnecting…";
  if (tokens.status === "unavailable") return "Token service unavailable";
  if (tokens.status === "error") return "Token sync interrupted";
  const count = tokens.view?.tokens.length ?? 0;
  return `${count} ${count === 1 ? "token" : "tokens"} visible`;
}

function boardOrigin(scene: SquareGridScene, metadata: SceneMapMetadata) {
  const halfStep = metadata.calibration.distance_ft / 2;
  return [
    scene.origin_ft.x_ft + halfStep,
    scene.origin_ft.y_ft + halfStep,
    scene.origin_ft.z_ft,
  ] as [number, number, number];
}

function initialTokenPose(
  scene: SquareGridScene,
  metadata: SceneMapMetadata,
  actorPosition?: [number, number, number],
): Pick<TokenRecord["pose"], "position_ft" | "occupied_hex_cells"> {
  const calibration = metadata.calibration;
  const origin = boardOrigin(scene, metadata);
  let position = actorPosition;
  if (position === undefined) {
    if (calibration.topology === "gridless") {
      position = pixelToBoardFeet(
        calibration,
        { x_px: calibration.origin_x_px, y_px: calibration.origin_y_px },
        origin,
      );
    } else {
      const firstCell = enumerateBoardCells(
        calibration,
        metadata.width_px,
        metadata.height_px,
      )[0];
      if (firstCell === undefined) throw new Error("The active board has no complete cells");
      position = boardCellToFeet(calibration, firstCell, origin);
    }
  }
  const position_ft = { x_ft: position[0], y_ft: position[1], z_ft: position[2] };
  if (!calibration.topology.startsWith("hex_")) return { position_ft };
  const anchor = feetToBoardCell(calibration, position, origin);
  if (!("q" in anchor)) throw new Error("Hex token placement requires an axial cell");
  return { position_ft, occupied_hex_cells: [anchor] };
}

export function VttTokensPanel({
  table,
  scene,
  mapMetadata,
  actors,
  tokens,
}: {
  table: VttTableView;
  scene: SquareGridScene;
  mapMetadata: SceneMapMetadata;
  actors: Record<string, ActorProjection>;
  tokens: VttTokensController;
}) {
  const titleId = useId();
  const [selectedTokenId, setSelectedTokenId] = useState("");
  const [draft, setDraft] = useState<{
    revision: number;
    token: TokenRecord;
  } | null>(null);
  const [newTokenId, setNewTokenId] = useState("");
  const [newName, setNewName] = useState("");
  const [newActorId, setNewActorId] = useState("");
  const [duplicateId, setDuplicateId] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const visibleTokens = tokens.view?.tokens ?? [];
  const selected =
    visibleTokens.find((token) => token.token_id === selectedTokenId) ??
    visibleTokens[0];
  const editing =
    draft !== null &&
    draft.revision === tokens.view?.revision &&
    draft.token.token_id === selected?.token_id
      ? draft.token
      : selected ?? null;
  const isGm = table.current_participant.role === "gm";

  const reviseDraft = (revise: (current: TokenRecord) => TokenRecord) => {
    if (editing !== null && tokens.view !== null) {
      setDraft({ revision: tokens.view.revision, token: revise(editing) });
    }
  };

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const extent = Math.min(scene.cell_size_ft, 5);
      const actor = newActorId ? actors[newActorId] : undefined;
      const initialPose = initialTokenPose(
        scene,
        mapMetadata,
        actor?.position,
      );
      await tokens.createToken({
        schema_version: "vtt.token_record.v1",
        token_id: newTokenId,
        scene_id: scene.scene_id,
        actor_id: actor?.actor_id ?? null,
        name: newName,
        pose: {
          schema_version: "vtt.token_pose.v1",
          ...initialPose,
          width_ft: extent,
          height_ft: extent,
          rotation_degrees: 0,
          layer: 0,
        },
        visibility: "public",
        locked: false,
        nameplate: "hover",
        show_hp_bar: actor !== undefined,
        aura_radius_ft: 0,
        aura_color: "#4DD7B3",
        condition_labels: [],
      });
      setSelectedTokenId(newTokenId);
      setNewTokenId("");
      setNewName("");
      setNewActorId("");
      setLocalError(null);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "The token could not be created.");
    }
  };

  const update = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (editing === null) return;
    try {
      await tokens.updateToken(editing);
      setLocalError(null);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "The token could not be updated.");
    }
  };

  const duplicate = async () => {
    if (editing === null) return;
    try {
      await tokens.duplicateToken(editing.token_id, duplicateId, editing.pose);
      setSelectedTokenId(duplicateId);
      setDuplicateId("");
      setLocalError(null);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "The token could not be duplicated.");
    }
  };

  const remove = async () => {
    if (selected === undefined) return;
    try {
      await tokens.deleteToken(selected.scene_id, selected.token_id);
      setSelectedTokenId("");
      setLocalError(null);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "The token could not be deleted.");
    }
  };

  const updatePose = (
    field: "x_ft" | "y_ft" | "z_ft" | "width_ft" | "height_ft" | "rotation_degrees" | "layer",
    value: number,
  ) => {
    reviseDraft((current) => {
      if (field === "x_ft" || field === "y_ft" || field === "z_ft") {
        return {
          ...current,
          pose: {
            ...current.pose,
            position_ft: { ...current.pose.position_ft, [field]: value },
          },
        };
      }
      return { ...current, pose: { ...current.pose, [field]: value } };
    });
  };

  return (
    <section className="panel token-panel" aria-labelledby={titleId}>
      <div className="panel-heading token-heading">
        <div>
          <p className="eyebrow">Board pieces</p>
          <h2 id={titleId}>Token workshop</h2>
        </div>
        <span className={`token-status token-status-${tokens.status}`} role="status">
          {statusLabel(tokens)}
        </span>
      </div>

      <div className="token-visible-list" aria-live="polite">
        {visibleTokens.length === 0 ? (
          <p>No tokens are visible in this scene.</p>
        ) : (
          visibleTokens.map((token) => (
            <button
              type="button"
              className={token.token_id === selectedTokenId ? "is-selected" : ""}
              aria-pressed={token.token_id === selectedTokenId}
              onClick={() => {
                setSelectedTokenId(token.token_id);
                setDraft(null);
              }}
              key={token.token_id}
            >
              <strong>{token.name}</strong>
              <small>{token.actor_id ? `Linked · ${token.visibility}` : token.visibility}</small>
            </button>
          ))
        )}
      </div>

      {isGm ? (
        <>
          <form className="token-create-form" onSubmit={(event) => void create(event)}>
            <label>
              New token ID
              <input value={newTokenId} onChange={(event) => setNewTokenId(event.target.value)} />
            </label>
            <label>
              Display name
              <input value={newName} onChange={(event) => setNewName(event.target.value)} />
            </label>
            <label>
              Engine actor
              <select value={newActorId} onChange={(event) => setNewActorId(event.target.value)}>
                <option value="">Unlinked board token</option>
                {Object.values(actors).map((actor) => (
                  <option value={actor.actor_id} key={actor.actor_id}>{actor.name}</option>
                ))}
              </select>
            </label>
            <button type="submit" disabled={!tokens.canMutate || !newTokenId || !newName}>
              Create token
            </button>
          </form>

          {editing ? (
            <form className="token-edit-form" onSubmit={(event) => void update(event)}>
              <div className="token-edit-heading">
                <div>
                  <span>Selected token</span>
                  <strong>{editing.name}</strong>
                  <small>{editing.actor_id ? `Engine linked: ${editing.actor_id}` : "Free board token"}</small>
                </div>
                <label>
                  Name
                  <input
                    value={editing.name}
                    onChange={(event) => reviseDraft((current) => ({ ...current, name: event.target.value }))}
                  />
                </label>
              </div>

              <fieldset className="token-pose-fields">
                <legend>Pose in feet</legend>
                {(["x_ft", "y_ft", "z_ft"] as const).map((field) => (
                  <label key={field}>
                    {field.replace("_ft", "").toUpperCase()}
                    <input
                      type="number"
                      step="0.5"
                      disabled={editing.actor_id !== null}
                      value={editing.pose.position_ft[field]}
                      onChange={(event) => updatePose(field, Number(event.target.value))}
                    />
                  </label>
                ))}
                <label>
                  Width
                  <input type="number" min="0.1" max="500" step="0.5" value={editing.pose.width_ft} onChange={(event) => updatePose("width_ft", Number(event.target.value))} />
                </label>
                <label>
                  Height
                  <input type="number" min="0.1" max="500" step="0.5" value={editing.pose.height_ft} onChange={(event) => updatePose("height_ft", Number(event.target.value))} />
                </label>
                <label>
                  Rotation
                  <input type="number" min="0" max="359.9" step="1" value={editing.pose.rotation_degrees} onChange={(event) => updatePose("rotation_degrees", Number(event.target.value))} />
                </label>
                <label>
                  Layer
                  <input type="number" min="-100" max="100" step="1" value={editing.pose.layer} onChange={(event) => updatePose("layer", Number(event.target.value))} />
                </label>
              </fieldset>

              <div className="token-presentation-fields">
                <label>
                  Visibility
                  <select value={editing.visibility} onChange={(event) => reviseDraft((current) => ({ ...current, visibility: event.target.value as TokenRecord["visibility"] }))}>
                    <option value="public">Everyone</option>
                    {editing.actor_id ? <option value="owners">Owners</option> : null}
                    <option value="gm_only">GM only</option>
                  </select>
                </label>
                <label>
                  Nameplate
                  <select value={editing.nameplate} onChange={(event) => reviseDraft((current) => ({ ...current, nameplate: event.target.value as TokenRecord["nameplate"] }))}>
                    <option value="hidden">Hidden</option>
                    <option value="hover">On hover</option>
                    <option value="always">Always</option>
                  </select>
                </label>
                <label>
                  Aura radius
                  <input type="number" min="0" max="1000" step="0.5" value={editing.aura_radius_ft} onChange={(event) => reviseDraft((current) => ({ ...current, aura_radius_ft: Number(event.target.value) }))} />
                </label>
                <label>
                  Aura color
                  <input type="color" value={editing.aura_color} onChange={(event) => reviseDraft((current) => ({ ...current, aura_color: event.target.value.toUpperCase() }))} />
                </label>
                <label className="token-check"><input type="checkbox" checked={editing.locked} onChange={(event) => reviseDraft((current) => ({ ...current, locked: event.target.checked }))} /> Locked</label>
                <label className="token-check"><input type="checkbox" checked={editing.show_hp_bar} onChange={(event) => reviseDraft((current) => ({ ...current, show_hp_bar: event.target.checked }))} /> HP bar</label>
              </div>

              <div className="token-edit-actions">
                <button type="submit" disabled={!tokens.canMutate}>Update token</button>
                <label>
                  Copy ID
                  <input value={duplicateId} onChange={(event) => setDuplicateId(event.target.value)} />
                </label>
                <button type="button" disabled={!tokens.canMutate || !duplicateId} onClick={() => void duplicate()}>Duplicate</button>
                <button type="button" className="token-delete" disabled={!tokens.canMutate} onClick={() => void remove()}>Delete</button>
              </div>
            </form>
          ) : null}
        </>
      ) : (
        <p className="token-permission-note">The Game Master controls token presentation.</p>
      )}

      {localError ?? tokens.error ? (
        <p className="token-error" role="alert">{localError ?? tokens.error}</p>
      ) : null}
      {tokens.status === "error" || tokens.status === "unavailable" ? (
        <button type="button" className="token-retry" onClick={tokens.retry}>Retry token sync</button>
      ) : null}
    </section>
  );
}
