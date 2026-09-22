"use client";

import { useId, useState, type FormEvent } from "react";

import type { VttTableView } from "./vtt-access";
import type {
  SceneConnectionStatus,
  VttScenesController,
} from "./use-vtt-scenes";
import type { VttMapAssetsController } from "./use-vtt-map-assets";
import {
  buildSceneExportBundle,
  parseSceneExportBundle,
  type SceneRecord,
} from "./vtt-scenes";
import type { BoardTopology } from "./vtt-board-calibration";

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
  table,
  scenes,
  assets,
}: {
  table: VttTableView;
  scenes: VttScenesController;
  assets: VttMapAssetsController;
}) {
  const [sceneId, setSceneId] = useState("");
  const [name, setName] = useState("");
  const [widthPx, setWidthPx] = useState(1920);
  const [heightPx, setHeightPx] = useState(1080);
  const [gridSizePx, setGridSizePx] = useState(70);
  const [topology, setTopology] = useState<BoardTopology>("square");
  const [originXPx, setOriginXPx] = useState(35);
  const [originYPx, setOriginYPx] = useState(35);
  const [distanceFt, setDistanceFt] = useState(5);
  const [assetId, setAssetId] = useState("");
  const [assetAltText, setAssetAltText] = useState("");
  const [assetFile, setAssetFile] = useState<File | null>(null);
  const [calibration, setCalibration] = useState<{
    sceneId: string;
    assetId: string;
    gridSizePx: number;
    topology: BoardTopology;
    originXPx: number;
    originYPx: number;
    distanceFt: number;
  } | null>(null);
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
  const assetRecords = assets.catalog?.assets ?? [];
  const calibrationForActive =
    active && calibration?.sceneId === active.scene.scene_id ? calibration : null;
  const selectedAssetId =
    calibrationForActive?.assetId ?? active?.scene.map_metadata.asset?.asset_id ?? "";
  const attachGridSizePx =
    calibrationForActive?.gridSizePx ?? active?.scene.map_metadata.grid_size_px ?? 70;
  const attachTopology =
    calibrationForActive?.topology ??
    active?.scene.map_metadata.calibration.topology ??
    "square";
  const attachOriginXPx =
    calibrationForActive?.originXPx ??
    active?.scene.map_metadata.calibration.origin_x_px ??
    attachGridSizePx / 2;
  const attachOriginYPx =
    calibrationForActive?.originYPx ??
    active?.scene.map_metadata.calibration.origin_y_px ??
    attachGridSizePx / 2;
  const attachDistanceFt =
    calibrationForActive?.distanceFt ??
    active?.scene.map_metadata.calibration.distance_ft ??
    5;
  const selectedAsset = assetRecords.find(
    (record) => record.reference.asset_id === selectedAssetId,
  );

  const reviseCalibration = (
    patch: Partial<{
      assetId: string;
      gridSizePx: number;
      topology: BoardTopology;
      originXPx: number;
      originYPx: number;
      distanceFt: number;
    }>,
  ) => {
    if (!active) return;
    setCalibration((current) => {
      const base =
        current?.sceneId === active.scene.scene_id
          ? current
          : {
              sceneId: active.scene.scene_id,
              assetId: active.scene.map_metadata.asset?.asset_id ?? "",
              gridSizePx: active.scene.map_metadata.grid_size_px,
              topology: active.scene.map_metadata.calibration.topology,
              originXPx: active.scene.map_metadata.calibration.origin_x_px,
              originYPx: active.scene.map_metadata.calibration.origin_y_px,
              distanceFt: active.scene.map_metadata.calibration.distance_ft,
            };
      return { ...base, ...patch };
    });
  };

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
          gridless: topology === "gridless",
          calibration: {
            schema_version: "vtt.board_calibration.v1",
            topology,
            origin_x_px: originXPx,
            origin_y_px: originYPx,
            cell_extent_px: gridSizePx,
            distance_ft: distanceFt,
          },
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

  const uploadAsset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (assetFile === null) {
      setLocalError("Choose a PNG, JPEG, or WebP map image first.");
      return;
    }
    try {
      const uploaded = await assets.uploadAsset(assetFile, assetId, assetAltText);
      reviseCalibration({ assetId: uploaded.reference.asset_id });
      setAssetId("");
      setAssetAltText("");
      setAssetFile(null);
      setLocalError(null);
    } catch (error) {
      setLocalError(
        error instanceof Error ? error.message : "The map image could not be uploaded.",
      );
    }
  };

  const attachAsset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!active || !selectedAsset) {
      setLocalError("Choose an active scene and uploaded map asset first.");
      return;
    }
    try {
      await scenes.updateScene(active.scene.scene_id, {
        ...active.scene.map_metadata,
        width_px: selectedAsset.width_px,
        height_px: selectedAsset.height_px,
        grid_size_px: attachGridSizePx,
        gridless: attachTopology === "gridless",
        calibration: {
          schema_version: "vtt.board_calibration.v1",
          topology: attachTopology,
          origin_x_px: attachOriginXPx,
          origin_y_px: attachOriginYPx,
          cell_extent_px: attachGridSizePx,
          distance_ft: attachDistanceFt,
        },
        asset: selectedAsset.reference,
      });
      setLocalError(null);
    } catch (error) {
      setLocalError(
        error instanceof Error ? error.message : "The map could not be attached.",
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
          <span>Active scene</span>
          <strong>{active.scene.map_metadata.name}</strong>
          <small>
            {active.scene.map_metadata.width_px} × {active.scene.map_metadata.height_px}px
            · {active.scene.map_metadata.calibration.topology.replace("_", "-")}
            {` · ${active.scene.map_metadata.grid_size_px}px · ${active.scene.map_metadata.calibration.distance_ft} ft`}
            {active.scene.map_metadata.asset ? " · map attached" : " · no map asset"}
          </small>
        </div>
      ) : (
        <p className="scene-empty">No scene has been created yet.</p>
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
            <h3>Create scene</h3>
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
            <label>
              Board topology
              <select
                value={topology}
                onChange={(event) =>
                  setTopology(event.target.value as BoardTopology)
                }
                disabled={!scenes.canMutate}
              >
                <option value="square">Square</option>
                <option value="hex_flat">Flat-top hex</option>
                <option value="hex_pointy">Pointy-top hex</option>
                <option value="gridless">Gridless</option>
              </select>
            </label>
            <div className="scene-number-grid">
              <label>
                Origin X px
                <input
                  type="number"
                  step="any"
                  value={originXPx}
                  onChange={(event) => setOriginXPx(Number(event.target.value))}
                  disabled={!scenes.canMutate}
                />
              </label>
              <label>
                Origin Y px
                <input
                  type="number"
                  step="any"
                  value={originYPx}
                  onChange={(event) => setOriginYPx(Number(event.target.value))}
                  disabled={!scenes.canMutate}
                />
              </label>
              <label>
                Feet / step
                <input
                  type="number"
                  min={0.01}
                  max={100000}
                  step="any"
                  value={distanceFt}
                  onChange={(event) => setDistanceFt(Number(event.target.value))}
                  disabled={!scenes.canMutate}
                />
              </label>
            </div>
            <button className="button button-secondary" disabled={!scenes.canMutate}>
              {scenes.operation === "creating" ? "Creating…" : "Create scene"}
            </button>
          </form>

          <form className="scene-create-form scene-asset-upload" onSubmit={uploadAsset}>
            <h3>Upload map image</h3>
            <label>
              Asset ID
              <input
                value={assetId}
                onChange={(event) => setAssetId(event.target.value)}
                placeholder="moon-temple-map"
                pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
                required
                disabled={!assets.canUpload}
              />
            </label>
            <label>
              Alternative text
              <input
                value={assetAltText}
                onChange={(event) => setAssetAltText(event.target.value)}
                placeholder="A top-down moonlit temple battle map."
                maxLength={240}
                required
                disabled={!assets.canUpload}
              />
            </label>
            <label>
              Image file
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) => setAssetFile(event.target.files?.[0] ?? null)}
                required
                disabled={!assets.canUpload}
              />
            </label>
            <button
              type="submit"
              className="button button-primary"
              disabled={!assets.canUpload || assetFile === null}
            >
              {assets.uploading ? "Uploading…" : "Upload image"}
            </button>
            {assets.error ? <p className="scene-error">{assets.error}</p> : null}
          </form>

          <form className="scene-create-form scene-asset-attach" onSubmit={attachAsset}>
            <h3>Attach and calibrate map</h3>
            <label>
              Uploaded image
              <select
                value={selectedAssetId}
                onChange={(event) => reviseCalibration({ assetId: event.target.value })}
                required
                disabled={!scenes.canMutate || assetRecords.length === 0}
              >
                <option value="">Select an asset</option>
                {assetRecords.map((record) => (
                  <option
                    key={record.reference.asset_id}
                    value={record.reference.asset_id}
                  >
                    {record.reference.asset_id} · {record.width_px} × {record.height_px}px
                  </option>
                ))}
              </select>
            </label>
            <label>
              Grid size in pixels
              <input
                type="number"
                min={0.01}
                max={100000}
                step="any"
                value={attachGridSizePx}
                onChange={(event) =>
                  reviseCalibration({ gridSizePx: Number(event.target.value) })
                }
                required
                disabled={!scenes.canMutate}
              />
            </label>
            <label>
              Board topology
              <select
                value={attachTopology}
                onChange={(event) =>
                  reviseCalibration({
                    topology: event.target.value as BoardTopology,
                  })
                }
                disabled={!scenes.canMutate}
              >
                <option value="square">Square</option>
                <option value="hex_flat">Flat-top hex</option>
                <option value="hex_pointy">Pointy-top hex</option>
                <option value="gridless">Gridless</option>
              </select>
            </label>
            <div className="scene-number-grid">
              <label>
                Origin X px
                <input
                  type="number"
                  step="any"
                  value={attachOriginXPx}
                  onChange={(event) =>
                    reviseCalibration({ originXPx: Number(event.target.value) })
                  }
                  disabled={!scenes.canMutate}
                />
              </label>
              <label>
                Origin Y px
                <input
                  type="number"
                  step="any"
                  value={attachOriginYPx}
                  onChange={(event) =>
                    reviseCalibration({ originYPx: Number(event.target.value) })
                  }
                  disabled={!scenes.canMutate}
                />
              </label>
              <label>
                Feet / step
                <input
                  type="number"
                  min={0.01}
                  max={100000}
                  step="any"
                  value={attachDistanceFt}
                  onChange={(event) =>
                    reviseCalibration({ distanceFt: Number(event.target.value) })
                  }
                  disabled={!scenes.canMutate}
                />
              </label>
            </div>
            <button
              type="submit"
              className="button button-primary"
              disabled={!scenes.canMutate || !active || !selectedAsset}
            >
              {scenes.operation === "updating" ? "Attaching…" : "Attach to active scene"}
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
