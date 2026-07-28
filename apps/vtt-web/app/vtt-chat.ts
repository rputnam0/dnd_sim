import {
  VTT_API_BASE_URL,
  VttApiError,
  type JsonValue,
} from "./vtt-client";
import { buildVttRequestHeaders } from "./vtt-transport";

export const MAX_CHAT_TEXT_LENGTH = 2_000;

export interface ChatMessage {
  schema_version: "vtt.chat_message.v1";
  message_id: string;
  author_id: string;
  audience: string[];
  text: string;
}

export interface ChatView {
  schema_version: "vtt.chat_view.v1";
  session_id: string;
  table_id: string;
  revision: number;
  messages: ChatMessage[];
}

export interface ChatPostCommand {
  schema_version: "vtt.chat_command.v1";
  command_type: "post";
  table_id: string;
  command_id: string;
  expected_revision: number;
  message: ChatMessage;
}

export interface ChatDeleteCommand {
  schema_version: "vtt.chat_command.v1";
  command_type: "delete";
  table_id: string;
  command_id: string;
  expected_revision: number;
  message_id: string;
}

export type ChatMutationCommand = ChatPostCommand | ChatDeleteCommand;

export interface ChatPostRequest {
  schema_version: "vtt.chat_request.v1";
  session_id: string;
  command: ChatPostCommand;
}

export interface ChatDeleteRequest {
  schema_version: "vtt.chat_request.v1";
  session_id: string;
  command: ChatDeleteCommand;
}

export type ChatMutationRequest = ChatPostRequest | ChatDeleteRequest;

interface ChatEventBase {
  schema_version: "vtt.chat_event.v1";
  table_id: string;
  event_id: string;
  sequence: number;
  revision: number;
  command_id: string;
  message_id: string;
}

export interface ChatPostedEvent extends ChatEventBase {
  event_type: "posted";
  message: ChatMessage;
}

export interface ChatDeletedEvent extends ChatEventBase {
  event_type: "deleted";
  author_id: string;
  audience: string[];
}

export type ChatEvent = ChatPostedEvent | ChatDeletedEvent;

export interface ChatResponse {
  schema_version: "vtt.chat_response.v1";
  session_id: string;
  table_id: string;
  command_id: string;
  revision: number;
  replayed: boolean;
  event: ChatEvent | null;
}

type ObjectValue = Record<string, unknown>;

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
    if (!(key in result)) throw new Error(`${path} is missing field "${key}"`);
  }
  return result;
}

function canonicalText(value: unknown, path: string, maximum = 128): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value ||
    Array.from(value).length > maximum
  ) {
    throw new Error(`${path} must be canonical non-empty text`);
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

function booleanValue(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean`);
  return value;
}

function integerValue(value: unknown, path: string, minimum = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  ) {
    throw new Error(`${path} must be a safe integer >= ${minimum}`);
  }
  return value;
}

function compareUnicodeCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) =>
    character.codePointAt(0) as number,
  );
  const rightPoints = Array.from(right, (character) =>
    character.codePointAt(0) as number,
  );
  const sharedLength = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < sharedLength; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] - rightPoints[index];
    }
  }
  return leftPoints.length - rightPoints.length;
}

function audienceSelectorText(value: unknown, path: string): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.trim() !== value
  ) {
    throw new Error(`${path} must be canonical non-empty text`);
  }
  return value;
}

function selectorId(selector: string, prefix: string, path: string): void {
  const identifier = audienceSelectorText(selector.slice(prefix.length), path);
  if (identifier.includes(":")) {
    throw new Error(`${path} must not contain ':'`);
  }
}

function parseAudience(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${path} must be a non-empty ordered list`);
  }
  const audience = value.map((raw, index) =>
    audienceSelectorText(raw, `${path}[${index}]`),
  );
  if (new Set(audience).size !== audience.length) {
    throw new Error(`${path} must contain unique selectors`);
  }
  if (audience.includes("all")) {
    if (audience.length !== 1 || audience[0] !== "all") {
      throw new Error(`${path} selector all must be used alone`);
    }
    return audience;
  }
  if (
    audience.some(
      (selector, index) =>
        index > 0 &&
        compareUnicodeCodePoints(selector, audience[index - 1]) < 0,
    )
  ) {
    throw new Error(`${path} selectors must be sorted`);
  }
  for (const selector of audience) {
    if (["role:gm", "role:player", "role:spectator"].includes(selector)) {
      continue;
    }
    if (selector.startsWith("participant:")) {
      selectorId(selector, "participant:", `${path} participant ID`);
      continue;
    }
    if (selector.startsWith("actor:")) {
      selectorId(selector, "actor:", `${path} actor ID`);
      continue;
    }
    throw new Error(`${path} contains an unsupported selector`);
  }
  return audience;
}

function chatText(value: unknown, path: string): string {
  if (typeof value !== "string") throw new Error(`${path} must be text`);
  if (!value.trim()) {
    throw new Error(`${path} must contain a non-whitespace character`);
  }
  if (Array.from(value).length > MAX_CHAT_TEXT_LENGTH) {
    throw new Error(`${path} must be at most ${MAX_CHAT_TEXT_LENGTH} characters`);
  }
  if (
    Array.from(value).some(
      (character) =>
        /\p{Cc}/u.test(character) && character !== "\n" && character !== "\t",
    )
  ) {
    throw new Error(`${path} contains an unsupported control character`);
  }
  return value;
}

export function parseChatMessage(value: unknown, path = "chat_message"): ChatMessage {
  const data = exactObject(
    value,
    ["schema_version", "message_id", "author_id", "audience", "text"],
    path,
  );
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.chat_message.v1"],
      `${path}.schema_version`,
    ),
    message_id: canonicalText(data.message_id, `${path}.message_id`),
    author_id: canonicalText(data.author_id, `${path}.author_id`),
    audience: parseAudience(data.audience, `${path}.audience`),
    text: chatText(data.text, `${path}.text`),
  };
}

export function parseChatView(value: unknown): ChatView {
  const data = exactObject(
    value,
    ["schema_version", "session_id", "table_id", "revision", "messages"],
    "chat_view",
  );
  if (!Array.isArray(data.messages)) {
    throw new Error("chat_view.messages must be an array");
  }
  const messages = data.messages.map((item, index) =>
    parseChatMessage(item, `chat_view.messages[${index}]`),
  );
  const messageIds = messages.map((item) => item.message_id);
  if (new Set(messageIds).size !== messageIds.length) {
    throw new Error("chat_view.messages must contain unique message IDs");
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.chat_view.v1"],
      "chat_view.schema_version",
    ),
    session_id: canonicalText(data.session_id, "chat_view.session_id"),
    table_id: canonicalText(data.table_id, "chat_view.table_id"),
    revision: integerValue(data.revision, "chat_view.revision"),
    messages,
  };
}

export function parseChatEvent(value: unknown): ChatEvent {
  const raw = objectValue(value, "chat_event");
  const eventType = literalValue(
    raw.event_type,
    ["posted", "deleted"],
    "chat_event.event_type",
  );
  const commonKeys = [
    "schema_version",
    "table_id",
    "event_id",
    "sequence",
    "revision",
    "command_id",
    "message_id",
    "event_type",
  ];
  const data = exactObject(
    raw,
    eventType === "posted"
      ? [...commonKeys, "message"]
      : [...commonKeys, "author_id", "audience"],
    "chat_event",
  );
  const common = {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.chat_event.v1"],
      "chat_event.schema_version",
    ),
    table_id: canonicalText(data.table_id, "chat_event.table_id"),
    event_id: canonicalText(data.event_id, "chat_event.event_id", 512),
    sequence: integerValue(data.sequence, "chat_event.sequence", 1),
    revision: integerValue(data.revision, "chat_event.revision", 1),
    command_id: canonicalText(data.command_id, "chat_event.command_id"),
    message_id: canonicalText(data.message_id, "chat_event.message_id"),
  };
  if (common.sequence !== common.revision) {
    throw new Error("chat_event sequence must match revision");
  }
  if (eventType === "posted") {
    const message = parseChatMessage(data.message, "chat_event.message");
    if (message.message_id !== common.message_id) {
      throw new Error("chat_event message ID must match its message");
    }
    return { ...common, event_type: "posted", message };
  }
  return {
    ...common,
    event_type: "deleted",
    author_id: canonicalText(data.author_id, "chat_event.author_id"),
    audience: parseAudience(data.audience, "chat_event.audience"),
  };
}

export function parseChatResponse(value: unknown): ChatResponse {
  const data = exactObject(
    value,
    [
      "schema_version",
      "session_id",
      "table_id",
      "command_id",
      "revision",
      "replayed",
      "event",
    ],
    "chat_response",
  );
  const tableId = canonicalText(data.table_id, "chat_response.table_id");
  const commandId = canonicalText(data.command_id, "chat_response.command_id");
  const revision = integerValue(data.revision, "chat_response.revision", 1);
  const event = data.event === null ? null : parseChatEvent(data.event);
  if (event !== null) {
    if (event.table_id !== tableId) {
      throw new Error("chat response event table_id must match response table_id");
    }
    if (event.command_id !== commandId) {
      throw new Error("chat response event command_id must match response command_id");
    }
    if (event.revision !== revision) {
      throw new Error("chat response event revision must match response revision");
    }
  }
  return {
    schema_version: literalValue(
      data.schema_version,
      ["vtt.chat_response.v1"],
      "chat_response.schema_version",
    ),
    session_id: canonicalText(data.session_id, "chat_response.session_id"),
    table_id: tableId,
    command_id: commandId,
    revision,
    replayed: booleanValue(data.replayed, "chat_response.replayed"),
    event,
  };
}

export function buildChatPostRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  text: string;
  authorId?: string;
  audience?: string[];
  commandId?: string;
  messageId?: string;
}): ChatPostRequest {
  return {
    schema_version: "vtt.chat_request.v1",
    session_id: canonicalText(input.sessionId, "sessionId"),
    command: {
      schema_version: "vtt.chat_command.v1",
      command_type: "post",
      table_id: canonicalText(input.tableId, "tableId"),
      command_id: canonicalText(
        input.commandId ?? crypto.randomUUID(),
        "commandId",
      ),
      expected_revision: integerValue(
        input.expectedRevision,
        "expectedRevision",
      ),
      message: parseChatMessage({
        schema_version: "vtt.chat_message.v1",
        message_id: canonicalText(
          input.messageId ?? crypto.randomUUID(),
          "messageId",
        ),
        author_id: canonicalText(input.authorId ?? "local", "authorId"),
        audience: parseAudience(input.audience ?? ["all"], "audience"),
        text: input.text,
      }),
    },
  };
}

export function buildChatDeleteRequest(input: {
  sessionId: string;
  tableId: string;
  expectedRevision: number;
  messageId: string;
  commandId?: string;
}): ChatDeleteRequest {
  return {
    schema_version: "vtt.chat_request.v1",
    session_id: canonicalText(input.sessionId, "sessionId"),
    command: {
      schema_version: "vtt.chat_command.v1",
      command_type: "delete",
      table_id: canonicalText(input.tableId, "tableId"),
      command_id: canonicalText(
        input.commandId ?? crypto.randomUUID(),
        "commandId",
      ),
      expected_revision: integerValue(
        input.expectedRevision,
        "expectedRevision",
      ),
      message_id: canonicalText(input.messageId, "messageId"),
    },
  };
}

export function chatEventForRequest(
  request: ChatMutationRequest,
  response: ChatResponse,
): ChatEvent | null {
  if (
    response.session_id !== request.session_id ||
    response.table_id !== request.command.table_id ||
    response.command_id !== request.command.command_id
  ) {
    throw new Error("The chat response does not match its request.");
  }
  if (response.event === null) return null;
  const expectedType =
    request.command.command_type === "post" ? "posted" : "deleted";
  const expectedMessageId =
    request.command.command_type === "post"
      ? request.command.message.message_id
      : request.command.message_id;
  if (
    response.event.event_type !== expectedType ||
    response.event.message_id !== expectedMessageId
  ) {
    throw new Error("The chat response does not match its request.");
  }
  return response.event;
}

function sameAudience(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((selector, index) => selector === right[index])
  );
}

export function applyChatEvent(view: ChatView, event: ChatEvent): ChatView {
  if (event.table_id !== view.table_id) {
    throw new Error("Chat event table_id does not match the hydrated view");
  }
  if (event.revision <= view.revision) return view;
  if (event.event_type === "posted") {
    if (view.messages.some((item) => item.message_id === event.message_id)) {
      throw new Error("Chat event reposts an existing message ID");
    }
    return {
      ...view,
      revision: event.revision,
      messages: [...view.messages, event.message],
    };
  }
  const deleted = view.messages.find(
    (item) => item.message_id === event.message_id,
  );
  if (!deleted) throw new Error("Chat event deletes a missing message");
  if (
    deleted.author_id !== event.author_id ||
    !sameAudience(deleted.audience, event.audience)
  ) {
    throw new Error("Chat delete tombstone does not match its message");
  }
  return {
    ...view,
    revision: event.revision,
    messages: view.messages.filter(
      (item) => item.message_id !== event.message_id,
    ),
  };
}

function jsonObject(value: unknown, path: string): Record<string, JsonValue> {
  return objectValue(value, path) as Record<string, JsonValue>;
}

async function chatResponseJson(response: Response): Promise<unknown> {
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new VttApiError("The chat service returned unreadable data.", {
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
    literalValue(error.schema_version, ["vtt.error.v1"], "error.schema_version");
    throw new VttApiError(canonicalText(error.message, "error.message", 10_000), {
      code: canonicalText(error.code, "error.code"),
      status: response.status,
      details: jsonObject(error.details, "error.details"),
    });
  } catch (error) {
    if (error instanceof VttApiError) throw error;
    throw new VttApiError("The chat service rejected the request.", {
      code: "http_error",
      status: response.status,
    });
  }
}

export async function getChatView(
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<ChatView> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/chat`, {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
    }),
    signal,
  });
  return parseChatView(await chatResponseJson(response));
}

export async function postChatRequest(
  request: ChatMutationRequest,
  signal?: AbortSignal,
  bearerToken?: string | null,
): Promise<ChatResponse> {
  const response = await fetch(`${VTT_API_BASE_URL}/api/v1/chat-commands`, {
    method: "POST",
    headers: buildVttRequestHeaders({
      accept: "application/json",
      bearerToken,
      contentType: "application/json",
    }),
    body: JSON.stringify(request),
    signal,
  });
  return parseChatResponse(await chatResponseJson(response));
}

export function chatEventsUrl(after: number): string {
  if (!Number.isSafeInteger(after) || after < 0) {
    throw new Error(
      "Chat event cursor must be a non-negative integer within the safe range",
    );
  }
  return `${VTT_API_BASE_URL}/api/v1/chat-events?after=${after}`;
}

export function parseChatSseBlock(block: string): ChatEvent | null {
  if (typeof block !== "string") throw new Error("Chat SSE block must be text");
  const fields = new Map<string, string>();
  for (const rawLine of block.replaceAll("\r\n", "\n").split("\n")) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const separator = rawLine.indexOf(":");
    if (separator <= 0) throw new Error("Chat SSE contains a malformed field");
    const name = rawLine.slice(0, separator);
    const fieldValue = rawLine.slice(separator + 1).replace(/^ /, "");
    if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) {
      throw new Error("Chat SSE contains duplicate or unsupported fields");
    }
    fields.set(name, fieldValue);
  }
  if (fields.size === 0) return null;
  if (fields.get("event") !== "vtt.chat_event") {
    throw new Error("Chat SSE event type is invalid");
  }
  const idText = fields.get("id");
  const dataText = fields.get("data");
  if (!idText || !dataText || !/^\d+$/.test(idText)) {
    throw new Error("Chat SSE id must be a canonical integer");
  }
  const id = Number(idText);
  if (!Number.isSafeInteger(id) || String(id) !== idText) {
    throw new Error("Chat SSE id must be a canonical safe integer");
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(dataText);
  } catch {
    throw new Error("Chat SSE data must be valid JSON");
  }
  const event = parseChatEvent(decoded);
  if (id !== event.sequence) {
    throw new Error("Chat SSE id must match the event sequence");
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

export async function streamChatEvents(input: {
  after: number;
  bearerToken?: string | null;
  signal: AbortSignal;
  onEvent: (event: ChatEvent) => void;
  onOpen?: () => void;
}): Promise<number> {
  let cursor = integerValue(input.after, "after");
  const response = await fetch(chatEventsUrl(cursor), {
    method: "GET",
    headers: buildVttRequestHeaders({
      accept: "text/event-stream",
      bearerToken: input.bearerToken,
    }),
    signal: input.signal,
  });
  if (!response.ok) await chatResponseJson(response);
  if (!response.body) {
    throw new VttApiError("The chat event stream has no response body.", {
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
      const event = parseChatSseBlock(buffer.slice(0, boundary.index));
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
    throw new Error("Chat SSE ended with an incomplete event");
  }
  return cursor;
}
