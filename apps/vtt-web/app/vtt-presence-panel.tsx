"use client";

import { useId } from "react";

import { useVttPresence, type PresenceConnectionStatus } from "./use-vtt-presence";
import type { VttTableView } from "./vtt-access";
import type { PresenceStatus } from "./vtt-presence";

function connectionLabel(status: PresenceConnectionStatus): string {
  if (status === "loading") return "Loading participants…";
  if (status === "connecting") return "Connecting presence…";
  if (status === "reconnecting") return "Presence reconnecting…";
  if (status === "unavailable") return "Presence unavailable";
  if (status === "error") return "Presence sync interrupted";
  return "Presence live";
}

function statusLabel(status: PresenceStatus): string {
  if (status === "online") return "Online";
  if (status === "away") return "Away";
  return "Offline";
}

function roleLabel(role: string): string {
  if (role === "gm") return "Game Master";
  if (role === "player") return "Player";
  return "Spectator";
}

export function VttPresencePanel({
  sessionId,
  bearerToken,
  table,
}: {
  sessionId: string;
  bearerToken: string | null;
  table: VttTableView;
}) {
  const presence = useVttPresence({ sessionId, bearerToken, table });
  const titleId = useId();
  const onlineCount = presence.records.filter(
    (record) => record.status === "online",
  ).length;

  return (
    <section className="panel presence-panel" aria-labelledby={titleId}>
      <div className="panel-heading presence-heading">
        <div>
          <p className="eyebrow">Shared table roster</p>
          <h2 id={titleId}>Participant presence</h2>
        </div>
        <span
          className={`presence-connection presence-connection-${presence.status}`}
          role="status"
          aria-live="polite"
        >
          <span aria-hidden="true" />
          {connectionLabel(presence.status)}
        </span>
      </div>

      <div className="presence-summary">
        <strong>{onlineCount}</strong>
        <span>{onlineCount === 1 ? "participant online" : "participants online"}</span>
      </div>

      <ul className="presence-list" aria-label="Table participants">
        {(presence.records.length > 0
          ? presence.records
          : table.participants.map((participant) => ({
              schema_version: "vtt.presence_record.v1" as const,
              participant_id: participant.participant_id,
              display_name: participant.display_name,
              role: participant.role,
              status: "offline" as const,
            })))
          .map((record) => {
            const current =
              record.participant_id === table.current_participant.participant_id;
            return (
              <li className="presence-entry" key={record.participant_id}>
                <span
                  className={`presence-dot presence-dot-${record.status}`}
                  aria-hidden="true"
                />
                <div>
                  <div className="presence-name-row">
                    <strong>{record.display_name}</strong>
                    {current ? <span className="presence-you">You</span> : null}
                  </div>
                  <span>{roleLabel(record.role)}</span>
                </div>
                <span className={`presence-state presence-state-${record.status}`}>
                  {statusLabel(record.status)}
                </span>
              </li>
            );
          })}
      </ul>

      {presence.error ? (
        <div
          className="presence-notice"
          role={presence.status === "unavailable" ? "status" : "alert"}
        >
          <p>{presence.error}</p>
          {presence.status === "error" || presence.status === "unavailable" ? (
            <button type="button" onClick={presence.retry}>
              Retry presence
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
