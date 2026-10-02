"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { getTableView } from "./vtt-access";
import type { WorldLaunch } from "./vtt-installation";
import { useVttScenes } from "./use-vtt-scenes";
import { useVttMapAssetUrl } from "./use-vtt-map-assets";

/** Published map presentation only. No authoring controller or fixture board. */
export function VttGuestWorkspace({ launch, apiBaseUrl, onLeave, onAccessLost }: { launch: WorldLaunch; apiBaseUrl: string; onLeave: () => void; onAccessLost: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const lost = useRef(onAccessLost);
  useEffect(() => { lost.current = onAccessLost; }, [onAccessLost]);
  const scenes = useVttScenes({ sessionId: launch.session_id, tableId: launch.world.table_id, bearerToken: launch.bearer_token, participant: launch.table.current_participant, apiBaseUrl, onAccessLost, refreshOnly: true });
  const active = scenes.view?.scenes.find((entry) => !entry.archived && entry.scene.scene_id === scenes.view?.active_scene_id)?.scene;
  const map = active?.map_metadata;
  const media = useVttMapAssetUrl(map?.asset ?? null, launch.bearer_token, apiBaseUrl, onAccessLost);
  useEffect(() => { heading.current?.focus(); }, []);
  useEffect(() => {
    const controller = new AbortController(); let inFlight = false;
    const verify = async () => {
      if (controller.signal.aborted || inFlight) return;
      inFlight = true;
      try {
        const table = await getTableView({ bearerToken: launch.bearer_token, apiBaseUrl, signal: controller.signal });
        if (controller.signal.aborted) return;
        const participant = table.current_participant;
        if (table.table_id !== launch.world.table_id || table.access_mode !== "protected" || participant.participant_id !== launch.table.current_participant.participant_id || participant.role !== launch.table.current_participant.role || participant.owned_actor_ids.length !== 0 || table.participants.length !== 2 || table.participants.filter((entry) => entry.role === "gm").length !== 1) lost.current();
      } catch { if (!controller.signal.aborted) lost.current(); }
      finally { inFlight = false; }
    };
    void verify();
    const timer = setInterval(() => { void verify(); }, 15_000);
    const focus = () => { void verify(); };
    if (typeof window !== "undefined") window.addEventListener("focus", focus);
    return () => { controller.abort(); clearInterval(timer); if (typeof window !== "undefined") window.removeEventListener("focus", focus); };
  }, [apiBaseUrl, launch]);
  return <div className="vw-workspace vw-guest" aria-label="Guest world view">
    <header className="vw-heading"><div><p className="vi-eyebrow">AT THE TABLE / {launch.table.current_participant.role.toUpperCase()}</p><h1 ref={heading} tabIndex={-1}>{launch.world.name}</h1><p>Welcome, {launch.table.current_participant.display_name}. This is your published scene view.</p></div><button className="vi-button vi-secondary" onClick={onLeave}>Leave world</button></header>
    <section className="vw-stage" aria-label="Published scene"><div className="vw-stage-heading"><span className="vi-eyebrow">PUBLISHED SCENE</span><span className="vi-badge">Read-only view</span></div>
      {map ? <><div className="vw-map-frame" style={{ "--map-aspect": `${map.width_px} / ${map.height_px}` } as CSSProperties}>{media.url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={media.url} alt={map.asset?.alt_text ?? map.name} />
      ) : <div className="vw-map-placeholder"><h2>{map.name}</h2><p>{media.loading ? "Loading the published map…" : "The scene’s map image is not available."}</p></div>}</div><div className="vw-map-caption"><strong>{map.name}</strong><small>Map preview only. No actor controls or combat encounter.</small></div></> : <div className="vw-empty-stage"><span className="vw-compass" aria-hidden="true">◇</span><h2>{scenes.view ? "Waiting for the scene." : "Opening your world…"}</h2><p>Your Game Master’s published scene will appear here. No private preparation or other guests’ identities are shown.</p></div>}
      {scenes.error && <div className="vi-notice vi-notice-error" role="alert"><p>The published scene could not be synchronized. Check your connection or ask your Game Master for help.</p><button className="vi-button vi-secondary" onClick={scenes.retry}>Retry published scene</button></div>}
      {media.error && <div className="vi-notice vi-notice-error" role="alert"><p>The published map image could not be verified. Retry the map or ask your Game Master to check the map and connection.</p><button className="vi-button vi-secondary" onClick={scenes.retry}>Retry published map</button></div>}
    </section><p className="vw-scope-note">Access lasts up to four hours and is kept only in this page’s memory. Leaving, reloading, or a service restart requires a new invitation. Your Game Master can revoke access at any time.</p>
  </div>;
}
