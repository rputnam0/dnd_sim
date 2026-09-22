import type { JsonValue, VttCommand } from "./vtt-client";

export type CombatControlPayload =
  | {
      operation: "advance";
      direction: "next" | "previous";
      reason: string;
    }
  | {
      operation: "reorder";
      initiative_order: string[];
      reason: string;
    }
  | {
      operation: "delay";
      after_actor_id: string;
      reason: string;
    }
  | {
      operation: "override";
      active_actor_id: string;
      round_number: number;
      reason: string;
    };

function requiredText(value: string, field: string, maximum = 128): string {
  if (
    typeof value !== "string" ||
    value !== value.trim() ||
    value.length === 0 ||
    [...value].length > maximum
  ) {
    throw new Error(`${field} must be canonical non-empty text`);
  }
  return value;
}

function expectedRevision(value: number): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error("expectedRevision must be a non-negative safe integer");
  }
  return value;
}

function reason(value: string): string {
  return requiredText(value, "reason", 256);
}

function actorIds(values: string[]): string[] {
  if (!Array.isArray(values) || values.length === 0) {
    throw new Error("initiative_order must contain actors");
  }
  const result = values.map((value) => requiredText(value, "actor ID"));
  if (new Set(result).size !== result.length) {
    throw new Error("initiative_order must not contain duplicate actors");
  }
  return result;
}

function canonicalPayload(payload: CombatControlPayload): Record<string, JsonValue> {
  if (payload.operation === "advance") {
    if (!new Set(["next", "previous"]).has(payload.direction)) {
      throw new Error("direction must be next or previous");
    }
    return {
      operation: "advance",
      direction: payload.direction,
      reason: reason(payload.reason),
    };
  }
  if (payload.operation === "reorder") {
    return {
      operation: "reorder",
      initiative_order: actorIds(payload.initiative_order),
      reason: reason(payload.reason),
    };
  }
  if (payload.operation === "delay") {
    return {
      operation: "delay",
      after_actor_id: requiredText(payload.after_actor_id, "after_actor_id"),
      reason: reason(payload.reason),
    };
  }
  if (payload.operation === "override") {
    if (!Number.isSafeInteger(payload.round_number) || payload.round_number < 1) {
      throw new Error("round_number must be a positive safe integer");
    }
    return {
      operation: "override",
      active_actor_id: requiredText(payload.active_actor_id, "active_actor_id"),
      round_number: payload.round_number,
      reason: reason(payload.reason),
    };
  }
  throw new Error("combat control operation is unsupported");
}

export function buildCombatControlCommand(input: {
  sessionId: string;
  expectedRevision: number;
  payload: CombatControlPayload;
  commandId?: string;
}): VttCommand {
  return {
    schema_version: "vtt.command.v1",
    command_id:
      input.commandId === undefined
        ? crypto.randomUUID()
        : requiredText(input.commandId, "commandId"),
    session_id: requiredText(input.sessionId, "sessionId"),
    actor_id: null,
    expected_revision: expectedRevision(input.expectedRevision),
    mode: "admin",
    kind: "dnd.combat.control.v1",
    payload: canonicalPayload(input.payload),
    intent_metadata: { surface: "echo-vault-web" },
  };
}
