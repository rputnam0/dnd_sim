import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSceneActivateRequest,
  buildSceneArchiveRequest,
  buildSceneCreateRequest,
  buildSceneDuplicateRequest,
  buildSceneExportBundle,
  buildSceneImportRequest,
  parseSceneEvent,
  parseSceneExportBundle,
  parseSceneLibraryView,
  parseSceneSseBlock,
  streamSceneEvents,
} from "../app/vtt-scenes";

const mapMetadata = {
  schema_version: "vtt.scene_map_metadata.v1",
  name: "Moon Temple",
  width_px: 1920,
  height_px: 1080,
  grid_size_px: 70.0,
  gridless: false,
} as const;

const scene = {
  schema_version: "vtt.scene_record.v1",
  scene_id: "moon-temple",
  map_metadata: mapMetadata,
} as const;

const view = {
  schema_version: "vtt.scene_library_view.v1",
  table_id: "echo-vault-session",
  revision: 2,
  active_scene_id: "moon-temple",
  scenes: [
    { scene, archived: false },
    {
      scene: {
        ...scene,
        scene_id: "old-road",
        map_metadata: { ...mapMetadata, name: "Old Road", gridless: true },
      },
      archived: true,
    },
  ],
} as const;

test("strictly parses ordered scene library metadata without map blobs", () => {
  assert.deepEqual(parseSceneLibraryView(view), view);
  assert.throws(
    () =>
      parseSceneLibraryView({
        ...view,
        scenes: [
          {
            scene: {
              ...scene,
              map_metadata: { ...mapMetadata, image_url: "https://secret" },
            },
            archived: false,
          },
        ],
      }),
    /unexpected field.*image_url/i,
  );
  assert.throws(
    () => parseSceneLibraryView({ ...view, scenes: [...view.scenes].reverse() }),
    /sorted.*scene/i,
  );
});

test("accepts backend code-point ordering for non-BMP scene IDs", () => {
  const privateUse = "\uE000";
  const supplementary = "\u{10000}";
  assert.doesNotThrow(() =>
    parseSceneLibraryView({
      ...view,
      active_scene_id: privateUse,
      scenes: [
        {
          scene: { ...scene, scene_id: privateUse },
          archived: false,
        },
        {
          scene: { ...scene, scene_id: supplementary },
          archived: false,
        },
      ],
    }),
  );
});

test("builds exact create duplicate activate and safe archive requests", () => {
  assert.deepEqual(
    buildSceneCreateRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 2,
      commandId: "create-scene",
      scene,
    }),
    {
      schema_version: "vtt.scene_library_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.scene_command.v1",
        command_type: "create",
        table_id: "echo-vault-session",
        command_id: "create-scene",
        expected_revision: 2,
        scene,
      },
    },
  );
  assert.equal(
    buildSceneDuplicateRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 2,
      sourceSceneId: "moon-temple",
      newSceneId: "moon-temple-copy",
      newName: "Moon Temple Copy",
      commandId: "duplicate-scene",
    }).command.command_type,
    "duplicate",
  );
  assert.equal(
    buildSceneActivateRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 2,
      sceneId: "moon-temple",
      commandId: "activate-scene",
    }).command.command_type,
    "activate",
  );
  assert.deepEqual(
    buildSceneArchiveRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 2,
      sceneId: "moon-temple",
      successorSceneId: "old-road",
      commandId: "archive-scene",
    }).command,
    {
      schema_version: "vtt.scene_command.v1",
      command_type: "archive",
      table_id: "echo-vault-session",
      command_id: "archive-scene",
      expected_revision: 2,
      scene_id: "moon-temple",
      successor_scene_id: "old-road",
    },
  );
});

test("exports and imports the exact strict metadata bundle", () => {
  const bundle = buildSceneExportBundle(scene);
  assert.deepEqual(bundle, {
    schema_version: "vtt.scene_export.v1",
    scene,
  });
  assert.deepEqual(parseSceneExportBundle(JSON.stringify(bundle)), bundle);
  assert.equal(
    buildSceneImportRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      expectedRevision: 2,
      bundle,
      commandId: "import-scene",
    }).command.command_type,
    "import",
  );
  assert.throws(
    () => parseSceneExportBundle('{"schema_version":"vtt.scene_export.v0"}'),
    /scene_export|missing|schema/i,
  );
});

test("streams authenticated scene events from a reconnect cursor", async () => {
  const event = parseSceneEvent({
    schema_version: "vtt.scene_event.v1",
    table_id: "echo-vault-session",
    event_id: "echo-vault-session:scene:3",
    sequence: 3,
    revision: 3,
    command_id: "activate-scene",
    event_type: "activated",
    scene_id: "moon-temple",
    previous_scene_id: "old-road",
  });
  const block = [
    "id: 3",
    "event: vtt.scene_event",
    `data: ${JSON.stringify(event)}`,
  ].join("\n");
  assert.deepEqual(parseSceneSseBlock(block), event);

  const originalFetch = globalThis.fetch;
  const encoder = new TextEncoder();
  const received: unknown[] = [];
  globalThis.fetch = (async (input, init) => {
    assert.equal(
      String(input),
      "http://127.0.0.1:8000/api/v1/scene-events?after=1",
    );
    assert.deepEqual(init?.headers, {
      accept: "text/event-stream",
      authorization: "Bearer table-token-1234567890",
    });
    return new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(`: heartbeat\n\n${block}\n\n`));
          controller.close();
        },
      }),
      { status: 200 },
    );
  }) as typeof fetch;
  try {
    const cursor = await streamSceneEvents({
      after: 1,
      bearerToken: "table-token-1234567890",
      signal: new AbortController().signal,
      onEvent: (incoming) => received.push(incoming),
    });
    assert.equal(cursor, 3);
    assert.deepEqual(received, [event]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
