export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface VttVersionInfo {
  schema_version: "vtt.version_info.v1";
  engine: string;
  rules: string;
  content: string;
}

export interface FeetPosition {
  x_ft: number;
  y_ft: number;
  z_ft: number;
}

export interface SquareGridScene {
  schema_version: "vtt.scene.v1";
  scene_id: string;
  name: string;
  grid_type: "square";
  cell_size_ft: number;
  columns: number;
  rows: number;
  origin_ft: FeetPosition;
}

export interface ActorAction {
  name: string;
  action_type: string;
  action_cost: string;
  target_mode: string;
  reach_ft: number | null;
  range_normal_ft: number | null;
  range_long_ft: number | null;
}

export interface ActorProjection {
  actor_id: string;
  team: string;
  name: string;
  hp: number;
  max_hp: number;
  temp_hp: number;
  ac: number;
  position: [number, number, number];
  movement_remaining: number;
  conditions: string[];
  dead: boolean;
  stable: boolean;
  bonus_available: boolean;
  reaction_available: boolean;
  actions: ActorAction[];
}

export interface TurnPrompt {
  actor_id: string;
  round_number: number;
  turn_token: string;
}

export interface TurnResult {
  actor_id: string;
  round_number: number;
  turn_token: string;
  status: string;
  strategy_name: string | null;
}

export type EncounterOutcome =
  | "party_victory"
  | "enemy_victory"
  | "timeout";
export type EncounterPhase = "unstarted" | "awaiting_declaration" | "terminal";

export interface EncounterProjection {
  phase: EncounterPhase;
  outcome: EncounterOutcome | null;
  winner: "party" | "enemy" | null;
  current_index: number;
  active_actor_id: string | null;
  round_number: number;
  max_rounds: number;
  initiative_order: string[];
  actors: Record<string, ActorProjection>;
  prompt: TurnPrompt | null;
  result: TurnResult | null;
}

export interface VttSessionView {
  schema_version: "vtt.session_view.v1";
  session_id: string;
  revision: number;
  versions: VttVersionInfo;
  scene: SquareGridScene | null;
  projection: EncounterProjection;
}

export interface VttCommand {
  schema_version: "vtt.command.v1";
  command_id: string;
  session_id: string;
  actor_id: string | null;
  expected_revision: number;
  mode: "preview" | "commit" | "reaction" | "admin";
  kind: string;
  payload: Record<string, JsonValue>;
  intent_metadata: Record<string, JsonValue>;
}

export interface VttEventDraft {
  schema_version: "vtt.event_draft.v1";
  kind: string;
  audience: string[];
  payload: Record<string, JsonValue>;
}

export interface VttEvent {
  schema_version: "vtt.event.v1";
  event_id: string;
  session_id: string;
  sequence: number;
  revision: number;
  kind: string;
  command_id: string;
  versions: VttVersionInfo;
  causation_id: string | null;
  audience: string[];
  payload: Record<string, JsonValue>;
}

export interface VttPreviewResponse {
  schema_version: "vtt.preview_response.v1";
  response_type: "preview";
  command_id: string;
  session_id: string;
  revision: number;
  versions: VttVersionInfo;
  projection: EncounterProjection;
  events: VttEventDraft[];
}

export interface VttCommitResponse {
  schema_version: "vtt.commit_response.v1";
  response_type: "commit";
  command_id: string;
  session_id: string;
  replayed: boolean;
  revision: number;
  versions: VttVersionInfo;
  first_sequence: number | null;
  last_sequence: number | null;
  events: VttEvent[];
}

export type VttCommandResponse = VttPreviewResponse | VttCommitResponse;
export type DisplayEvent = VttEvent | VttEventDraft;

type ObjectValue = Record<string, unknown>;

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const configuredApiBase = process.env.NEXT_PUBLIC_VTT_API_BASE_URL?.trim();
export const VTT_API_BASE_URL = (
  configuredApiBase || DEFAULT_API_BASE_URL
).replace(/\/+$/, "");

function objectValue(value: unknown, path: string): ObjectValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value as ObjectValue;
}

function exactObject(
  value: unknown,
  keys: readonly string[],
  path: string,
): ObjectValue {
  const result = objectValue(value, path);
  const expected = new Set(keys);
  for (const key of Object.keys(result)) {
    if (!expected.has(key)) {
      throw new Error(`${path} contains unexpected field "${key}"`);
    }
  }
  for (const key of keys) {
    if (!(key in result)) {
      throw new Error(`${path} is missing field "${key}"`);
    }
  }
  return result;
}

function stringValue(value: unknown, path: string): string {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${path} must be a non-empty string`);
  }
  return value;
}

function literalValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) {
    throw new Error(`${path} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} must be a finite number`);
  }
  return value;
}

function integerValue(value: unknown, path: string, minimum = 0): number {
  const result = finiteNumber(value, path);
  if (!Number.isInteger(result) || result < minimum) {
    throw new Error(`${path} must be an integer >= ${minimum}`);
  }
  return result;
}

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${path} must be a boolean`);
  }
  return value;
}

function nullableString(value: unknown, path: string): string | null {
  return value === null ? null : stringValue(value, path);
}

function nullableNumber(value: unknown, path: string): number | null {
  return value === null ? null : finiteNumber(value, path);
}

function jsonObject(value: unknown, path: string): Record<string, JsonValue> {
  const result = objectValue(value, path);
  assertJsonValue(result, path);
  return result as Record<string, JsonValue>;
}

function assertJsonValue(value: unknown, path: string): asserts value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`${path} contains a non-finite number`);
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertJsonValue(item, `${path}[${index}]`));
    return;
  }
  if (typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      assertJsonValue(item, `${path}.${key}`);
    }
    return;
  }
  throw new Error(`${path} contains a non-JSON value`);
}

function stringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${path} must be an array`);
  }
  return value.map((item, index) => stringValue(item, `${path}[${index}]`));
}

function parseVersions(value: unknown, path: string): VttVersionInfo {
  const data = exactObject(
    value,
    ["schema_version", "engine", "rules", "content"],
    path,
  );
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.version_info.v1"],
      `${path}.schema_version`,
    ),
    engine: stringValue(data.engine, `${path}.engine`),
    rules: stringValue(data.rules, `${path}.rules`),
    content: stringValue(data.content, `${path}.content`),
  };
}

function parseFeetPosition(value: unknown, path: string): FeetPosition {
  const data = exactObject(value, ["x_ft", "y_ft", "z_ft"], path);
  return {
    x_ft: finiteNumber(data.x_ft, `${path}.x_ft`),
    y_ft: finiteNumber(data.y_ft, `${path}.y_ft`),
    z_ft: finiteNumber(data.z_ft, `${path}.z_ft`),
  };
}

function parseScene(value: unknown, path: string): SquareGridScene {
  const data = exactObject(
    value,
    [
      "schema_version",
      "scene_id",
      "name",
      "grid_type",
      "cell_size_ft",
      "columns",
      "rows",
      "origin_ft",
    ],
    path,
  );
  const cellSize = finiteNumber(data.cell_size_ft, `${path}.cell_size_ft`);
  if (cellSize <= 0) {
    throw new Error(`${path}.cell_size_ft must be positive`);
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.scene.v1"],
      `${path}.schema_version`,
    ),
    scene_id: stringValue(data.scene_id, `${path}.scene_id`),
    name: stringValue(data.name, `${path}.name`),
    grid_type: literalValue(data.grid_type, ["square"], `${path}.grid_type`),
    cell_size_ft: cellSize,
    columns: integerValue(data.columns, `${path}.columns`, 1),
    rows: integerValue(data.rows, `${path}.rows`, 1),
    origin_ft: parseFeetPosition(data.origin_ft, `${path}.origin_ft`),
  };
}

function parseAction(value: unknown, path: string): ActorAction {
  const data = exactObject(
    value,
    [
      "name",
      "action_type",
      "action_cost",
      "target_mode",
      "reach_ft",
      "range_normal_ft",
      "range_long_ft",
    ],
    path,
  );
  return {
    name: stringValue(data.name, `${path}.name`),
    action_type: stringValue(data.action_type, `${path}.action_type`),
    action_cost: stringValue(data.action_cost, `${path}.action_cost`),
    target_mode: stringValue(data.target_mode, `${path}.target_mode`),
    reach_ft: nullableNumber(data.reach_ft, `${path}.reach_ft`),
    range_normal_ft: nullableNumber(
      data.range_normal_ft,
      `${path}.range_normal_ft`,
    ),
    range_long_ft: nullableNumber(
      data.range_long_ft,
      `${path}.range_long_ft`,
    ),
  };
}

function parseActor(value: unknown, path: string): ActorProjection {
  const data = exactObject(
    value,
    [
      "actor_id",
      "team",
      "name",
      "hp",
      "max_hp",
      "temp_hp",
      "ac",
      "position",
      "movement_remaining",
      "conditions",
      "dead",
      "stable",
      "bonus_available",
      "reaction_available",
      "actions",
    ],
    path,
  );
  if (!Array.isArray(data.position) || data.position.length !== 3) {
    throw new Error(`${path}.position must contain exactly three coordinates`);
  }
  const position: [number, number, number] = [
    finiteNumber(data.position[0], `${path}.position[0]`),
    finiteNumber(data.position[1], `${path}.position[1]`),
    finiteNumber(data.position[2], `${path}.position[2]`),
  ];
  const conditions = stringArray(data.conditions, `${path}.conditions`);
  if (
    conditions.some((condition, index) => condition !== [...conditions].sort()[index]) ||
    new Set(conditions).size !== conditions.length
  ) {
    throw new Error(`${path}.conditions must be unique and sorted`);
  }
  if (!Array.isArray(data.actions)) {
    throw new Error(`${path}.actions must be an array`);
  }
  return {
    actor_id: stringValue(data.actor_id, `${path}.actor_id`),
    team: stringValue(data.team, `${path}.team`),
    name: stringValue(data.name, `${path}.name`),
    hp: integerValue(data.hp, `${path}.hp`),
    max_hp: integerValue(data.max_hp, `${path}.max_hp`, 1),
    temp_hp: integerValue(data.temp_hp, `${path}.temp_hp`),
    ac: integerValue(data.ac, `${path}.ac`),
    position,
    movement_remaining: finiteNumber(
      data.movement_remaining,
      `${path}.movement_remaining`,
    ),
    conditions,
    dead: booleanValue(data.dead, `${path}.dead`),
    stable: booleanValue(data.stable, `${path}.stable`),
    bonus_available: booleanValue(
      data.bonus_available,
      `${path}.bonus_available`,
    ),
    reaction_available: booleanValue(
      data.reaction_available,
      `${path}.reaction_available`,
    ),
    actions: data.actions.map((action, index) =>
      parseAction(action, `${path}.actions[${index}]`),
    ),
  };
}

function parsePrompt(value: unknown, path: string): TurnPrompt | null {
  if (value === null) {
    return null;
  }
  const data = exactObject(
    value,
    ["actor_id", "round_number", "turn_token"],
    path,
  );
  return {
    actor_id: stringValue(data.actor_id, `${path}.actor_id`),
    round_number: integerValue(data.round_number, `${path}.round_number`, 1),
    turn_token: stringValue(data.turn_token, `${path}.turn_token`),
  };
}

function parseResult(value: unknown, path: string): TurnResult | null {
  if (value === null) {
    return null;
  }
  const data = exactObject(
    value,
    ["actor_id", "round_number", "turn_token", "status", "strategy_name"],
    path,
  );
  return {
    actor_id: stringValue(data.actor_id, `${path}.actor_id`),
    round_number: integerValue(data.round_number, `${path}.round_number`, 1),
    turn_token: stringValue(data.turn_token, `${path}.turn_token`),
    status: stringValue(data.status, `${path}.status`),
    strategy_name: nullableString(
      data.strategy_name,
      `${path}.strategy_name`,
    ),
  };
}

function parseProjection(value: unknown, path: string): EncounterProjection {
  const data = exactObject(
    value,
    [
      "phase",
      "outcome",
      "winner",
      "current_index",
      "active_actor_id",
      "round_number",
      "max_rounds",
      "initiative_order",
      "actors",
      "prompt",
      "result",
    ],
    path,
  );
  const phase = literalValue(
    data.phase,
    ["unstarted", "awaiting_declaration", "terminal"],
    `${path}.phase`,
  );
  const outcome =
    data.outcome === null
      ? null
      : literalValue(
          data.outcome,
          ["party_victory", "enemy_victory", "timeout"],
          `${path}.outcome`,
        );
  const winner =
    data.winner === null
      ? null
      : literalValue(data.winner, ["party", "enemy"], `${path}.winner`);
  const activeActorId = nullableString(
    data.active_actor_id,
    `${path}.active_actor_id`,
  );
  const initiativeOrder = stringArray(
    data.initiative_order,
    `${path}.initiative_order`,
  );
  const rawActors = objectValue(data.actors, `${path}.actors`);
  const actors: Record<string, ActorProjection> = {};
  for (const [actorId, actorValue] of Object.entries(rawActors)) {
    const actor = parseActor(actorValue, `${path}.actors.${actorId}`);
    if (actor.actor_id !== actorId) {
      throw new Error(`${path}.actors.${actorId}.actor_id must match its map key`);
    }
    actors[actorId] = actor;
  }
  if (
    initiativeOrder.length !== Object.keys(actors).length ||
    new Set(initiativeOrder).size !== initiativeOrder.length ||
    initiativeOrder.some((actorId) => !(actorId in actors))
  ) {
    throw new Error(`${path}.initiative_order must contain every actor exactly once`);
  }
  const prompt = parsePrompt(data.prompt, `${path}.prompt`);
  const result = parseResult(data.result, `${path}.result`);
  if (phase === "terminal") {
    if (activeActorId !== null || outcome === null || prompt !== null) {
      throw new Error(`${path} has inconsistent terminal fields`);
    }
  } else if (activeActorId === null || outcome !== null) {
    throw new Error(`${path} has inconsistent active encounter fields`);
  }
  if (phase === "awaiting_declaration" && prompt === null) {
    throw new Error(`${path}.prompt is required while awaiting a declaration`);
  }
  return {
    phase,
    outcome,
    winner,
    current_index: integerValue(data.current_index, `${path}.current_index`),
    active_actor_id: activeActorId,
    round_number: integerValue(data.round_number, `${path}.round_number`, 1),
    max_rounds: integerValue(data.max_rounds, `${path}.max_rounds`, 1),
    initiative_order: initiativeOrder,
    actors,
    prompt,
    result,
  };
}

export function parseSessionView(value: unknown): VttSessionView {
  const data = exactObject(
    value,
    ["schema_version", "session_id", "revision", "versions", "scene", "projection"],
    "session",
  );
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.session_view.v1"],
      "session.schema_version",
    ),
    session_id: stringValue(data.session_id, "session.session_id"),
    revision: integerValue(data.revision, "session.revision"),
    versions: parseVersions(data.versions, "session.versions"),
    scene: data.scene === null ? null : parseScene(data.scene, "session.scene"),
    projection: parseProjection(data.projection, "session.projection"),
  };
}

function parseAudience(value: unknown, path: string): string[] {
  const audience = stringArray(value, path);
  if (audience.length === 0 || new Set(audience).size !== audience.length) {
    throw new Error(`${path} must contain unique recipients`);
  }
  return audience;
}

function parseEventDraft(value: unknown, path: string): VttEventDraft {
  const data = exactObject(
    value,
    ["schema_version", "kind", "audience", "payload"],
    path,
  );
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.event_draft.v1"],
      `${path}.schema_version`,
    ),
    kind: stringValue(data.kind, `${path}.kind`),
    audience: parseAudience(data.audience, `${path}.audience`),
    payload: jsonObject(data.payload, `${path}.payload`),
  };
}

function parseEvent(value: unknown, path: string): VttEvent {
  const data = exactObject(
    value,
    [
      "schema_version",
      "event_id",
      "session_id",
      "sequence",
      "revision",
      "kind",
      "command_id",
      "versions",
      "causation_id",
      "audience",
      "payload",
    ],
    path,
  );
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.event.v1"],
      `${path}.schema_version`,
    ),
    event_id: stringValue(data.event_id, `${path}.event_id`),
    session_id: stringValue(data.session_id, `${path}.session_id`),
    sequence: integerValue(data.sequence, `${path}.sequence`, 1),
    revision: integerValue(data.revision, `${path}.revision`, 1),
    kind: stringValue(data.kind, `${path}.kind`),
    command_id: stringValue(data.command_id, `${path}.command_id`),
    versions: parseVersions(data.versions, `${path}.versions`),
    causation_id: nullableString(data.causation_id, `${path}.causation_id`),
    audience: parseAudience(data.audience, `${path}.audience`),
    payload: jsonObject(data.payload, `${path}.payload`),
  };
}

export function parseCommandResponse(value: unknown): VttCommandResponse {
  const base = objectValue(value, "response");
  if (base.response_type === "preview") {
    const data = exactObject(
      base,
      [
        "schema_version",
        "response_type",
        "command_id",
        "session_id",
        "revision",
        "versions",
        "projection",
        "events",
      ],
      "response",
    );
    if (!Array.isArray(data.events)) {
      throw new Error("response.events must be an array");
    }
    return {
      schema_version: literalValue(
        data.schema_version,
        ["vtt.preview_response.v1"],
        "response.schema_version",
      ),
      response_type: "preview",
      command_id: stringValue(data.command_id, "response.command_id"),
      session_id: stringValue(data.session_id, "response.session_id"),
      revision: integerValue(data.revision, "response.revision"),
      versions: parseVersions(data.versions, "response.versions"),
      projection: parseProjection(data.projection, "response.projection"),
      events: data.events.map((event, index) =>
        parseEventDraft(event, `response.events[${index}]`),
      ),
    };
  }
  if (base.response_type === "commit") {
    const data = exactObject(
      base,
      [
        "schema_version",
        "response_type",
        "command_id",
        "session_id",
        "replayed",
        "revision",
        "versions",
        "first_sequence",
        "last_sequence",
        "events",
      ],
      "response",
    );
    if (!Array.isArray(data.events)) {
      throw new Error("response.events must be an array");
    }
    return {
      schema_version: literalValue(
        data.schema_version,
        ["vtt.commit_response.v1"],
        "response.schema_version",
      ),
      response_type: "commit",
      command_id: stringValue(data.command_id, "response.command_id"),
      session_id: stringValue(data.session_id, "response.session_id"),
      replayed: booleanValue(data.replayed, "response.replayed"),
      revision: integerValue(data.revision, "response.revision", 1),
      versions: parseVersions(data.versions, "response.versions"),
      first_sequence:
        data.first_sequence === null
          ? null
          : integerValue(data.first_sequence, "response.first_sequence", 1),
      last_sequence:
        data.last_sequence === null
          ? null
          : integerValue(data.last_sequence, "response.last_sequence", 1),
      events: data.events.map((event, index) =>
        parseEvent(event, `response.events[${index}]`),
      ),
    };
  }
  throw new Error("response.response_type must be preview or commit");
}

function commandId(value?: string): string {
  return value ?? crypto.randomUUID();
}

function requireCommandText(value: string, field: string): string {
  if (value.trim() === "") {
    throw new Error(`${field} must not be empty`);
  }
  return value;
}

function requireRevision(value: number): number {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error("expectedRevision must be a non-negative integer");
  }
  return value;
}

export function buildStartCommand(input: {
  sessionId: string;
  expectedRevision: number;
  commandId?: string;
}): VttCommand {
  return {
    schema_version: "vtt.command.v1",
    command_id: commandId(input.commandId),
    session_id: requireCommandText(input.sessionId, "sessionId"),
    actor_id: null,
    expected_revision: requireRevision(input.expectedRevision),
    mode: "admin",
    kind: "dnd.start_encounter.v1",
    payload: {},
    intent_metadata: { surface: "echo-vault-web" },
  };
}

export function buildDeclarationCommand(input: {
  sessionId: string;
  expectedRevision: number;
  actorId: string;
  actionName: string;
  targetIds: string[];
  mode: "preview" | "commit";
  commandId?: string;
}): VttCommand {
  const actorId = requireCommandText(input.actorId, "actorId");
  const actionName = requireCommandText(input.actionName, "actionName");
  const targetIds = input.targetIds.map((targetId) =>
    requireCommandText(targetId, "targetId"),
  );
  return {
    schema_version: "vtt.command.v1",
    command_id: commandId(input.commandId),
    session_id: requireCommandText(input.sessionId, "sessionId"),
    actor_id: actorId,
    expected_revision: requireRevision(input.expectedRevision),
    mode: input.mode,
    kind: "dnd.declare_turn.v1",
    payload: {
      movement_path: [],
      action: {
        action_name: actionName,
        targets: targetIds.map((targetId) => ({ actor_id: targetId })),
        resource_spend: { amounts: {} },
        spell_slot_level: null,
        rationale: {},
      },
      bonus_action: null,
      reaction_policy: { mode: "auto", rationale: {} },
      ready: null,
      rationale: {},
    },
    intent_metadata: {
      surface: "echo-vault-web",
      selected_action: actionName,
      selected_targets: targetIds,
    },
  };
}

export function feetToCell(
  scene: SquareGridScene,
  position: [number, number, number],
): { column: number; row: number } {
  const column = Math.floor(
    (position[0] - scene.origin_ft.x_ft) / scene.cell_size_ft,
  );
  const row = Math.floor(
    (position[1] - scene.origin_ft.y_ft) / scene.cell_size_ft,
  );
  if (
    column < 0 ||
    row < 0 ||
    column >= scene.columns ||
    row >= scene.rows
  ) {
    throw new Error("Token position is outside the scene bounds");
  }
  return { column, row };
}

export class VttApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, JsonValue>;

  constructor(
    message: string,
    options: {
      code: string;
      status: number;
      details?: Record<string, JsonValue>;
    },
  ) {
    super(message);
    this.name = "VttApiError";
    this.code = options.code;
    this.status = options.status;
    this.details = options.details ?? {};
  }
}

async function responseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The table service returned unreadable data.", {
      code: "invalid_response",
      status: response.status,
    });
  }
  if (response.ok) {
    return value;
  }
  try {
    const error = exactObject(
      value,
      ["schema_version", "code", "message", "details"],
      "error",
    );
    literalValue(error.schema_version, ["vtt.error.v1"], "error.schema_version");
    throw new VttApiError(stringValue(error.message, "error.message"), {
      code: stringValue(error.code, "error.code"),
      status: response.status,
      details: jsonObject(error.details, "error.details"),
    });
  } catch (error) {
    if (error instanceof VttApiError) {
      throw error;
    }
    throw new VttApiError("The table service rejected the request.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getSessionView(signal?: AbortSignal): Promise<VttSessionView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/session`, {
    method: "GET",
    headers: { accept: "application/json" },
    signal,
  });
  return parseSessionView(await responseJson(response));
}

export async function postCommand(
  command: VttCommand,
  signal?: AbortSignal,
): Promise<VttCommandResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/commands`, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify(command),
    signal,
  });
  return parseCommandResponse(await responseJson(response));
}
