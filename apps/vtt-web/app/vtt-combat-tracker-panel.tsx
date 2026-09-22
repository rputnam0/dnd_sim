"use client";

import { useMemo, useState } from "react";

import type { EncounterProjection } from "./vtt-client";
import type { CombatControlPayload } from "./vtt-combat-tracker";

interface VttCombatTrackerPanelProps {
  projection: EncounterProjection;
  canManage: boolean;
  pending: boolean;
  error: string | null;
  onControl: (payload: CombatControlPayload) => Promise<void>;
}

export function VttCombatTrackerPanel({
  projection,
  canManage,
  pending,
  error,
  onControl,
}: VttCombatTrackerPanelProps) {
  const [auditReason, setAuditReason] = useState("");
  const [delayAfterActorId, setDelayAfterActorId] = useState("");
  const [overrideActorId, setOverrideActorId] = useState(
    projection.active_actor_id ?? projection.initiative_order[0] ?? "",
  );
  const [overrideRound, setOverrideRound] = useState(projection.round_number);
  const activeIndex = projection.active_actor_id
    ? projection.initiative_order.indexOf(projection.active_actor_id)
    : -1;
  const laterActorIds = useMemo(
    () => projection.initiative_order.slice(activeIndex + 1),
    [activeIndex, projection.initiative_order],
  );
  const selectedDelayActorId = laterActorIds.includes(delayAfterActorId)
    ? delayAfterActorId
    : (laterActorIds[0] ?? "");
  const reasonReady =
    auditReason === auditReason.trim() &&
    auditReason.length > 0 &&
    [...auditReason].length <= 256;
  const started = projection.phase === "awaiting_declaration";
  const canSubmit = canManage && !pending && reasonReady;

  if (!canManage) {
    return (
      <section className="combat-tracker-controls" aria-label="Combat tracker controls">
        <p className="command-permission-note">
          Combat tracker corrections are read-only for players and spectators.
        </p>
      </section>
    );
  }

  const submit = (payload: CombatControlPayload) => {
    void onControl(payload);
  };
  const moveActor = (actorId: string, offset: -1 | 1) => {
    const index = projection.initiative_order.indexOf(actorId);
    const destination = index + offset;
    if (index < 0 || destination < 0 || destination >= projection.initiative_order.length) {
      return;
    }
    const initiativeOrder = [...projection.initiative_order];
    [initiativeOrder[index], initiativeOrder[destination]] = [
      initiativeOrder[destination],
      initiativeOrder[index],
    ];
    submit({
      operation: "reorder",
      initiative_order: initiativeOrder,
      reason: auditReason,
    });
  };

  return (
    <section className="combat-tracker-controls" aria-labelledby="combat-tracker-title">
      <div className="combat-tracker-heading">
        <p className="eyebrow">GM audit controls</p>
        <h3 id="combat-tracker-title">Correct tracker</h3>
      </div>

      <label>
        Audit reason
        <input
          name="combat-control-reason"
          type="text"
          maxLength={256}
          value={auditReason}
          disabled={pending}
          onChange={(event) => setAuditReason(event.currentTarget.value)}
          placeholder="Why is this correction needed?"
        />
      </label>

      <div className="combat-cursor-buttons" aria-label="Move combat cursor">
        <button
          type="button"
          disabled={
            !canSubmit ||
            !started ||
            (projection.current_index === 0 && projection.round_number === 1)
          }
          onClick={() =>
            submit({
              operation: "advance",
              direction: "previous",
              reason: auditReason,
            })
          }
        >
          Previous
        </button>
        <button
          type="button"
          disabled={
            !canSubmit ||
            !started ||
            (projection.current_index === projection.initiative_order.length - 1 &&
              projection.round_number === projection.max_rounds)
          }
          onClick={() =>
            submit({
              operation: "advance",
              direction: "next",
              reason: auditReason,
            })
          }
        >
          Next
        </button>
      </div>

      <ol className="combat-order-editor" aria-label="Initiative order editor">
        {projection.initiative_order.map((actorId, index) => (
          <li key={actorId}>
            <span>{projection.actors[actorId]?.name ?? actorId}</span>
            <button
              type="button"
              disabled={!canSubmit || index === 0 || projection.phase === "terminal"}
              onClick={() => moveActor(actorId, -1)}
            >
              {`Move ${projection.actors[actorId]?.name ?? actorId} up`}
            </button>
            <button
              type="button"
              disabled={
                !canSubmit ||
                index === projection.initiative_order.length - 1 ||
                projection.phase === "terminal"
              }
              onClick={() => moveActor(actorId, 1)}
            >
              {`Move ${projection.actors[actorId]?.name ?? actorId} down`}
            </button>
          </li>
        ))}
      </ol>

      <div className="combat-control-row">
        <label>
          Delay until after
          <select
            value={selectedDelayActorId}
            disabled={!started || laterActorIds.length === 0 || pending}
            onChange={(event) => setDelayAfterActorId(event.currentTarget.value)}
          >
            {laterActorIds.map((actorId) => (
              <option key={actorId} value={actorId}>
                {projection.actors[actorId]?.name ?? actorId}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!canSubmit || !started || selectedDelayActorId === ""}
          onClick={() =>
            submit({
              operation: "delay",
              after_actor_id: selectedDelayActorId,
              reason: auditReason,
            })
          }
        >
          Delay turn
        </button>
      </div>

      <div className="combat-control-row">
        <label>
          Active combatant
          <select
            value={overrideActorId}
            disabled={!started || pending}
            onChange={(event) => setOverrideActorId(event.currentTarget.value)}
          >
            {projection.initiative_order.map((actorId) => (
              <option key={actorId} value={actorId}>
                {projection.actors[actorId]?.name ?? actorId}
              </option>
            ))}
          </select>
        </label>
        <label>
          Round
          <input
            name="combat-override-round"
            type="number"
            min={1}
            max={projection.max_rounds}
            value={overrideRound}
            disabled={!started || pending}
            onChange={(event) => setOverrideRound(Number(event.currentTarget.value))}
          />
        </label>
        <button
          type="button"
          disabled={
            !canSubmit ||
            !started ||
            !Number.isSafeInteger(overrideRound) ||
            overrideRound < 1 ||
            overrideRound > projection.max_rounds ||
            !projection.initiative_order.includes(overrideActorId)
          }
          onClick={() =>
            submit({
              operation: "override",
              active_actor_id: overrideActorId,
              round_number: overrideRound,
              reason: auditReason,
            })
          }
        >
          Apply cursor
        </button>
      </div>

      <p className="combat-tracker-status" role={error ? "alert" : "status"} aria-live="polite">
        {error ?? (pending ? "Applying authoritative tracker change…" : "Tracker changes are durably audited.")}
      </p>
    </section>
  );
}
