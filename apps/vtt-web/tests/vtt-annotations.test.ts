import assert from "node:assert/strict";
import test from "node:test";

import {
  annotationEventForRequest,
  applyAnnotationEvent,
  buildAnnotationDeleteRequest,
  buildAnnotationPutRequest,
  buildPingPutRequest,
  parseAnnotationEvent,
  parseAnnotationsView,
  parseAnnotationSseBlock,
  parseAnnotationResponse,
  streamAnnotationEvents,
  vttAnnotationEventsUrl,
} from "../app/vtt-annotations";

const ping = {
  schema_version: "vtt.annotation.v1",
  annotation_id: "ping-a",
  scene_id: "echo-vault",
  author_id: "browser-player",
  audience: ["all"],
  annotation_type: "ping",
  position: { x_ft: 17.5, y_ft: 12.5, z_ft: 0 },
  duration_ms: 1500,
} as const;

const view = {
  schema_version: "vtt.annotations_view.v1",
  session_id: "echo-vault-session",
  table_id: "echo-vault-table",
  scene_id: "echo-vault",
  revision: 1,
  annotations: [ping],
} as const;

const putEvent = {
  schema_version: "vtt.annotation_event.v1",
  table_id: "echo-vault-table",
  event_id: "echo-vault-table:annotation:2",
  sequence: 2,
  revision: 2,
  command_id: "command-b",
  annotation_id: "ping-b",
  event_type: "put",
  annotation: {
    ...ping,
    annotation_id: "ping-b",
    position: { x_ft: 22.5, y_ft: 17.5, z_ft: 0 },
  },
} as const;

const circle = {
  schema_version: "vtt.annotation.v1",
  annotation_id: "circle-a",
  scene_id: "echo-vault",
  author_id: "local",
  audience: ["all"],
  annotation_type: "circle_template",
  center: { x_ft: 17.5, y_ft: 12.5, z_ft: 0 },
  radius_ft: 10,
} as const;

test("builds exact generic annotation put and delete requests", () => {
  assert.deepEqual(
    buildAnnotationPutRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-table",
      expectedRevision: 4,
      commandId: "command-circle",
      annotation: circle,
    }),
    {
      schema_version: "vtt.annotation_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.annotation_command.v1",
        table_id: "echo-vault-table",
        command_id: "command-circle",
        expected_revision: 4,
        command_type: "put",
        annotation: circle,
      },
    },
  );
  assert.deepEqual(
    buildAnnotationDeleteRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-table",
      expectedRevision: 5,
      commandId: "command-delete-circle",
      annotationId: "circle-a",
    }),
    {
      schema_version: "vtt.annotation_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.annotation_command.v1",
        table_id: "echo-vault-table",
        command_id: "command-delete-circle",
        expected_revision: 5,
        command_type: "delete",
        annotation_id: "circle-a",
      },
    },
  );
});

test("matches mutation receipts to the exact originating request", () => {
  const request = buildAnnotationDeleteRequest({
    sessionId: "echo-vault-session",
    tableId: "echo-vault-table",
    expectedRevision: 2,
    commandId: "command-delete",
    annotationId: "ping-a",
  });
  const response = parseAnnotationResponse({
    schema_version: "vtt.annotation_response.v1",
    session_id: "echo-vault-session",
    replayed: false,
    receipt: {
      schema_version: "vtt.annotation_receipt.v1",
      table_id: "echo-vault-table",
      command_id: "command-delete",
      revision: 3,
      event: {
        schema_version: "vtt.annotation_event.v1",
        table_id: "echo-vault-table",
        event_id: "echo-vault-table:annotation:3",
        sequence: 3,
        revision: 3,
        command_id: "command-delete",
        annotation_id: "ping-a",
        event_type: "delete",
        scene_id: "echo-vault",
        audience: ["all"],
      },
    },
  });
  assert.equal(annotationEventForRequest(request, response).event_type, "delete");
  assert.throws(
    () =>
      annotationEventForRequest(request, {
        ...response,
        session_id: "another-session",
      }),
    /does not match its request/i,
  );
});

test("builds an exact public ping put request", () => {
  assert.deepEqual(
    buildPingPutRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-table",
      sceneId: "echo-vault",
      authorId: "browser-player",
      expectedRevision: 3,
      position: [17.5, 12.5, 0],
      commandId: "command-a",
      annotationId: "ping-a",
    }),
    {
      schema_version: "vtt.annotation_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.annotation_command.v1",
        table_id: "echo-vault-table",
        command_id: "command-a",
        expected_revision: 3,
        command_type: "put",
        annotation: ping,
      },
    },
  );
});

test("strictly parses a deterministic scene-bound annotation view", () => {
  assert.deepEqual(parseAnnotationsView(view), view);

  const unicodeSorted = {
    ...view,
    annotations: [
      { ...ping, annotation_id: "\ue000" },
      { ...ping, annotation_id: "\u{10000}" },
    ],
  };
  assert.deepEqual(parseAnnotationsView(unicodeSorted), unicodeSorted);

  assert.throws(
    () => parseAnnotationsView({ ...view, canonical_store: {} }),
    /unexpected field.*canonical_store/i,
  );
  assert.throws(
    () =>
      parseAnnotationsView({
        ...view,
        annotations: [
          { ...ping, annotation_id: "ping-b" },
          { ...ping, annotation_id: "ping-a" },
        ],
      }),
    /annotations.*sorted/i,
  );
  assert.throws(
    () =>
      parseAnnotationsView({
        ...view,
        annotations: [ping, ping],
      }),
    /annotations.*unique/i,
  );
  assert.throws(
    () =>
      parseAnnotationsView({
        ...view,
        annotations: [{ ...ping, scene_id: "other-scene" }],
      }),
    /annotation.*scene_id.*view/i,
  );
  assert.throws(
    () =>
      parseAnnotationsView({
        ...view,
        annotations: [
          { ...ping, audience: ["all", "participant:player-1"] },
        ],
      }),
    /audience.*all/i,
  );
  assert.throws(
    () =>
      parseAnnotationsView({
        ...view,
        annotations: [{ ...ping, duration_ms: 249 }],
      }),
    /duration_ms/i,
  );
});

test("parses receipts and applies put/delete events without duplicates", () => {
  const parsedPut = parseAnnotationEvent(putEvent);
  const afterPut = applyAnnotationEvent(parseAnnotationsView(view), parsedPut);
  assert.equal(afterPut.revision, 2);
  assert.deepEqual(
    afterPut.annotations.map((annotation) => annotation.annotation_id),
    ["ping-a", "ping-b"],
  );

  const response = parseAnnotationResponse({
    schema_version: "vtt.annotation_response.v1",
    session_id: "echo-vault-session",
    replayed: false,
    receipt: {
      schema_version: "vtt.annotation_receipt.v1",
      table_id: "echo-vault-table",
      command_id: "command-b",
      revision: 2,
      event: putEvent,
    },
  });
  assert.equal(response.receipt.event.event_type, "put");

  const deleteEvent = parseAnnotationEvent({
    schema_version: "vtt.annotation_event.v1",
    table_id: "echo-vault-table",
    event_id: "echo-vault-table:annotation:3",
    sequence: 3,
    revision: 3,
    command_id: "command-delete",
    annotation_id: "ping-a",
    event_type: "delete",
    scene_id: "echo-vault",
    audience: ["all"],
  });
  assert.deepEqual(
    applyAnnotationEvent(afterPut, deleteEvent).annotations.map(
      (annotation) => annotation.annotation_id,
    ),
    ["ping-b"],
  );

  assert.throws(
    () =>
      parseAnnotationResponse({
        ...response,
        receipt: { ...response.receipt, command_id: "wrong-command" },
      }),
    /command_id.*match/i,
  );
  assert.throws(
    () => parseAnnotationEvent({ ...putEvent, sequence: 3 }),
    /sequence.*match revision/i,
  );
});

test("strictly decodes reconnectable annotation SSE blocks", () => {
  const block = [
    "id: 2",
    "event: vtt.annotation_event",
    `data: ${JSON.stringify(putEvent)}`,
  ].join("\n");

  assert.deepEqual(parseAnnotationSseBlock(block), putEvent);
  assert.equal(parseAnnotationSseBlock(": heartbeat"), null);
  assert.throws(
    () => parseAnnotationSseBlock(block.replace("id: 2", "id: 1")),
    /id.*sequence/i,
  );
  assert.equal(
    vttAnnotationEventsUrl(17),
    "http://127.0.0.1:8000/api/v1/annotation-events?after=17",
  );
  assert.throws(() => vttAnnotationEventsUrl(-1), /non-negative integer/i);
  assert.throws(
    () => vttAnnotationEventsUrl(Number.MAX_SAFE_INTEGER + 1),
    /safe range/i,
  );
});

test("streams chunked annotation events and resumes after the supplied cursor", async () => {
  const originalFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  const received: unknown[] = [];
  let opened = false;
  const eventBlock = [
    "id: 2",
    "event: vtt.annotation_event",
    `data: ${JSON.stringify(putEvent)}`,
    "",
    "",
  ].join("\n");

  globalThis.fetch = (async (input, init) => {
    assert.equal(
      String(input),
      "http://127.0.0.1:8000/api/v1/annotation-events?after=1",
    );
    assert.equal(init?.method, "GET");
    assert.deepEqual(init?.headers, {
      accept: "text/event-stream",
      authorization: "Bearer table-token-1234567890",
    });
    const chunks = [": heartbeat\n\ni", eventBlock.slice(1, 37), eventBlock.slice(37)];
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
          controller.close();
        },
      }),
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
  }) as typeof fetch;

  try {
    const cursor = await streamAnnotationEvents({
      after: 1,
      bearerToken: "table-token-1234567890",
      signal: new AbortController().signal,
      onOpen: () => {
        opened = true;
      },
      onEvent: (event) => received.push(event),
    });
    assert.equal(opened, true);
    assert.equal(cursor, 2);
    assert.deepEqual(received, [putEvent]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
