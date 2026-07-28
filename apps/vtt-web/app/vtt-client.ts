import { buildVttRequestHeaders } from "./vtt-transport";

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

export type Position3 = [number, number, number];

export interface GridCell {
  column: number;
  row: number;
}

export interface GridMovementPlan {
  destination: GridCell;
  distanceFt: number;
  end: Position3;
  path: Position3[];
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
  position: Position3;
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

export interface TurnMovementChoice {
  origin: Position3;
  remaining_ft: number;
}

export interface TurnActionChoice {
  action_name: string;
  action_cost: "action" | "bonus" | "none";
  target_mode: string;
  requires_explicit_targets: boolean;
  selectable_target_ids: string[];
  legal_target_ids: string[];
  reason: "no_legal_targets" | null;
}

export interface TurnChoices {
  schema_version: "dnd.turn-choices.v1";
  actor_id: string;
  movement: TurnMovementChoice;
  actions: TurnActionChoice[];
  reason: "no_available_actions" | null;
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
  choices: TurnChoices | null;
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

function sortedUniqueStringArray(value: unknown, path: string): string[] {
  const items = stringArray(value, path);
  if (new Set(items).size !== items.length) {
    throw new Error(`${path} must contain unique actor IDs`);
  }
  if (items.some((item, index) => index > 0 && item < items[index - 1])) {
    throw new Error(`${path} must use sorted actor-ID order`);
  }
  return items;
}

function parsePosition(value: unknown, path: string): Position3 {
  if (!Array.isArray(value) || value.length !== 3) {
    throw new Error(`${path} must contain exactly three coordinates`);
  }
  return [
    finiteNumber(value[0], `${path}[0]`),
    finiteNumber(value[1], `${path}[1]`),
    finiteNumber(value[2], `${path}[2]`),
  ];
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
  const position = parsePosition(data.position, `${path}.position`);
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

const EXPLICIT_TARGET_MODES = new Set([
  "single_enemy",
  "single_ally",
  "single_creature",
  "n_enemies",
  "n_allies",
  "random_enemy",
  "random_ally",
]);

function parseTurnActionChoice(
  value: unknown,
  path: string,
): TurnActionChoice {
  const data = exactObject(
    value,
    [
      "action_name",
      "action_cost",
      "target_mode",
      "requires_explicit_targets",
      "selectable_target_ids",
      "legal_target_ids",
      "reason",
    ],
    path,
  );
  const targetMode = stringValue(data.target_mode, `${path}.target_mode`);
  const requiresExplicitTargets = booleanValue(
    data.requires_explicit_targets,
    `${path}.requires_explicit_targets`,
  );
  if (requiresExplicitTargets !== EXPLICIT_TARGET_MODES.has(targetMode)) {
    throw new Error(
      `${path}.requires_explicit_targets must match target_mode`,
    );
  }
  const selectableTargetIds = sortedUniqueStringArray(
    data.selectable_target_ids,
    `${path}.selectable_target_ids`,
  );
  const legalTargetIds = sortedUniqueStringArray(
    data.legal_target_ids,
    `${path}.legal_target_ids`,
  );
  const selectable = new Set(selectableTargetIds);
  if (legalTargetIds.some((actorId) => !selectable.has(actorId))) {
    throw new Error(
      `${path}.legal_target_ids must be a subset of selectable_target_ids`,
    );
  }
  const reason =
    data.reason === null
      ? null
      : literalValue(
          data.reason,
          ["no_legal_targets"],
          `${path}.reason`,
        );
  if (legalTargetIds.length > 0 && reason !== null) {
    throw new Error(`${path}.reason must be null when legal targets exist`);
  }
  if (legalTargetIds.length === 0 && reason !== "no_legal_targets") {
    throw new Error(
      `${path}.reason must be no_legal_targets when no targets are legal now`,
    );
  }
  return {
    action_name: stringValue(data.action_name, `${path}.action_name`),
    action_cost: literalValue(
      data.action_cost,
      ["action", "bonus", "none"],
      `${path}.action_cost`,
    ),
    target_mode: targetMode,
    requires_explicit_targets: requiresExplicitTargets,
    selectable_target_ids: selectableTargetIds,
    legal_target_ids: legalTargetIds,
    reason,
  };
}

function parseTurnChoices(value: unknown, path: string): TurnChoices | null {
  if (value === null) return null;
  const data = exactObject(
    value,
    ["schema_version", "actor_id", "movement", "actions", "reason"],
    path,
  );
  const movementData = exactObject(
    data.movement,
    ["origin", "remaining_ft"],
    `${path}.movement`,
  );
  const remainingFt = finiteNumber(
    movementData.remaining_ft,
    `${path}.movement.remaining_ft`,
  );
  if (remainingFt < 0) {
    throw new Error(`${path}.movement.remaining_ft must be non-negative`);
  }
  if (!Array.isArray(data.actions)) {
    throw new Error(`${path}.actions must be an array`);
  }
  const actions = data.actions.map((action, index) =>
    parseTurnActionChoice(action, `${path}.actions[${index}]`),
  );
  const names = actions.map((choice) => choice.action_name);
  if (new Set(names).size !== names.length) {
    throw new Error(`${path}.actions must not contain duplicate action names`);
  }
  const reason =
    data.reason === null
      ? null
      : literalValue(
          data.reason,
          ["no_available_actions"],
          `${path}.reason`,
        );
  if (actions.length > 0 && reason !== null) {
    throw new Error(`${path}.reason must be null when actions are available`);
  }
  if (actions.length === 0 && reason !== "no_available_actions") {
    throw new Error(
      `${path}.reason must be no_available_actions when actions are empty`,
    );
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["dnd.turn-choices.v1"],
      `${path}.schema_version`,
    ),
    actor_id: stringValue(data.actor_id, `${path}.actor_id`),
    movement: {
      origin: parsePosition(movementData.origin, `${path}.movement.origin`),
      remaining_ft: remainingFt,
    },
    actions,
    reason,
  };
}

function samePosition(left: Position3, right: Position3): boolean {
  return left.every((coordinate, index) => coordinate === right[index]);
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
      "choices",
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
  const choices = parseTurnChoices(data.choices, `${path}.choices`);
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
  if (phase === "awaiting_declaration") {
    if (choices === null) {
      throw new Error(`${path}.choices is required while awaiting a declaration`);
    }
    if (
      choices.actor_id !== activeActorId ||
      prompt?.actor_id !== activeActorId
    ) {
      throw new Error(
        `${path}.choices.actor_id and prompt.actor_id must match active_actor_id`,
      );
    }
    const activeActor = actors[choices.actor_id];
    if (!activeActor) {
      throw new Error(`${path}.choices.actor_id must identify a projected actor`);
    }
    if (!samePosition(choices.movement.origin, activeActor.position)) {
      throw new Error(
        `${path}.choices.movement.origin must match the active actor position`,
      );
    }
    if (choices.movement.remaining_ft !== activeActor.movement_remaining) {
      throw new Error(
        `${path}.choices.movement.remaining_ft must match the active actor movement`,
      );
    }
    const actionIndexes = new Map<string, number>();
    for (const [index, action] of activeActor.actions.entries()) {
      if (!actionIndexes.has(action.name)) {
        actionIndexes.set(action.name, index);
      }
    }
    let previousIndex = -1;
    for (const [choiceIndex, choice] of choices.actions.entries()) {
      const actorActionIndex = actionIndexes.get(choice.action_name);
      if (actorActionIndex === undefined) {
        throw new Error(
          `${path}.choices.actions[${choiceIndex}] must identify an active actor action`,
        );
      }
      if (actorActionIndex <= previousIndex) {
        throw new Error(
          `${path}.choices.actions must preserve canonical actor action order`,
        );
      }
      previousIndex = actorActionIndex;
      const actorAction = activeActor.actions[actorActionIndex];
      if (
        choice.action_cost !== actorAction.action_cost ||
        choice.target_mode !== actorAction.target_mode
      ) {
        throw new Error(
          `${path}.choices.actions[${choiceIndex}] must match active actor action metadata`,
        );
      }
      for (const targetId of choice.selectable_target_ids) {
        if (!(targetId in actors)) {
          throw new Error(
            `${path}.choices.actions[${choiceIndex}].selectable_target_ids must identify projected actors`,
          );
        }
      }
    }
  } else if (choices !== null) {
    throw new Error(`${path}.choices must be null during the ${phase} phase`);
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
    choices,
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

export function parseVttEvent(value: unknown): VttEvent {
  return parseEvent(value, "event");
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
  movementPath: Position3[];
  mode: "preview" | "commit";
  commandId?: string;
}): VttCommand {
  const actorId = requireCommandText(input.actorId, "actorId");
  const actionName = requireCommandText(input.actionName, "actionName");
  const targetIds = input.targetIds.map((targetId) =>
    requireCommandText(targetId, "targetId"),
  );
  const movementPath = input.movementPath.map((waypoint, index) => {
    if (!Array.isArray(waypoint) || waypoint.length !== 3) {
      throw new Error(`movementPath[${index}] must contain three coordinates`);
    }
    if (
      waypoint.some(
        (coordinate) =>
          typeof coordinate !== "number" || !Number.isFinite(coordinate),
      )
    ) {
      throw new Error(`movementPath[${index}] coordinates must be finite numbers`);
    }
    return [...waypoint] as Position3;
  });
  return {
    schema_version: "vtt.command.v1",
    command_id: commandId(input.commandId),
    session_id: requireCommandText(input.sessionId, "sessionId"),
    actor_id: actorId,
    expected_revision: requireRevision(input.expectedRevision),
    mode: input.mode,
    kind: "dnd.declare_turn.v1",
    payload: {
      movement_path: movementPath,
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
      movement_waypoints: movementPath.length,
      selected_action: actionName,
      selected_targets: targetIds,
    },
  };
}

export function feetToCell(
  scene: SquareGridScene,
  position: Position3,
): GridCell {
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

function validateGridCell(scene: SquareGridScene, cell: GridCell): GridCell {
  if (
    !Number.isInteger(cell.column) ||
    !Number.isInteger(cell.row) ||
    cell.column < 0 ||
    cell.row < 0 ||
    cell.column >= scene.columns ||
    cell.row >= scene.rows
  ) {
    throw new Error("Grid cell is outside the scene bounds");
  }
  return { column: cell.column, row: cell.row };
}

export function cellToFeet(
  scene: SquareGridScene,
  destination: GridCell,
): Position3 {
  const cell = validateGridCell(scene, destination);
  const halfCell = scene.cell_size_ft / 2;
  return [
    scene.origin_ft.x_ft + cell.column * scene.cell_size_ft + halfCell,
    scene.origin_ft.y_ft + cell.row * scene.cell_size_ft + halfCell,
    scene.origin_ft.z_ft,
  ];
}

export function planGridMovement(input: {
  scene: SquareGridScene;
  start: Position3;
  destination: GridCell;
  movementRemaining: number;
}): GridMovementPlan {
  if (
    !Array.isArray(input.start) ||
    input.start.length !== 3 ||
    input.start.some(
      (coordinate) =>
        typeof coordinate !== "number" || !Number.isFinite(coordinate),
    )
  ) {
    throw new Error("Movement start must contain three finite coordinates");
  }
  if (
    typeof input.movementRemaining !== "number" ||
    !Number.isFinite(input.movementRemaining) ||
    input.movementRemaining < 0
  ) {
    throw new Error("movementRemaining must be a non-negative finite number");
  }

  const destination = validateGridCell(input.scene, input.destination);
  const projectedEnd = cellToFeet(input.scene, destination);
  const end: Position3 = [projectedEnd[0], projectedEnd[1], input.start[2]];
  const distanceFt = Math.max(
    Math.abs(end[0] - input.start[0]),
    Math.abs(end[1] - input.start[1]),
    Math.abs(end[2] - input.start[2]),
  );
  if (distanceFt > input.movementRemaining + 1e-6) {
    throw new Error(
      `Destination exceeds remaining movement (${distanceFt} ft > ${input.movementRemaining} ft)`,
    );
  }

  const start = [...input.start] as Position3;
  return {
    destination,
    distanceFt,
    end,
    path: distanceFt <= 1e-6 ? [] : [start, end],
  };
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

export async function getSessionView(
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<VttSessionView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/session`, {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
    }),
    signal,
  });
  return parseSessionView(await responseJson(response));
}

export function vttEventsUrl(after: number): string {
  if (!Number.isInteger(after) || after < 0) {
    throw new Error("Event cursor must be a non-negative integer");
  }
  return `${VTT_API_BASE_URL}/api/v1/events?after=${after}`;
}

export function parseVttSseBlock(block: string): VttEvent | null {
  if (typeof block !== "string") throw new Error("VTT SSE block must be text");
  const fields = new Map<string, string>();
  for (const rawLine of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    if (separator <= 0) throw new Error("VTT SSE contains a malformed field");
    const name = rawLine.slice(0, separator);
    const fieldValue = rawLine.slice(separator + 1).replace(/^ /, "");
    if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) {
      throw new Error("VTT SSE contains duplicate or unsupported fields");
    }
    fields.set(name, fieldValue);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.event") {
    throw new Error("VTT SSE event type is invalid");
  }
  const idText = fields.get("id");
  const dataText = fields.get("data");
  if (!idText || !dataText || !/^\d+$/.test(idText)) {
    throw new Error("VTT SSE id must be a canonical integer");
  }
  const id = Number(idText);
  if (!Number.isSafeInteger(id) || String(id) !== idText) {
    throw new Error("VTT SSE id must be a canonical safe integer");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(dataText);
  } catch {
    throw new Error("VTT SSE data must be valid JSON");
  }
  const event = parseVttEvent(decoded);
  if (id !== event.sequence) {
    throw new Error("VTT SSE id must match the event sequence");
  }
  return event;
}

function findSseBoundary(buffer: string): { index: number; length: number } | null {
  const unix = buffer.indexOf("\n\n");
  const windows = buffer.indexOf("\r\n\r\n");
  if (unix < 0 && windows < 0) return null;
  if (windows >= 0 && (unix < 0 || windows < unix)) {
    return { index: windows, length: 4 };
  }
  return { index: unix, length: 2 };
}

export async function streamVttEvents(input: {
  after: number;
  bearerToken?: string | null;
  signal: AbortSignal;
  onEvent: (event: VttEvent) => void;
  onOpen?: () => void;
}): Promise<number> {
  if (!Number.isSafeInteger(input.after) || input.after < 0) {
    throw new Error("Event cursor must be a non-negative safe integer");
  }
  let cursor = input.after;
  const response = await fetch(vttEventsUrl(cursor), {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "text/event-stream",
      bearerToken: input.bearerToken,
    }),
    signal: input.signal,
  });
  if (!response.ok) await responseJson(response);
  if (!response.body) {
    throw new VttApiError("The event stream has no response body.", {
      code: "invalid_response",
      status: response.status,
    });
  }
  input.onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let boundary = findSseBoundary(buffer);
    while (boundary !== null) {
      const event = parseVttSseBlock(buffer.slice(0, boundary.index));
      buffer = buffer.slice(boundary.index + boundary.length);
      if (event && event.sequence > cursor) {
        cursor = event.sequence;
        input.onEvent(event);
      }
      boundary = findSseBoundary(buffer);
    }
    if (done) break;
  }
  if (buffer.trim() !== "") {
    throw new Error("VTT SSE ended with an incomplete event");
  }
  return cursor;
}

export async function postCommand(
  command: VttCommand,
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<VttCommandResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/commands`, {
    method: "POST",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
      contentType: "application/json",
    }),
    body: JSON.stringify(command),
    signal,
  });
  return parseCommandResponse(await responseJson(response));
}
