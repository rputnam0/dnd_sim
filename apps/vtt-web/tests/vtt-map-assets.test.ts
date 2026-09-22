import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  blobToBase64,
  buildMapAssetUploadRequest,
  fetchAuthenticatedMapAsset,
  parseMapAssetCatalog,
  parseMapAssetUploadResponse,
} from "../app/vtt-map-assets";

const content = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const digest = createHash("sha256").update(content).digest("hex");
const reference = {
  schema_version: "vtt.scene_map_asset.v1",
  asset_id: "moon-temple",
  media_type: "image/png",
  content_path: "/api/v1/map-assets/moon-temple/content.png",
  sha256: digest,
  alt_text: "A top-down moon temple battle map.",
} as const;
const record = {
  schema_version: "vtt.map_asset_record.v1",
  reference,
  width_px: 80,
  height_px: 60,
  byte_size: content.byteLength,
} as const;

test("builds a strict versioned upload request from canonical base64", async () => {
  const contentBase64 = await blobToBase64(new Blob([content]));
  assert.equal(contentBase64, "iVBORw0KGgo=");
  assert.deepEqual(
    buildMapAssetUploadRequest({
      sessionId: "echo-vault-session",
      tableId: "echo-vault-session",
      commandId: "upload-map",
      expectedRevision: 3,
      assetId: "moon-temple",
      altText: reference.alt_text,
      contentBase64,
    }),
    {
      schema_version: "vtt.map_asset_upload_request.v1",
      session_id: "echo-vault-session",
      command: {
        schema_version: "vtt.map_asset_upload_command.v1",
        table_id: "echo-vault-session",
        command_id: "upload-map",
        expected_revision: 3,
        asset_id: "moon-temple",
        alt_text: reference.alt_text,
        content_base64: contentBase64,
      },
    },
  );
});

test("strictly parses catalog and upload responses", () => {
  assert.deepEqual(
    parseMapAssetCatalog({
      schema_version: "vtt.map_asset_catalog.v1",
      table_id: "echo-vault-session",
      revision: 1,
      assets: [record],
    }).assets,
    [record],
  );
  assert.deepEqual(
    parseMapAssetUploadResponse({
      schema_version: "vtt.map_asset_upload_response.v1",
      session_id: "echo-vault-session",
      table_id: "echo-vault-session",
      command_id: "upload-map",
      revision: 1,
      replayed: false,
      asset: record,
    }).asset,
    record,
  );
  assert.throws(
    () =>
      parseMapAssetCatalog({
        schema_version: "vtt.map_asset_catalog.v1",
        table_id: "echo-vault-session",
        revision: 1,
        assets: [record, record],
      }),
    /unique|sorted|asset/i,
  );
});

test("fetches protected asset bytes with bearer auth and verifies integrity", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input, init) => {
    assert.equal(
      String(input),
      "http://127.0.0.1:8000/api/v1/map-assets/moon-temple/content.png",
    );
    assert.deepEqual(init?.headers, {
      accept: "image/png",
      authorization: "Bearer table-token-1234567890",
    });
    return new Response(content, {
      status: 200,
      headers: { "content-type": "image/png" },
    });
  }) as typeof fetch;
  try {
    const blob = await fetchAuthenticatedMapAsset(
      reference,
      "table-token-1234567890",
    );
    assert.equal(blob.type, "image/png");
    assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), content);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects content type or digest mismatch after authenticated fetch", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(content, {
      status: 200,
      headers: { "content-type": "image/jpeg" },
    })) as typeof fetch;
  try {
    await assert.rejects(
      fetchAuthenticatedMapAsset(reference, null),
      /content type/i,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
