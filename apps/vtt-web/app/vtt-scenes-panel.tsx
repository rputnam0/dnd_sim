"use client";

import { useId, useState, type FormEvent } from "react";

import type { VttTableView } from "./vtt-access";
import { useVttScenes, type SceneConnectionStatus } from "./use-vtt-scenes";
import {
  buildSceneExportBundle,
  parseSceneExportBundle,
  type SceneRecord,
} from "./vtt-scenes";

function statusLabel(status: SceneConnectionStatus, count: number): string {
  if (status === "loading") return "Loading scenes…";
  if (status === "connecting") return "Connecting scene sync…";
  if (status === "reconnecting") return "Scenes reconnecting…";
  if (status === "unavailable") return "Scene library unavailable";
  if (status === "error") return "Scene sync interrupted";
  return `${count} ${count === 1 ? "scene" : "scenes"} synced`;
}

function downloadScene(scene: SceneRecord): void {
  const bundle = buildSceneExportBundle(scene);
  const href = URL.createObjectURL(
    new Blob([`${JSON.stringify(bundle, null, 2)}\n`], {
      type: "application/json",
    }),
  );
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = `${scene.scene_id}.vtt-scene.json`;
  anchor.click();
  URL.revokeObjectURL(href);
}

export function VttScenesPanel({
  sessionId,
  bearerToken,
  table,
}: {
  sessionId: string;
  bearerToken: string | null;
  table: VttTableView;
}) {
  const scenes = useVttScenes({
    sessionId,
    tableId: table.table_id,
    bearerToken,
    participant: table.current_participant,
  });
  const [sceneId, setSceneId] = useState("");
  const [name, setName] = useState("");
  const [widthPx, setWidthPx] = useState(1920);
  const [heightPx, setHeightPx] = useState(1080);
  const [gridSizePx, setGridSizePx] = useState(70);
  const [gridless, setGridless] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [archiveTargetId, setArchiveTargetId] = useState<string | null>(null);
  const [archiveSuccessorId, setArchiveSuccessorId] = useState("");
  const importId = useId();
  const titleId = useId();
  const view = scenes.view;
  const entries = view?.scenes ?? [];
  const active = entries.find(
    (entry) => entry.scene.scene_id === view?.active_scene_id,
  );
  const archiveTarget = entries.find(
    (entry) => entry.scene.scene_id === archiveTargetId && !entry.archived,
  );
  const archiveTargetIsActive =
    archiveTarget?.scene.scene_id === view?.active_scene_id;
  const archiveSuccessors = entries.filter(
    (entry) =>
      !entry.archived &&
      entry.scene.scene_id !== archiveTarget?.scene.scene_id,
  );

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      await scenes.createScene({
        schema_version: "vtt.scene_record.v1",
        scene_id: sceneId,
        map_metadata: {
          schema_version: "vtt.scene_map_metadata.v1",
          name,
          width_px: widthPx,
          height_px: heightPx,
          grid_size_px: gridSizePx,
          gridless,
        },
      });
      setSceneId("");
      setName("");
      setLocalError(null);
    } catch (error) {
      setLocalError(
        error instanceof Error ? error.message : "The scene could not be created.",
      );
    }
  };

  const archive = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!archiveTarget) return;
    if (archiveTargetIsActive && archiveSuccessorId.length === 0) {
      setLocalError("Choose the next active scene before archiving this one.");
      return;
    }
    try {
      await scenes.archiveScene(
        archiveTarget.scene.scene_id,
        archiveTargetIsActive ? archiveSuccessorId : null,
      );
      setArchiveTargetId(null);
      setArchiveSuccessorId("");
      setLocalError(null);
    } catch (error) {
      setLocalError(
        error instanceof Error ? error.message : "The scene could not be archived.",
      );
    }
  };

  return (
    <section className="panel scene-panel" aria-labelledby={titleId}>
      <div className="panel-heading scene-heading">
        <div>
          <p className="eyebrow">Campaign preparation</p>
          <h2 id={titleId}>Scene library</h2>
        </div>
        <span className={`scene-status scene-status-${scenes.status}`} role="status">
          {statusLabel(scenes.status, entries.length)}
        </span>
      </div>

      {active ? (
        <div className="scene-active-card">
          <span>Active metadata</span>
          <strong>{active.scene.map_metadata.name}</strong>
          <small>
            {active.scene.map_metadata.width_px} × {active.scene.map_metadata.height_px}px
            · {active.scene.map_metadata.gridless
              ? " gridless"
              : ` ${active.scene.map_metadata.grid_size_px}px grid`}
          </small>
        </div>
      ) : (
        <p className="scene-empty">No scene metadata has been created yet.</p>
      )}

      {entries.length > 0 ? (
        <ul className="scene-list">
          {entries.map((entry) => {
            const isActive = entry.scene.scene_id === view?.active_scene_id;
            const hasSuccessor = entries.some(
              (candidate) =>
                !candidate.archived &&
                candidate.scene.scene_id !== entry.scene.scene_id,
            );
            return (
              <li key={entry.scene.scene_id}>
                <div>
                  <strong>{entry.scene.map_metadata.name}</strong>
                  <span>
                    {entry.archived ? "Archived" : isActive ? "Active" : "Available"}
                  </span>
                </div>
                <div className="scene-row-actions">
                  <button
                    type="button"
                    disabled={!scenes.canMutate || entry.archived || isActive}
                    onClick={() => {
                      void scenes.activateScene(entry.scene.scene_id).catch(() => undefined);
                    }}
                  >
                    Activate
                  </button>
                  <button
                    type="button"
                    disabled={!scenes.canMutate || entry.archived}
                    onClick={() => {
                      void scenes
                        .duplicateScene(
                          entry.scene.scene_id,
                          `${entry.scene.scene_id}-copy-${(view?.revision ?? 0) + 1}`,
                          `${entry.scene.map_metadata.name} Copy`,
                        )
                        .catch(() => undefined);
                    }}
                  >
                    Duplicate
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadScene(entry.scene)}
                  >
                    Export
                  </button>
                  <button
                    type="button"
                    disabled={
                      !scenes.canMutate ||
                      entry.archived ||
                      (isActive && !hasSuccessor)
                    }
                    onClick={() => {
                      setArchiveTargetId(entry.scene.scene_id);
                      setArchiveSuccessorId("");
                      setLocalError(null);
                    }}
                  >
                    Archive…
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}

      {archiveTarget ? (
        <form className="scene-archive-confirm" onSubmit={archive}>
          <div>
            <h3>Archive {archiveTarget.scene.map_metadata.name}?</h3>
            <p>
              Archived scene IDs remain reserved. Confirm only when this metadata
              should leave the available scene list.
            </p>
          </div>
          {archiveTargetIsActive ? (
            <label>
              Choose the next active scene
              <select
                value={archiveSuccessorId}
                onChange={(event) => setArchiveSuccessorId(event.target.value)}
                required
                disabled={scenes.operation === "archiving"}
              >
                <option value="">Select a successor</option>
                {archiveSuccessors.map((entry) => (
                  <option key={entry.scene.scene_id} value={entry.scene.scene_id}>
                    {entry.scene.map_metadata.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="scene-archive-actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                setArchiveTargetId(null);
                setArchiveSuccessorId("");
              }}
              disabled={scenes.operation === "archiving"}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button-primary"
              disabled={
                scenes.operation === "archiving" ||
                (archiveTargetIsActive && archiveSuccessorId.length === 0)
              }
            >
              {scenes.operation === "archiving" ? "Archiving…" : "Confirm archive"}
            </button>
          </div>
        </form>
      ) : null}

      {table.current_participant.role === "gm" ? (
        <div className="scene-admin-grid">
          <form className="scene-create-form" onSubmit={create}>
            <h3>Create scene metadata</h3>
            <label>
              Scene ID
              <input
                value={sceneId}
                onChange={(event) => setSceneId(event.target.value)}
                placeholder="moon-temple"
                required
                disabled={!scenes.canMutate}
              />
            </label>
            <label>
              Display name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Moon Temple"
                required
                disabled={!scenes.canMutate}
              />
            </label>
            <div className="scene-number-grid">
              <label>
                Width px
                <input
                  type="number"
                  min={1}
                  max={1_000_000}
                  value={widthPx}
                  onChange={(event) => setWidthPx(Number(event.target.value))}
                  disabled={!scenes.canMutate}
                />
              </label>
              <label>
                Height px
                <input
                  type="number"
                  min={1}
                  max={1_000_000}
                  value={heightPx}
                  onChange={(event) => setHeightPx(Number(event.target.value))}
                  disabled={!scenes.canMutate}
                />
              </label>
              <label>
                Grid px
                <input
                  type="number"
                  min={0.1}
                  max={100_000}
                  step={0.1}
                  value={gridSizePx}
                  onChange={(event) => setGridSizePx(Number(event.target.value))}
                  disabled={!scenes.canMutate}
                />
              </label>
            </div>
            <label className="scene-gridless-toggle">
              <input
                type="checkbox"
                checked={gridless}
                onChange={(event) => setGridless(event.target.checked)}
                disabled={!scenes.canMutate}
              />
              Gridless scene
            </label>
            <button className="button button-secondary" disabled={!scenes.canMutate}>
              {scenes.operation === "creating" ? "Creating…" : "Create scene"}
            </button>
          </form>

          <div className="scene-import-box">
            <h3>Portable metadata</h3>
            <p>Import a strict `.vtt-scene.json` bundle. Map bytes remain separate.</p>
            <label htmlFor={importId} className="button button-secondary">
              {scenes.operation === "importing" ? "Importing…" : "Import scene"}
            </label>
            <input
              id={importId}
              type="file"
              accept="application/json,.json"
              disabled={!scenes.canMutate}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (!file) return;
                void file
                  .text()
                  .then(parseSceneExportBundle)
                  .then(scenes.importScene)
                  .then(() => setLocalError(null))
                  .catch((error) =>
                    setLocalError(
                      error instanceof Error
                        ? error.message
                        : "The scene bundle could not be imported.",
                    ),
                  );
              }}
            />
          </div>
        </div>
      ) : (
        <p className="scene-readonly-note">
          Only Game Masters can create, activate, duplicate, archive, or import scenes.
        </p>
      )}

      {scenes.error || localError ? (
        <div className="scene-error" role="alert">
          <span>{localError ?? scenes.error}</span>
          {scenes.status === "error" || scenes.status === "unavailable" ? (
            <button type="button" onClick={scenes.retry}>Retry</button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
