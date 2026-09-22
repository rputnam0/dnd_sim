import {
  VTT_API_BASE_URL,
  VttApiError,
  type JsonValue,
} from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";

export type VttTableRole = "gm" | "player" | "spectator";

export interface VttTableParticipant {
  schema_version: "vtt.participant.v1";
  participant_id: string;
  display_name: string;
  role: VttTableRole;
  owned_actor_ids: string[];
}

export interface VttTableView {
  schema_version: "vtt.table_view.v1";
  access_mode: "open_local" | "protected";
  table_id: string;
  current_participant: VttTableParticipant;
  participants: VttTableParticipant[];
}

export interface VttChatAudienceChoice {
  key: string;
  label: string;
  audience: string[];
}

type ObjectValue = Record<string, unknown>;

function exactObject(
  value: unknown,
  keys: readonly string[],
  path: string,
): ObjectValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  const result = value as ObjectValue;
  const expected = new Set(keys);
  for (const key of Object.keys(result)) {
    if (!expected.has(key)) {
      throw new Error(`${path} contains unexpected field "${key}"`);
    }
  }
  for (const key of keys) {
    if (!(key in result)) throw new Error(`${path} is missing field "${key}"`);
  }
  return result;
}

function literal<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new Error(`${path} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function canonicalText(value: unknown, path: string): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value
  ) {
    throw new Error(`${path} must be canonical non-empty text`);
  }
  return value;
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) => character.codePointAt(0) as number);
  const rightPoints = Array.from(right, (character) => character.codePointAt(0) as number);
  for (let index = 0; index < Math.min(leftPoints.length, rightPoints.length); index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

function parseParticipant(value: unknown, path: string): VttTableParticipant {
  const data = exactObject(
    value,
    [
      "schema_version",
      "participant_id",
      "display_name",
      "role",
      "owned_actor_ids",
    ],
    path,
  );
  const participantId = canonicalText(data.participant_id, `${path}.participant_id`);
  const displayName = canonicalText(data.display_name, `${path}.display_name`);
  const role = literal(data.role, ["gm", "player", "spectator"], `${path}.role`);
  if (!Array.isArray(data.owned_actor_ids)) {
    throw new Error(`${path}.owned_actor_ids must be an ordered list`);
  }
  const ownedActorIds = data.owned_actor_ids.map((actorId, index) =>
    canonicalText(actorId, `${path}.owned_actor_ids[${index}]`),
  );
  if (new Set(ownedActorIds).size !== ownedActorIds.length) {
    throw new Error(`${path}.owned_actor_ids must be unique`);
  }
  if (
    ownedActorIds.some(
      (actorId, index) =>
        index > 0 && compareCodePoints(ownedActorIds[index - 1], actorId) > 0,
    )
  ) {
    throw new Error(`${path}.owned_actor_ids must be sorted`);
  }
  if (role === "spectator" && ownedActorIds.length > 0) {
    throw new Error(`${path} spectator cannot own actors`);
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.participant.v1"],
      `${path}.schema_version`,
    ),
    participant_id: participantId,
    display_name: displayName,
    role,
    owned_actor_ids: ownedActorIds,
  };
}

function sameParticipant(
  left: VttTableParticipant,
  right: VttTableParticipant,
): boolean {
  return (
    left.schema_version === right.schema_version &&
    left.participant_id === right.participant_id &&
    left.display_name === right.display_name &&
    left.role === right.role &&
    left.owned_actor_ids.length === right.owned_actor_ids.length &&
    left.owned_actor_ids.every((actorId, index) => actorId === right.owned_actor_ids[index])
  );
}

export function parseTableView(value: unknown): VttTableView {
  const data = exactObject(
    value,
    [
      "schema_version",
      "access_mode",
      "table_id",
      "current_participant",
      "participants",
    ],
    "table_view",
  );
  if (!Array.isArray(data.participants) || data.participants.length === 0) {
    throw new Error("table_view.participants must be a non-empty directory");
  }
  const participants = data.participants.map((participant, index) =>
    parseParticipant(participant, `table_view.participants[${index}]`),
  );
  const participantIds = participants.map((participant) => participant.participant_id);
  if (new Set(participantIds).size !== participantIds.length) {
    throw new Error("table_view participants must have unique participant IDs");
  }
  if (
    participantIds.some(
      (participantId, index) =>
        index > 0 && compareCodePoints(participantIds[index - 1], participantId) > 0,
    )
  ) {
    throw new Error("table_view participants must be sorted by participant ID");
  }
  const currentParticipant = parseParticipant(
    data.current_participant,
    "table_view.current_participant",
  );
  const directoryEntry = participants.find(
    (participant) => participant.participant_id === currentParticipant.participant_id,
  );
  if (directoryEntry === undefined || !sameParticipant(directoryEntry, currentParticipant)) {
    throw new Error("The current participant must exactly match its directory entry");
  }
  return {
    schema_version: literal(
      data.schema_version,
      ["vtt.table_view.v1"],
      "table_view.schema_version",
    ),
    access_mode: literal(
      data.access_mode,
      ["open_local", "protected"],
      "table_view.access_mode",
    ),
    table_id: canonicalText(data.table_id, "table_view.table_id"),
    current_participant: currentParticipant,
    participants,
  };
}

export function canControlActor(
  participant: VttTableParticipant,
  actorId: string,
): boolean {
  if (participant.role === "gm") return true;
  return (
    participant.role === "player" &&
    participant.owned_actor_ids.includes(actorId)
  );
}

export function canDeleteParticipantRecord(
  participant: VttTableParticipant,
  authorId: string,
): boolean {
  return participant.role === "gm" || participant.participant_id === authorId;
}

export function chatAudienceChoices(
  table: VttTableView,
): VttChatAudienceChoice[] {
  const direct = table.participants
    .filter(
      (participant) =>
        participant.participant_id !== table.current_participant.participant_id &&
        participant.role !== "spectator",
    )
    .map((participant) => ({
      key: `participant:${participant.participant_id}`,
      label: `Direct · ${participant.display_name}`,
      audience: [`participant:${participant.participant_id}`],
    }));
  return [
    { key: "public", label: "Everyone", audience: ["all"] },
    { key: "gm", label: "Game Masters", audience: ["role:gm"] },
    ...direct,
  ];
}

function jsonObject(value: unknown, path: string): Record<string, JsonValue> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value as Record<string, JsonValue>;
}

async function tableResponseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The table service returned unreadable identity data.", {
      code: "invalid_response",
      status: response.status,
    });
  }
  if (response.ok) return value;
  try {
    const error = exactObject(
      value,
      ["schema_version", "code", "message", "details"],
      "error",
    );
    literal(error.schema_version, ["vtt.error.v1"], "error.schema_version");
    throw new VttApiError(canonicalText(error.message, "error.message"), {
      code: canonicalText(error.code, "error.code"),
      status: response.status,
      details: jsonObject(error.details, "error.details"),
    });
  } catch (error) {
    if (error instanceof VttApiError) throw error;
    throw new VttApiError("The table service rejected identity access.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getTableView(input: {
  bearerToken?: string | null;
  signal?: AbortSignal;
  apiBaseUrl?: string;
} = {}): Promise<VttTableView> {
  const response = await fetch(`${(input.apiBaseUrl ?? VTT_API_BASE_URL).replace(/\/+$/, "")}/api/v1/table`, {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken: input.bearerToken,
    }),
    signal: input.signal,
    credentials: "omit", redirect: "error", cache: "no-store",
  });
  return parseTableView(await tableResponseJson(response));
}
