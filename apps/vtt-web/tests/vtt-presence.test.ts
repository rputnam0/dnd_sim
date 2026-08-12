import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPresenceHeartbeatRequest,
  assertPresenceViewMatchesTable,
  parsePresenceHeartbeatResponse,
  parsePresenceSseBlock,
  parsePresenceView,
  presenceEventsUrl,
  presenceSignalForRequest,
  streamPresenceEvents,
} from "../app/vtt-presence";

const records = [
  {
    schema_version: "vtt.presence_record.v1",
    participant_id: "gm",
    display_name: "Game Master",
    role: "gm",
    status: "online",
  },
  {
    schema_version: "vtt.presence_record.v1",
    participant_id: "player",
    display_name: "Vela",
    role: "player",
    status: "away",
  },
  {
    schema_version: "vtt.presence_record.v1",
    participant_id: "spectator",
    display_name: "Observer",
    role: "spectator",
    status: "offline",
  },
] as const;

const view = {
  schema_version: "vtt.presence_view.v1",
  table_id: "echo-vault-session",
  revision: 4,
  evaluated_at_ms: 1_800_000_000_000,
  away_after_ms: 30_000,
  offline_after_ms: 90_000,
  records,
} as const;

const signal = {
  schema_version: "vtt.presence_change_signal.v1",
  sequence: 5,
  revision: 5,
  participant_id: "player",
} as const;

test("builds exact server-timed heartbeat requests", () => {
  assert.deepEqual(
    buildPresenceHeartbeatRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 4,
      participantId: "player",
      clientId: "browser-a",
      commandId: "heartbeat-a",
    }),
    {
      schema_version: "vtt.presence_heartbeat_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.presence_command.v1",
        command_type: "heartbeat",
        table_id: "echo-vault-session",
        command_id: "heartbeat-a",
        expected_revision: 4,
        participant_id: "player",
        client_id: "browser-a",
      },
    },
  );
});

test("strictly parses the safe ordered presence directory", () => {
  assert.deepEqual(parsePresenceView(view), view);
  assert.throws(
    () => parsePresenceView({ ...view, client_id: "leak" }),
    /unexpected field.*client_id/i,
  );
  assert.throws(
    () =>
      parsePresenceView({
        ...view,
        records: [{ ...records[0], observed_at_ms: 42 }],
      }),
    /unexpected field.*observed_at_ms/i,
  );
  assert.throws(
    () => parsePresenceView({ ...view, records: [records[1], records[0]] }),
    /sorted/i,
  );
  assert.throws(
    () => parsePresenceView({ ...view, away_after_ms: 90_000 }),
    /less than offline/i,
  );
});

test("accepts Python code-point record ordering across the BMP boundary", () => {
  const privateUse = { ...records[0], participant_id: "\ue000" };
  const supplementary = { ...records[1], participant_id: "\u{10000}" };
  assert.deepEqual(
    parsePresenceView({ ...view, records: [privateUse, supplementary] }).records.map(
      (record) => record.participant_id,
    ),
    ["\ue000", "\u{10000}"],
  );
});

test("binds the presence directory to the authenticated table roster", () => {
  const table = {
    schema_version: "vtt.table_view.v1",
    access_mode: "protected",
    table_id: "echo-vault-session",
    current_participant: {
      schema_version: "vtt.participant.v1",
      participant_id: "player",
      display_name: "Vela",
      role: "player",
      owned_actor_ids: ["vela_quill"],
    },
    participants: records.map((record) => ({
      schema_version: "vtt.participant.v1" as const,
      participant_id: record.participant_id,
      display_name: record.display_name,
      role: record.role,
      owned_actor_ids: [],
    })),
  } as const;
  assert.doesNotThrow(() => assertPresenceViewMatchesTable(parsePresenceView(view), table));
  assert.throws(
    () =>
      assertPresenceViewMatchesTable(
        parsePresenceView({
          ...view,
          records: [{ ...records[0], display_name: "Impostor" }, ...records.slice(1)],
        }),
        table,
      ),
    /directory.*match/i,
  );
});

test("matches sanitized heartbeat responses to their exact request", () => {
  const request = buildPresenceHeartbeatRequest({
    sessionId: "echo-vault-session",
    tableId: "echo-vault-session",
    expectedRevision: 4,
    participantId: "player",
    clientId: "browser-a",
    commandId: "heartbeat-a",
  });
  const response = parsePresenceHeartbeatResponse({
    schema_version: "vtt.presence_heartbeat_response.v1",
    session_id: "echo-vault-session",
    table_id: "echo-vault-session",
    command_id: "heartbeat-a",
    revision: 5,
    replayed: false,
    signal,
  });
  assert.deepEqual(presenceSignalForRequest(request, response), signal);
  assert.throws(
    () =>
      parsePresenceHeartbeatResponse({
        ...response,
        client_id: "browser-a",
      }),
    /unexpected field.*client_id/i,
  );
  assert.throws(
    () =>
      parsePresenceHeartbeatResponse({
        ...response,
        signal: { ...signal, observed_at_ms: 1_800_000_000_000 },
      }),
    /unexpected field.*observed_at_ms/i,
  );
  assert.throws(
    () => presenceSignalForRequest(request, { ...response, command_id: "wrong" }),
    /does not match its request/i,
  );
});

test("decodes authenticated reconnectable sanitized presence SSE", async () => {
  const block = [
    "id: 5",
    "event: vtt.presence_changed",
    `data: ${JSON.stringify(signal)}`,
  ].join("\n");
  assert.deepEqual(parsePresenceSseBlock(block), signal);
  assert.equal(parsePresenceSseBlock(": heartbeat"), null);
  assert.equal(
    presenceEventsUrl(4),
    "http://127.0.0.1:8000/api/v1/presence-events?after=4",
  );
  assert.throws(() => presenceEventsUrl(-1), /non-negative integer/i);

  const originalFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  const received: unknown[] = [];
  let opened = false;
  const eventBlock = `${block}\n\n`;
  globalThis.fetch = (async (input, init) => {
    assert.equal(
      String(input),
      "http://127.0.0.1:8000/api/v1/presence-events?after=4",
    );
    assert.deepEqual(init?.headers, {
      accept: "text/event-stream",
      authorization: "Bearer table-token-1234567890",
    });
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const chunk of [": heartbeat\n\ni", eventBlock.slice(1, 27), eventBlock.slice(27)]) {
            controller.enqueue(encoder.encode(chunk));
          }
          controller.close();
        },
      }),
      { status: 200 },
    );
  }) as typeof fetch;
  try {
    const cursor = await streamPresenceEvents({
      after: 4,
      bearerToken: "table-token-1234567890",
      signal: new AbortController().signal,
      onOpen: () => {
        opened = true;
      },
      onSignal: (nextSignal) => received.push(nextSignal),
    });
    assert.equal(opened, true);
    assert.equal(cursor, 5);
    assert.deepEqual(received, [signal]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
