import {
  VTT_API_BASE_URL, parseActor, parseCommandResponse, parseProjection, parseScene,
  parseVersions, responseJson, type ActorProjection, type EncounterProjection,
  type SquareGridScene, type VttCommand, type VttCommitResponse, type VttVersionInfo,
} from "./vtt-client";

export interface AdventureChoice { id: string; label: string; description: string }
export interface AdventureView {
  schema_version: "adventure.view.v1";
  session_id: string;
  revision: number;
  versions: VttVersionInfo;
  title: string;
  subtitle: string;
  phase: "exploration" | "combat" | "complete" | "defeat";
  location: { id: string; name: string; description: string };
  scene: SquareGridScene;
  party: ActorProjection[];
  combat: EncounterProjection | null;
  choices: AdventureChoice[];
  journal: { id: string; title: string; text: string }[];
  inventory: { id: string; name: string; quantity: number; description: string }[];
  objective: string;
  dialogue: { speaker: string; text: string } | null;
  ending: { title: string; text: string } | null;
}

function object(value: unknown, keys: string[], path: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${path} must be an object`);
  const data = value as Record<string, unknown>;
  if (Object.keys(data).some((key) => !keys.includes(key))) throw new Error(`${path} contains unexpected fields`);
  if (keys.some((key) => !(key in data))) throw new Error(`${path} is missing required fields`);
  return data;
}
function text(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${path} must be nonempty text`);
  return value;
}
function integer(value: unknown, path: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) throw new Error(`${path} must be a non-negative integer`);
  return value as number;
}
function records<T>(value: unknown, path: string, parse: (value: unknown, path: string) => T, id: (entry: T) => string): T[] {
  if (!Array.isArray(value)) throw new Error(`${path} must be an array`);
  const entries = value.map((entry, index) => parse(entry, `${path}[${index}]`));
  if (new Set(entries.map(id)).size !== entries.length) throw new Error(`${path} must contain unique IDs`);
  return entries;
}
function textRecord<K extends string>(value: unknown, keys: K[], path: string): Record<K, string> {
  const data = object(value, keys, path);
  return Object.fromEntries(keys.map((key) => [key, text(data[key], `${path}.${key}`)])) as Record<K, string>;
}

export function parseAdventureView(value: unknown): AdventureView {
  const data = object(value, ["schema_version", "session_id", "revision", "versions", "title", "subtitle", "phase", "location", "scene", "party", "combat", "choices", "journal", "inventory", "objective", "dialogue", "ending"], "adventure");
  if (data.schema_version !== "adventure.view.v1") throw new Error("Unsupported adventure schema");
  const phase = text(data.phase, "adventure.phase");
  if (!["exploration", "combat", "complete", "defeat"].includes(phase)) throw new Error("Unsupported adventure phase");
  const combat = data.combat === null ? null : parseProjection(data.combat, "adventure.combat");
  if (phase === "combat" && combat === null) throw new Error("Combat phase requires combat projection");
  return {
    schema_version: "adventure.view.v1", session_id: text(data.session_id, "adventure.session_id"),
    revision: integer(data.revision, "adventure.revision"), versions: parseVersions(data.versions, "adventure.versions"),
    title: text(data.title, "adventure.title"), subtitle: text(data.subtitle, "adventure.subtitle"),
    phase: phase as AdventureView["phase"],
    location: textRecord(data.location, ["id", "name", "description"], "adventure.location"),
    scene: parseScene(data.scene, "adventure.scene"),
    party: records(data.party, "adventure.party", parseActor, (actor) => actor.actor_id), combat,
    choices: records(data.choices, "adventure.choices", (entry, path) => textRecord(entry, ["id", "label", "description"], path), (entry) => entry.id),
    journal: records(data.journal, "adventure.journal", (entry, path) => textRecord(entry, ["id", "title", "text"], path), (entry) => entry.id),
    inventory: records(data.inventory, "adventure.inventory", (entry, path) => {
      const item = object(entry, ["id", "name", "quantity", "description"], path);
      return { id: text(item.id, `${path}.id`), name: text(item.name, `${path}.name`),
        quantity: integer(item.quantity, `${path}.quantity`), description: text(item.description, `${path}.description`) };
    }, (entry) => entry.id),
    objective: text(data.objective, "adventure.objective"),
    dialogue: data.dialogue === null ? null : textRecord(data.dialogue, ["speaker", "text"], "adventure.dialogue"),
    ending: data.ending === null ? null : textRecord(data.ending, ["title", "text"], "adventure.ending"),
  };
}

export function buildAdventureChoice(view: AdventureView, choiceId: string, commandId = crypto.randomUUID()): VttCommand {
  if (!view.choices.some((choice) => choice.id === choiceId)) throw new Error("That choice is no longer available.");
  return { schema_version: "vtt.command.v1", command_id: commandId, session_id: view.session_id,
    actor_id: null, expected_revision: view.revision, mode: "commit", kind: "adventure.choose.v1",
    payload: { choice_id: choiceId }, intent_metadata: { surface: "lantern-adventure" } };
}

export async function getAdventureView(signal?: AbortSignal): Promise<AdventureView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/adventure`, {
    method: "GET", headers: { Accept: "application/json" }, cache: "no-store", signal,
  });
  return parseAdventureView(await responseJson(response));
}

export async function postAdventureCommand(command: VttCommand): Promise<VttCommitResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/adventure/commands`, {
    method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(command), signal: AbortSignal.timeout(20_000),
  });
  const receipt = parseCommandResponse(await responseJson(response));
  if (receipt.response_type !== "commit" || receipt.command_id !== command.command_id || receipt.session_id !== command.session_id) {
    throw new Error("The adventure returned a mismatched command receipt. Retry to confirm the saved result.");
  }
  return receipt;
}
