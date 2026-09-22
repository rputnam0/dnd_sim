import { VTT_API_BASE_URL, VttApiError, responseJson } from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";

export type JournalBlock =
  | { schema_version: "vtt.journal_block.v1"; block_type: "paragraph"; text: string }
  | { schema_version: "vtt.journal_block.v1"; block_type: "heading"; level: 1 | 2 | 3; text: string }
  | { schema_version: "vtt.journal_block.v1"; block_type: "bullet_list"; items: string[] }
  | { schema_version: "vtt.journal_block.v1"; block_type: "document_link"; document_id: string; label: string };

export interface JournalFolder {
  schema_version: "vtt.journal_folder.v1";
  folder_id: string;
  parent_folder_id: string | null;
  name: string;
}

export interface JournalMapPin {
  schema_version: "vtt.journal_map_pin.v1";
  scene_id: string;
  position: { x_ft: number; y_ft: number; z_ft: number };
  color: string;
}

export interface JournalDocument {
  schema_version: "vtt.journal_document.v1";
  document_id: string;
  document_type: "note" | "handout";
  folder_id: string | null;
  title: string;
  audience: string[];
  tags: string[];
  favorite: boolean;
  blocks: JournalBlock[];
  map_pin: JournalMapPin | null;
}

export interface JournalView {
  schema_version: "vtt.journal_view.v1";
  session_id: string;
  table_id: string;
  revision: number;
  folders: JournalFolder[];
  documents: JournalDocument[];
}

export type JournalCommand =
  | { schema_version: "vtt.journal_command.v1"; command_type: "put_document"; table_id: string; command_id: string; expected_revision: number; document: JournalDocument }
  | { schema_version: "vtt.journal_command.v1"; command_type: "delete_document"; table_id: string; command_id: string; expected_revision: number; document_id: string }
  | { schema_version: "vtt.journal_command.v1"; command_type: "put_folder"; table_id: string; command_id: string; expected_revision: number; folder: JournalFolder }
  | { schema_version: "vtt.journal_command.v1"; command_type: "delete_folder"; table_id: string; command_id: string; expected_revision: number; folder_id: string };

export interface JournalRequest {
  schema_version: "vtt.journal_request.v1";
  session_id: string;
  command: JournalCommand;
}

export type JournalEvent =
  | { schema_version: "vtt.journal_event.v1"; event_type: "document_put"; table_id: string; event_id: string; sequence: number; revision: number; command_id: string; document: JournalDocument }
  | { schema_version: "vtt.journal_event.v1"; event_type: "document_deleted"; table_id: string; event_id: string; sequence: number; revision: number; command_id: string; document: JournalDocument }
  | { schema_version: "vtt.journal_event.v1"; event_type: "folder_put"; table_id: string; event_id: string; sequence: number; revision: number; command_id: string; folder: JournalFolder }
  | { schema_version: "vtt.journal_event.v1"; event_type: "folder_deleted"; table_id: string; event_id: string; sequence: number; revision: number; command_id: string; folder: JournalFolder };

type ObjectValue = Record<string, unknown>;

function objectValue(value: unknown, path: string): ObjectValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${path} must be an object`);
  return value as ObjectValue;
}

function exactObject(value: unknown, keys: string[], path: string): ObjectValue {
  const data = objectValue(value, path);
  const expected = new Set(keys);
  for (const key of Object.keys(data)) if (!expected.has(key)) throw new Error(`${path} contains unexpected field "${key}"`);
  for (const key of keys) if (!(key in data)) throw new Error(`${path} is missing field "${key}"`);
  return data;
}

function literal<T extends string>(value: unknown, allowed: readonly T[], path: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) throw new Error(`${path} is invalid`);
  return value as T;
}

function text(value: unknown, path: string, max = 128, multiline = false): string {
  if (typeof value !== "string" || !value || value.trim() !== value || Array.from(value).length > max) throw new Error(`${path} must be canonical text`);
  if (Array.from(value).some((character) => /\p{Cc}/u.test(character) && !(multiline && character === "\n"))) throw new Error(`${path} contains a control character`);
  return value;
}

function integer(value: unknown, path: string, min = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min) throw new Error(`${path} must be an integer`);
  return value;
}

function finite(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${path} must be finite`);
  return value;
}

function stringArray(value: unknown, path: string, max: number, sorted = false, itemMax = 128): string[] {
  if (!Array.isArray(value) || value.length > max) throw new Error(`${path} must be a bounded array`);
  const result = value.map((item, index) => {
    if (typeof item === "string" && Array.from(item).length > itemMax) throw new Error(`${path}[${index}] must be at most ${itemMax} characters`);
    return text(item, `${path}[${index}]`, itemMax);
  });
  if (new Set(result).size !== result.length || (sorted && result.some((item, index) => index > 0 && compareCodePoints(result[index - 1], item) >= 0))) throw new Error(`${path} must be unique${sorted ? " and sorted" : ""}`);
  return result;
}

function parseAudience(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 128) throw new Error(`${path} must contain 1-128 audience selectors`);
  const audience = value.map((selector, index) => {
    if (selector === "all" || selector === "role:gm" || selector === "role:player" || selector === "role:spectator") return selector;
    if (typeof selector !== "string") throw new Error(`${path}[${index}] must be an audience selector`);
    if (selector.startsWith("participant:")) {
      const suffix = selector.slice("participant:".length);
      if (Array.from(suffix).length > 128) throw new Error(`${path}[${index}] participant ID must be at most 128 characters`);
      if (suffix.includes(":")) throw new Error(`${path}[${index}] participant ID must not contain a colon`);
      return `participant:${text(suffix, `${path}[${index}] participant ID`, 128)}`;
    }
    if (selector.startsWith("actor:")) {
      const suffix = selector.slice("actor:".length);
      if (Array.from(suffix).length > 128) throw new Error(`${path}[${index}] actor ID must be at most 128 characters`);
      if (suffix.includes(":")) throw new Error(`${path}[${index}] actor ID must not contain a colon`);
      return `actor:${text(suffix, `${path}[${index}] actor ID`, 128)}`;
    }
    throw new Error(`${path} contains an unsupported audience selector`);
  });
  if (new Set(audience).size !== audience.length) throw new Error(`${path} audience selectors must be unique`);
  if (audience.includes("all")) {
    if (audience.length !== 1 || audience[0] !== "all") throw new Error(`${path} audience selector all must be used alone`);
    return audience;
  }
  if (audience.some((item, index) => index > 0 && compareCodePoints(audience[index - 1], item) >= 0)) throw new Error(`${path} audience selectors must be sorted`);
  for (const selector of audience) {
    if (["role:gm", "role:player", "role:spectator"].includes(selector)) continue;
    if (selector.startsWith("participant:") || selector.startsWith("actor:")) continue;
  }
  return audience;
}

export function parseJournalFolder(value: unknown, path = "folder"): JournalFolder {
  const data = exactObject(value, ["schema_version", "folder_id", "parent_folder_id", "name"], path);
  const folderId = text(data.folder_id, `${path}.folder_id`);
  const parent = data.parent_folder_id === null ? null : text(data.parent_folder_id, `${path}.parent_folder_id`);
  if (parent === folderId) throw new Error(`${path} cannot parent itself`);
  return { schema_version: literal(data.schema_version, ["vtt.journal_folder.v1"], `${path}.schema_version`), folder_id: folderId, parent_folder_id: parent, name: text(data.name, `${path}.name`, 160) };
}

export function parseJournalDocument(value: unknown, path = "document"): JournalDocument {
  const data = exactObject(value, ["schema_version", "document_id", "document_type", "folder_id", "title", "audience", "tags", "favorite", "blocks", "map_pin"], path);
  const documentId = text(data.document_id, `${path}.document_id`);
  if (!Array.isArray(data.blocks) || data.blocks.length < 1 || data.blocks.length > 256) throw new Error(`${path}.blocks must contain 1-256 blocks`);
  const blocks: JournalBlock[] = data.blocks.map((raw, index) => {
    const base = objectValue(raw, `${path}.blocks[${index}]`);
    const blockType = literal(base.block_type, ["paragraph", "heading", "bullet_list", "document_link"] as const, `${path}.blocks[${index}].block_type`);
    if (blockType === "paragraph") {
      const block = exactObject(raw, ["schema_version", "block_type", "text"], `${path}.blocks[${index}]`);
      return { schema_version: literal(block.schema_version, ["vtt.journal_block.v1"], "block.schema_version"), block_type: blockType, text: text(block.text, "block.text", 50_000, true) };
    }
    if (blockType === "heading") {
      const block = exactObject(raw, ["schema_version", "block_type", "level", "text"], `${path}.blocks[${index}]`);
      const level = integer(block.level, "block.level", 1);
      if (level > 3) throw new Error("block.level must be 1-3");
      return { schema_version: literal(block.schema_version, ["vtt.journal_block.v1"], "block.schema_version"), block_type: blockType, level: level as 1 | 2 | 3, text: text(block.text, "block.text", 500) };
    }
    if (blockType === "bullet_list") {
      const block = exactObject(raw, ["schema_version", "block_type", "items"], `${path}.blocks[${index}]`);
      if (!Array.isArray(block.items) || block.items.length < 1 || block.items.length > 64) throw new Error("block.items must contain 1-64 items");
      return { schema_version: literal(block.schema_version, ["vtt.journal_block.v1"], "block.schema_version"), block_type: blockType, items: block.items.map((item, itemIndex) => text(item, `block.items[${itemIndex}]`, 2_000)) };
    }
    const block = exactObject(raw, ["schema_version", "block_type", "document_id", "label"], `${path}.blocks[${index}]`);
    const target = text(block.document_id, "block.document_id");
    if (target === documentId) throw new Error("document cannot link to itself");
    return { schema_version: literal(block.schema_version, ["vtt.journal_block.v1"], "block.schema_version"), block_type: blockType, document_id: target, label: text(block.label, "block.label", 500) };
  });
  const title = text(data.title, `${path}.title`, 160);
  let textSize = Array.from(title).length;
  for (const block of blocks) {
    if (block.block_type === "paragraph" || block.block_type === "heading") textSize += Array.from(block.text).length;
    else if (block.block_type === "bullet_list") textSize += block.items.reduce((sum, item) => sum + Array.from(item).length, 0);
    else textSize += Array.from(block.label).length;
  }
  if (textSize > 50_000) throw new Error(`${path} text must be at most 50,000 characters`);
  let mapPin: JournalMapPin | null = null;
  if (data.map_pin !== null) {
    const pin = exactObject(data.map_pin, ["schema_version", "scene_id", "position", "color"], `${path}.map_pin`);
    const point = exactObject(pin.position, ["x_ft", "y_ft", "z_ft"], `${path}.map_pin.position`);
    if (typeof pin.color !== "string" || !/^#[0-9a-f]{6}$/.test(pin.color)) throw new Error(`${path}.map_pin.color is invalid`);
    const position = { x_ft: finite(point.x_ft, "x_ft"), y_ft: finite(point.y_ft, "y_ft"), z_ft: finite(point.z_ft, "z_ft") };
    if (Object.values(position).some((coordinate) => Math.abs(coordinate) > 1_000_000)) throw new Error(`${path}.map_pin.position is outside the supported range`);
    mapPin = { schema_version: literal(pin.schema_version, ["vtt.journal_map_pin.v1"], "pin.schema_version"), scene_id: text(pin.scene_id, "pin.scene_id"), position, color: pin.color };
  }
  if (typeof data.favorite !== "boolean") throw new Error(`${path}.favorite must be boolean`);
  return { schema_version: literal(data.schema_version, ["vtt.journal_document.v1"], `${path}.schema_version`), document_id: documentId, document_type: literal(data.document_type, ["note", "handout"], `${path}.document_type`), folder_id: data.folder_id === null ? null : text(data.folder_id, `${path}.folder_id`), title, audience: parseAudience(data.audience, `${path}.audience`), tags: stringArray(data.tags, `${path}.tags`, 32, true, 64), favorite: data.favorite, blocks, map_pin: mapPin };
}

function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left, (character) => character.codePointAt(0) as number);
  const b = Array.from(right, (character) => character.codePointAt(0) as number);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) if (a[index] !== b[index]) return a[index] - b[index];
  return a.length - b.length;
}

function compareDocuments(left: JournalDocument, right: JournalDocument): number {
  if (left.favorite !== right.favorite) return left.favorite ? -1 : 1;
  return compareCodePoints(left.title, right.title) || compareCodePoints(left.document_id, right.document_id);
}

function compareFolders(left: JournalFolder, right: JournalFolder): number {
  return compareCodePoints(left.parent_folder_id ?? "", right.parent_folder_id ?? "") || compareCodePoints(left.name, right.name) || compareCodePoints(left.folder_id, right.folder_id);
}

export function parseJournalView(value: unknown): JournalView {
  const data = exactObject(value, ["schema_version", "session_id", "table_id", "revision", "folders", "documents"], "journal");
  if (!Array.isArray(data.folders) || !Array.isArray(data.documents)) throw new Error("journal records must be arrays");
  if (data.folders.length > 256 || data.documents.length > 2_000) throw new Error("journal record counts exceed the supported limits");
  const folders = data.folders.map((item, index) => parseJournalFolder(item, `journal.folders[${index}]`));
  const documents = data.documents.map((item, index) => parseJournalDocument(item, `journal.documents[${index}]`));
  const folderIds = folders.map((item) => item.folder_id);
  const documentIds = documents.map((item) => item.document_id);
  if (new Set(folderIds).size !== folderIds.length || new Set(documentIds).size !== documentIds.length) throw new Error("journal record IDs must be unique");
  const expectedFolders = [...folders].sort(compareFolders);
  if (expectedFolders.some((item, index) => item.folder_id !== folders[index]?.folder_id)) throw new Error("journal folders are not canonically ordered");
  const byFolderId = new Map(folders.map((folder) => [folder.folder_id, folder]));
  for (const folder of folders) {
    let current = folder;
    const seen = new Set<string>();
    let depth = 1;
    while (current.parent_folder_id !== null) {
      const parent = byFolderId.get(current.parent_folder_id);
      if (!parent || seen.has(parent.folder_id)) throw new Error("journal folder graph is invalid");
      seen.add(current.folder_id);
      current = parent;
      depth += 1;
      if (depth > 16) throw new Error("journal folder depth exceeds 16");
    }
  }
  if (documents.some((document) => document.folder_id !== null && !byFolderId.has(document.folder_id))) throw new Error("journal document references a missing folder");
  const documentIdSet = new Set(documentIds);
  if (documents.some((document) => document.blocks.some((block) => block.block_type === "document_link" && !documentIdSet.has(block.document_id)))) throw new Error("journal document references a missing linked document");
  const expectedDocuments = [...documents].sort(compareDocuments);
  if (expectedDocuments.some((item, index) => item.document_id !== documents[index]?.document_id)) throw new Error("journal documents are not canonically ordered");
  return { schema_version: literal(data.schema_version, ["vtt.journal_view.v1"], "journal.schema_version"), session_id: text(data.session_id, "journal.session_id"), table_id: text(data.table_id, "journal.table_id"), revision: integer(data.revision, "journal.revision"), folders, documents };
}

export function journalViewMatchesIdentity(view: JournalView, identity: { sessionId: string | null; tableId: string | null }): boolean {
  return identity.sessionId !== null && identity.tableId !== null && view.session_id === identity.sessionId && view.table_id === identity.tableId;
}

export function applyJournalEvent(view: JournalView, event: JournalEvent): JournalView {
  if (event.table_id !== view.table_id) throw new Error("journal event table mismatch");
  if (event.revision <= view.revision) return view;
  const folders = new Map(view.folders.map((item) => [item.folder_id, item]));
  const documents = new Map(view.documents.map((item) => [item.document_id, item]));
  if (event.event_type === "folder_put") folders.set(event.folder.folder_id, event.folder);
  else if (event.event_type === "folder_deleted") folders.delete(event.folder.folder_id);
  else if (event.event_type === "document_put") documents.set(event.document.document_id, event.document);
  else documents.delete(event.document.document_id);
  const survivingIds = new Set(documents.keys());
  const projectedDocuments = [...documents.values()].map((document) => ({
    ...document,
    blocks: document.blocks.filter(
      (block) => block.block_type !== "document_link" || survivingIds.has(block.document_id),
    ),
  }));
  return parseJournalView({ ...view, revision: event.revision, folders: [...folders.values()].sort(compareFolders), documents: projectedDocuments.sort(compareDocuments) });
}

export function parseJournalEvent(value: unknown): JournalEvent {
  const base = objectValue(value, "journal event");
  const eventType = literal(base.event_type, ["document_put", "document_deleted", "folder_put", "folder_deleted"] as const, "journal event.event_type");
  const recordKey = eventType.startsWith("document_") ? "document" : "folder";
  const data = exactObject(value, ["schema_version", "event_type", "table_id", "event_id", "sequence", "revision", "command_id", recordKey], "journal event");
  const common = {
    schema_version: literal(data.schema_version, ["vtt.journal_event.v1"], "journal event.schema_version"),
    table_id: text(data.table_id, "journal event.table_id"),
    event_id: text(data.event_id, "journal event.event_id", 512),
    sequence: integer(data.sequence, "journal event.sequence", 1),
    revision: integer(data.revision, "journal event.revision", 1),
    command_id: text(data.command_id, "journal event.command_id"),
  };
  if (common.sequence !== common.revision) throw new Error("journal event sequence must equal revision");
  if (common.event_id !== `${common.table_id}:journal:${common.sequence}`) throw new Error("journal event identity is invalid");
  if (eventType === "document_put" || eventType === "document_deleted") {
    return { ...common, event_type: eventType, document: parseJournalDocument(data.document, "journal event.document") };
  }
  return { ...common, event_type: eventType, folder: parseJournalFolder(data.folder, "journal event.folder") };
}

export function parseJournalSseBlock(block: string): JournalEvent | null {
  const fields = new Map<string, string>();
  for (const line of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    if (separator <= 0) throw new Error("journal SSE contains a malformed field");
    const name = line.slice(0, separator);
    const value = line.slice(separator + 1).replace(/^ /, "");
    if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) throw new Error("journal SSE field is duplicated or unsupported");
    fields.set(name, value);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.journal_event") throw new Error("journal SSE event type is invalid");
  const event = parseJournalEvent(JSON.parse(fields.get("data") ?? ""));
  if (fields.get("id") !== String(event.sequence)) throw new Error("journal SSE ID does not match sequence");
  return event;
}

export async function streamJournalEvents(input: { after: number; bearerToken: string | null; signal: AbortSignal; onEvent: (event: JournalEvent) => void; onOpen?: () => void }): Promise<void> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/journal-events?after=${input.after}`, { method: "GET", headers: buildVttRequestHeaders({ bearerToken: input.bearerToken, accept: "text/event-stream" }), signal: input.signal });
  if (!response.ok) await responseJson(response);
  if (!response.body) throw new VttApiError("The journal event stream has no response body.", { status: response.status, code: "invalid_response" });
  if (!(response.headers.get("content-type") ?? "").toLowerCase().startsWith("text/event-stream")) throw new Error("The journal event stream returned an unsupported media type.");
  input.onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    if (buffer.length > 524_288) throw new Error("journal SSE block exceeds the supported size");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const event = parseJournalSseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (event) input.onEvent(event);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (buffer.trim()) throw new Error("journal SSE ended with an incomplete event");
}

export function buildJournalPutDocumentRequest(input: { sessionId: string; tableId: string; expectedRevision: number; document: JournalDocument; commandId?: string }): JournalRequest {
  return { schema_version: "vtt.journal_request.v1", session_id: input.sessionId, command: { schema_version: "vtt.journal_command.v1", command_type: "put_document", table_id: input.tableId, command_id: input.commandId ?? crypto.randomUUID(), expected_revision: input.expectedRevision, document: parseJournalDocument(input.document) } };
}

export function buildJournalDeleteDocumentRequest(input: { sessionId: string; tableId: string; expectedRevision: number; documentId: string; commandId?: string }): JournalRequest {
  return { schema_version: "vtt.journal_request.v1", session_id: input.sessionId, command: { schema_version: "vtt.journal_command.v1", command_type: "delete_document", table_id: input.tableId, command_id: input.commandId ?? crypto.randomUUID(), expected_revision: input.expectedRevision, document_id: text(input.documentId, "documentId") } };
}

export function buildJournalPutFolderRequest(input: { sessionId: string; tableId: string; expectedRevision: number; folder: JournalFolder; commandId?: string }): JournalRequest {
  return { schema_version: "vtt.journal_request.v1", session_id: input.sessionId, command: { schema_version: "vtt.journal_command.v1", command_type: "put_folder", table_id: input.tableId, command_id: input.commandId ?? crypto.randomUUID(), expected_revision: input.expectedRevision, folder: parseJournalFolder(input.folder) } };
}

export function buildJournalDeleteFolderRequest(input: { sessionId: string; tableId: string; expectedRevision: number; folderId: string; commandId?: string }): JournalRequest {
  return { schema_version: "vtt.journal_request.v1", session_id: input.sessionId, command: { schema_version: "vtt.journal_command.v1", command_type: "delete_folder", table_id: input.tableId, command_id: input.commandId ?? crypto.randomUUID(), expected_revision: input.expectedRevision, folder_id: text(input.folderId, "folderId") } };
}

export async function getJournalView(signal: AbortSignal, bearerToken: string | null, query = ""): Promise<JournalView> {
  const params = query ? `?query=${encodeURIComponent(query)}` : "";
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/journal${params}`, { method: "GET", headers: buildVttRequestHeaders({ bearerToken, accept: "application/json" }), signal });
  const payload = await responseJson(response);
  return parseJournalView(payload);
}

export async function postJournalRequest(request: JournalRequest, bearerToken: string | null): Promise<unknown> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/journal-commands`, { method: "POST", headers: buildVttRequestHeaders({ bearerToken, accept: "application/json", contentType: "application/json" }), body: JSON.stringify(request) });
  return responseJson(response);
}
