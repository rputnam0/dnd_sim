"use client";

import { useEffect, useRef, type CSSProperties } from "react";

import { getTableView } from "./vtt-access";
import type { WorldLaunch } from "./vtt-installation";
import { useVttScenes } from "./use-vtt-scenes";
import { useVttMapAssets, useVttMapAssetUrl } from "./use-vtt-map-assets";
import { VttScenesPanel } from "./vtt-scenes-panel";

/** A real empty-world workspace: scenes and maps only, with no combat fixture. */
export function VttWorldWorkspace({ launch, apiBaseUrl, onReturn, onAccessLost }: {
  launch: WorldLaunch;
  apiBaseUrl: string;
  onReturn: () => Promise<void>;
  onAccessLost: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const accessLost = useRef(onAccessLost);
  useEffect(() => { accessLost.current = onAccessLost; }, [onAccessLost]);
  const input = {
    sessionId: launch.session_id,
    tableId: launch.world.table_id,
    bearerToken: launch.bearer_token,
    participant: launch.table.current_participant,
    apiBaseUrl,
    onAccessLost,
  };
  const scenes = useVttScenes(input);
  const assets = useVttMapAssets(input);
  const active = scenes.view?.scenes.find((entry) => !entry.archived && entry.scene.scene_id === scenes.view?.active_scene_id)?.scene;
  const map = active?.map_metadata;
  const media = useVttMapAssetUrl(map?.asset ?? null, launch.bearer_token, apiBaseUrl, onAccessLost);
  const activeCount = scenes.view?.scenes.filter((entry) => !entry.archived).length ?? 0;

  useEffect(() => { heading.current?.focus(); }, []);

  // An idle workspace must notice revoked/expired credentials and archived
  // worlds too. No response from an old launch may close a newer workspace.
  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    const verify = async () => {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true;
      try {
        const table = await getTableView({ bearerToken: launch.bearer_token, apiBaseUrl, signal: controller.signal });
        if (controller.signal.aborted) return;
        if (table.table_id !== launch.world.table_id || table.access_mode !== "protected" ||
          table.current_participant.participant_id !== launch.table.current_participant.participant_id ||
          table.current_participant.role !== launch.table.current_participant.role) accessLost.current();
      } catch {
        if (!controller.signal.aborted) accessLost.current();
      } finally { inFlight = false; }
    };
    void verify();
    const timer = setInterval(() => { void verify(); }, 15_000);
    const onFocus = () => { void verify(); };
    if (typeof window !== "undefined") window.addEventListener("focus", onFocus);
    return () => {
      controller.abort(); clearInterval(timer);
      if (typeof window !== "undefined") window.removeEventListener("focus", onFocus);
    };
  }, [apiBaseUrl, launch]);

  return (
    <div className="vw-workspace" aria-label={`World preparation: ${launch.world.name}`}>
      <header className="vw-heading">
        <div>
          <p className="vi-eyebrow">WORLD PREPARATION / D&amp;D 5E</p>
          <h1 ref={heading} tabIndex={-1}>{launch.world.name}</h1>
          <p>A private space to set the scene for what comes next.</p>
        </div>
        <button className="vi-button vi-secondary" onClick={onReturn}>Return to worlds</button>
      </header>

      <div className="vw-stage-layout">
        <section className="vw-stage" aria-label="Scene preview">
          <div className="vw-stage-heading">
            <span className="vi-eyebrow">{map ? "ACTIVE SCENE" : "YOUR WORLD STARTS HERE"}</span>
            <span className="vi-badge">Preparation only</span>
          </div>
          {map ? (
            <>
              <div className="vw-map-frame" style={{ "--map-aspect": `${map.width_px} / ${map.height_px}` } as CSSProperties}>
                {media.url ? (
                  // Authenticated blob URLs are verified and revoked by the media hook.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={media.url} alt={map.asset?.alt_text ?? map.name} />
                ) : (
                  <div className="vw-map-placeholder">
                    <span aria-hidden="true">◇</span>
                    <h2>{map.name}</h2>
                    <p>{media.loading ? "Loading verified map image…" : map.asset ? "Map preview unavailable." : "Your scene is ready for a map."}</p>
                    {!map.asset && <a href="#world-scene-tools">Upload and attach a map below ↓</a>}
                  </div>
                )}
              </div>
              <div className="vw-map-caption">
                <strong>{map.name}</strong>
                <span>
                  {map.width_px.toLocaleString()} × {map.height_px.toLocaleString()} px · {map.calibration.topology.replaceAll("_", " ")} · {map.calibration.distance_ft} ft / {map.calibration.topology === "gridless" ? `${map.calibration.cell_extent_px} px` : "cell"}
                </span>
                <small>Raw map preview. Calibration is saved; no tactical grid or encounter is rendered.</small>
                {media.error && <p role="alert">The map image could not be verified. Check its source and try again.</p>}
              </div>
            </>
          ) : (
            <div className="vw-empty-stage">
              <span className="vw-compass" aria-hidden="true">◇</span>
              <p className="vi-eyebrow">ROOM FOR YOUR IMAGINATION</p>
              <h2>{scenes.view ? "A blank canvas for your world." : "Opening your scene library…"}</h2>
              <p>{scenes.view ? "No scenes, maps, or encounters have been added. Create your first scene, then bring it to life with a map." : "Loading this world’s verified preparation data."}</p>
              <a href="#world-scene-tools" className="vi-button vi-primary">{scenes.view ? "Create your first scene" : "Scene & map tools"}<span aria-hidden="true">↓</span></a>
            </div>
          )}
        </section>

        <aside className="vw-preparation-notes" aria-label="Preparation overview">
          <section className="vw-note-card">
            <p className="vi-eyebrow">AT A GLANCE</p>
            <h2>Your preparation desk</h2>
            <dl>
              <div><dt>Active scenes</dt><dd>{scenes.view ? activeCount : "—"}</dd></div>
              <div><dt>Map images</dt><dd>{assets.catalog ? assets.catalog.assets.length : "—"}</dd></div>
              <div><dt>Your role</dt><dd>{launch.table.current_participant.role === "gm" ? "Game Master" : launch.table.current_participant.role}</dd></div>
            </dl>
          </section>
          <section className="vw-note-card vw-next-steps">
            <p className="vi-eyebrow">MAKE IT YOURS</p>
            <ol>
              <li><span>01</span><div><strong>Create a scene</strong><p>Name the place and set its dimensions.</p></div></li>
              <li><span>02</span><div><strong>Bring your own map</strong><p>Upload a PNG, JPEG, or WebP image.</p></div></li>
              <li><span>03</span><div><strong>Attach & calibrate</strong><p>Save scale and geometry for your scene.</p></div></li>
            </ol>
          </section>
          <p className="vw-scope-note">Scenes and maps persist in this world. Combat, tokens, and player invitations are not available in this preparation workspace.</p>
        </aside>
      </div>

      <div id="world-scene-tools" className="vw-tools" tabIndex={-1}>
        <VttScenesPanel table={launch.table} scenes={scenes} assets={assets} />
      </div>
    </div>
  );
}
