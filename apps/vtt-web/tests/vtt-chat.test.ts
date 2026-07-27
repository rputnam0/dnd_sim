import assert from "node:assert/strict";
import test from "node:test";

import {
  applyChatEvent,
  buildChatDeleteRequest,
  buildChatPostRequest,
  chatEventForRequest,
  chatEventsUrl,
  parseChatEvent,
  parseChatResponse,
  parseChatSseBlock,
  parseChatView,
  streamChatEvents,
} from "../app/vtt-chat";

const message = {
  schema_version: "vtt.chat_message.v1",
  message_id: "message-a",
  author_id: "local",
  audience: ["all"],
  text: "<b>literal</b>\n**still plain text**",
} as const;

const view = {
  schema_version: "vtt.chat_view.v1",
  session_id: "echo-vault-session",
  table_id: "echo-vault-session",
  revision: 1,
  messages: [message],
} as const;

const postedEvent = {
  schema_version: "vtt.chat_event.v1",
  table_id: "echo-vault-session",
  event_id: "echo-vault-session:chat:3",
  sequence: 3,
  revision: 3,
  command_id: "command-post-b",
  message_id: "message-b",
  event_type: "posted",
  message: {
    ...message,
    message_id: "message-b",
    text: "second message",
  },
} as const;

test("builds exact open-local post and delete requests without changing text", () => {
  assert.deepEqual(
    buildChatPostRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 4,
      text: "  keep edges  \n<b>literal</b>",
      commandId: "command-post",
      messageId: "message-post",
    }),
    {
      schema_version: "vtt.chat_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.chat_command.v1",
        command_type: "post",
        table_id: "echo-vault-session",
        command_id: "command-post",
        expected_revision: 4,
        message: {
          schema_version: "vtt.chat_message.v1",
          message_id: "message-post",
          author_id: "local",
          audience: ["all"],
          text: "  keep edges  \n<b>literal</b>",
        },
      },
    },
  );
  assert.deepEqual(
    buildChatDeleteRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 5,
      messageId: "message-post",
      commandId: "command-delete",
    }),
    {
      schema_version: "vtt.chat_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.chat_command.v1",
        command_type: "delete",
        table_id: "echo-vault-session",
        command_id: "command-delete",
        expected_revision: 5,
        message_id: "message-post",
      },
    },
  );
});

test("strictly parses ordered plain-text chat views", () => {
  assert.deepEqual(parseChatView(view), view);
  assert.deepEqual(
    parseChatView({
      ...view,
      messages: [message, { ...message, message_id: "message-b" }],
    }).messages.map((item) => item.message_id),
    ["message-a", "message-b"],
  );
  assert.throws(
    () => parseChatView({ ...view, timestamp: "2026-07-26" }),
    /unexpected field.*timestamp/i,
  );
  assert.throws(
    () => parseChatView({ ...view, messages: [message, message] }),
    /unique message/i,
  );
  assert.throws(
    () => parseChatView({ ...view, messages: [{ ...message, text: " \n\t " }] }),
    /non-whitespace/i,
  );
  assert.throws(
    () => parseChatView({ ...view, messages: [{ ...message, text: "bad\u0001" }] }),
    /control character/i,
  );
  assert.throws(
    () => parseChatView({ ...view, messages: [{ ...message, text: "bad\u007f" }] }),
    /control character/i,
  );
  assert.throws(
    () => parseChatView({ ...view, messages: [{ ...message, text: "bad\u0085" }] }),
    /control character/i,
  );
  assert.throws(
    () => parseChatView({ ...view, messages: [{ ...message, text: "x".repeat(2001) }] }),
    /2000/i,
  );
});

test("matches unbounded colon-free audience selector IDs", () => {
  const longSelector = `participant:${"p".repeat(500)}`;
  assert.deepEqual(
    parseChatView({
      ...view,
      messages: [{ ...message, audience: [longSelector] }],
    }).messages[0].audience,
    [longSelector],
  );
  assert.throws(
    () =>
      parseChatView({
        ...view,
        messages: [{ ...message, audience: ["participant:player:one"] }],
      }),
    /participant ID.*colon|participant ID.*':'/i,
  );
  assert.throws(
    () =>
      parseChatView({
        ...view,
        messages: [{ ...message, audience: ["actor:wizard:one"] }],
      }),
    /actor ID.*colon|actor ID.*':'/i,
  );
});

test("matches strict nullable mutation responses to their request", () => {
  const request = buildChatPostRequest({
    sessionId: "echo-vault-session",
    tableId: "echo-vault-session",
    expectedRevision: 2,
    text: "second message",
    commandId: "command-post-b",
    messageId: "message-b",
  });
  const response = parseChatResponse({
    schema_version: "vtt.chat_response.v1",
    session_id: "echo-vault-session",
    table_id: "echo-vault-session",
    command_id: "command-post-b",
    revision: 3,
    replayed: false,
    event: postedEvent,
  });
  assert.deepEqual(chatEventForRequest(request, response), postedEvent);
  assert.equal(
    chatEventForRequest(request, parseChatResponse({ ...response, event: null })),
    null,
  );
  assert.throws(
    () => chatEventForRequest(request, { ...response, command_id: "wrong" }),
    /does not match its request/i,
  );
  assert.throws(
    () =>
      parseChatResponse({
        ...response,
        event: { ...postedEvent, revision: 4, sequence: 4 },
      }),
    /event revision.*response revision/i,
  );
});

test("applies visible posted/deleted events in server order with valid gaps", () => {
  const afterPost = applyChatEvent(parseChatView(view), parseChatEvent(postedEvent));
  assert.equal(afterPost.revision, 3);
  assert.deepEqual(
    afterPost.messages.map((item) => item.message_id),
    ["message-a", "message-b"],
  );
  const deleted = parseChatEvent({
    schema_version: "vtt.chat_event.v1",
    table_id: "echo-vault-session",
    event_id: "echo-vault-session:chat:4",
    sequence: 4,
    revision: 4,
    command_id: "command-delete-a",
    message_id: "message-a",
    event_type: "deleted",
    author_id: "local",
    audience: ["all"],
  });
  assert.deepEqual(
    applyChatEvent(afterPost, deleted).messages.map((item) => item.message_id),
    ["message-b"],
  );
  assert.equal(applyChatEvent(afterPost, postedEvent), afterPost);
});

test("decodes and consumes reconnectable chunked chat SSE", async () => {
  const block = [
    "id: 3",
    "event: vtt.chat_event",
    `data: ${JSON.stringify(postedEvent)}`,
  ].join("\n");
  assert.deepEqual(parseChatSseBlock(block), postedEvent);
  assert.equal(parseChatSseBlock(": heartbeat"), null);
  assert.equal(
    chatEventsUrl(1),
    "http://127.0.0.1:8000/api/v1/chat-events?after=1",
  );
  assert.throws(() => chatEventsUrl(-1), /non-negative integer/i);

  const originalFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  const received: unknown[] = [];
  let opened = false;
  const eventBlock = `${block}\n\n`;
  globalThis.fetch = (async (input, init) => {
    assert.equal(
      String(input),
      "http://127.0.0.1:8000/api/v1/chat-events?after=1",
    );
    assert.deepEqual(init?.headers, { accept: "text/event-stream" });
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const chunk of [": heartbeat\n\ni", eventBlock.slice(1, 29), eventBlock.slice(29)]) {
            controller.enqueue(encoder.encode(chunk));
          }
          controller.close();
        },
      }),
      { status: 200 },
    );
  }) as typeof fetch;
  try {
    const cursor = await streamChatEvents({
      after: 1,
      signal: new AbortController().signal,
      onOpen: () => {
        opened = true;
      },
      onEvent: (event) => received.push(event),
    });
    assert.equal(opened, true);
    assert.equal(cursor, 3);
    assert.deepEqual(received, [postedEvent]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
