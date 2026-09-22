import assert from "node:assert/strict";
import test from "node:test";

import {
  annotationEventForRequest,
  applyAnnotationEvent,
  buildAnnotationDeleteRequest,
  buildAnnotationPutRequest,
  buildPingPutRequest,
  annotationViewMatchesIdentity,
  isDrawingAnnotation,
  isLockedDrawingAnnotation,
  parseVttAnnotation,
  parseAnnotationEvent,
  parseAnnotationsView,
  parseAnnotationSseBlock,
  parseAnnotationResponse,
  streamAnnotationEvents,
  vttAnnotationEventsUrl,
  type ArrowDrawingAnnotation,
  type DrawingAnnotation,
  type FreehandDrawingAnnotation,
  type PingAnnotation,
  type ShapeDrawingAnnotation,
  type TextDrawingAnnotation,
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
} satisfies PingAnnotation;

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

const drawingStyle = {
  stroke_color: "#5eead4",
  fill_color: "#123456",
  opacity: 0.75,
  stroke_width_ft: 1.5,
  line_style: "dashed",
} as const;

const drawingBase = {
  schema_version: "vtt.annotation.v1",
  scene_id: "echo-vault",
  author_id: "browser-player",
  audience: ["all"],
} satisfies Pick<DrawingAnnotation, "schema_version" | "scene_id" | "author_id" | "audience">;

const drawings = [
  {
    ...drawingBase,
    annotation_id: "draw-arrow",
    annotation_type: "arrow_drawing",
    layer: "over_tokens",
    locked: false,
    style: drawingStyle,
    start: { x_ft: 5, y_ft: 10, z_ft: 0 },
    end: { x_ft: 15, y_ft: 20, z_ft: 0 },
    head_size_ft: 2,
  },
  {
    ...drawingBase,
    annotation_id: "draw-freehand",
    annotation_type: "freehand_drawing",
    layer: "under_tokens",
    locked: true,
    style: drawingStyle,
    points: [
      { x_ft: 5, y_ft: 10, z_ft: 0 },
      { x_ft: 10, y_ft: 15, z_ft: 0 },
      { x_ft: 15, y_ft: 10, z_ft: 0 },
    ],
  },
  {
    ...drawingBase,
    annotation_id: "draw-shape",
    annotation_type: "shape_drawing",
    layer: "under_tokens",
    locked: false,
    style: drawingStyle,
    shape: "ellipse",
    corner_a: { x_ft: 5, y_ft: 10, z_ft: 0 },
    corner_b: { x_ft: 15, y_ft: 20, z_ft: 0 },
  },
  {
    ...drawingBase,
    annotation_id: "draw-text",
    annotation_type: "text_drawing",
    layer: "over_tokens",
    locked: true,
    style: drawingStyle,
    anchor: { x_ft: 5, y_ft: 10, z_ft: 0 },
    text: "Hold <script>alert(1)</script>\nNorth",
    font_size_ft: 3,
    background_color: "#112233",
  },
] satisfies [
  ArrowDrawingAnnotation,
  FreehandDrawingAnnotation,
  ShapeDrawingAnnotation,
  TextDrawingAnnotation,
];

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

test("strictly round-trips every durable drawing variant as inert data", () => {
  for (const drawing of drawings) {
    const parsed = parseVttAnnotation(drawing);
    assert.deepEqual(parsed, drawing);
    assert.equal(isDrawingAnnotation(parsed), true);
  }
  assert.equal(isDrawingAnnotation(parseVttAnnotation(ping)), false);

  assert.throws(
    () => parseVttAnnotation({ ...drawings[0], style: { ...drawingStyle, stroke_color: "#ABCDEF" } }),
    /stroke_color/i,
  );
  assert.throws(
    () => parseVttAnnotation({ ...drawings[0], style: { ...drawingStyle, filter: "url(secret)" } }),
    /unexpected field.*filter/i,
  );
  assert.throws(
    () => parseVttAnnotation({ ...drawings[0], end: drawings[0].start }),
    /distinct/i,
  );
  assert.throws(
    () => parseVttAnnotation({ ...drawings[2], corner_b: { x_ft: 5, y_ft: 20, z_ft: 0 } }),
    /opposite corners/i,
  );
  assert.throws(
    () => parseVttAnnotation({ ...drawings[3], text: "unsafe\u0000text" }),
    /control/i,
  );
  assert.throws(
    () => parseVttAnnotation({
      ...drawings[1],
      points: Array.from({ length: 513 }, (_, index) => ({
        x_ft: index,
        y_ft: index % 2,
        z_ft: 0,
      })),
    }),
    /2-512/i,
  );
  assert.throws(
    () => parseVttAnnotation({
      ...drawings[1],
      points: [
        { x_ft: 5, y_ft: 5, z_ft: 0 },
        { x_ft: 10, y_ft: 10, z_ft: 0 },
        { x_ft: 5, y_ft: 5, z_ft: 0 },
      ],
    }),
    /unique/i,
  );
  assert.equal(isLockedDrawingAnnotation(drawings[1]), true);
  assert.equal(isLockedDrawingAnnotation(drawings[0]), false);
  assert.equal(isLockedDrawingAnnotation(ping), false);
});

test("annotation projection identity fails closed for every table binding", () => {
  const parsed = parseAnnotationsView(view);
  assert.equal(
    annotationViewMatchesIdentity(parsed, {
      sessionId: "echo-vault-session",
      tableId: "echo-vault-table",
      sceneId: "echo-vault",
    }),
    true,
  );
  for (const identity of [
    { sessionId: "other-session", tableId: "echo-vault-table", sceneId: "echo-vault" },
    { sessionId: "echo-vault-session", tableId: "other-table", sceneId: "echo-vault" },
    { sessionId: "echo-vault-session", tableId: "echo-vault-table", sceneId: "other-scene" },
  ]) {
    assert.equal(annotationViewMatchesIdentity(parsed, identity), false);
  }
});

test("updates one drawing event without disturbing unrelated records", () => {
  const initial = parseAnnotationsView({
    ...view,
    revision: 2,
    annotations: [drawings[0], drawings[1]],
  });
  const updatedArrow = {
    ...drawings[0],
    locked: true,
    style: { ...drawingStyle, opacity: 0.5 },
  };
  const event = parseAnnotationEvent({
    ...putEvent,
    sequence: 3,
    revision: 3,
    annotation_id: "draw-arrow",
    annotation: updatedArrow,
  });

  const next = applyAnnotationEvent(initial, event);

  assert.equal(next.revision, 3);
  assert.deepEqual(next.annotations, [updatedArrow, drawings[1]]);
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
