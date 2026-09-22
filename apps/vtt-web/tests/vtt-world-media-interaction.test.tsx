import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { useVttMapAssetUrl } from "../app/use-vtt-map-assets";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const bytes = new Uint8Array([137, 80, 78, 71]);
const reference = {
  schema_version: "vtt.scene_map_asset.v1", asset_id: "same-map", media_type: "image/png",
  content_path: "/api/v1/map-assets/same-map/content.png", alt_text: "Private map",
  sha256: createHash("sha256").update(bytes).digest("hex"),
} as const;

function Probe({ token, apiBaseUrl, onAccessLost }: { token: string; apiBaseUrl: string; onAccessLost: () => void }) {
  const media = useVttMapAssetUrl(reference, token, apiBaseUrl, onAccessLost);
  return createElement("output", { "data-url": media.url, "data-loading": media.loading, "data-error": media.error });
}

test("changing only a map bearer synchronously hides and revokes the previous private object URL", async (context) => {
  const originalFetch = globalThis.fetch;
  const originalRevoke = URL.revokeObjectURL;
  const revoked: string[] = [];
  let resolveNew!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { resolveNew = resolve; });
  globalThis.fetch = async (_url, init) => new Headers(init?.headers).get("authorization") === "Bearer world_second_private_token" ? pending : new Response(bytes, { headers: { "content-type": "image/png" } });
  URL.revokeObjectURL = (url) => { revoked.push(url); originalRevoke(url); };
  let renderer: TestRenderer.ReactTestRenderer;
  context.after(async () => {
    await act(async () => renderer?.unmount());
    globalThis.fetch = originalFetch; URL.revokeObjectURL = originalRevoke;
  });
  const props = { apiBaseUrl: "https://install.test/proxy/api/v1/worlds/one", token: "world_first_private_token", onAccessLost() {} };
  await act(async () => { renderer = TestRenderer.create(createElement(Probe, props)); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  const previous = renderer!.root.findByType("output").props["data-url"];
  assert.match(previous, /^blob:/);
  await act(async () => { renderer!.update(createElement(Probe, { ...props, token: "world_second_private_token" })); });
  assert.equal(renderer!.root.findByType("output").props["data-url"], null);
  assert.equal(renderer!.root.findByType("output").props["data-loading"], true);
  assert.ok(revoked.includes(previous));
  await act(async () => { resolveNew(new Response(bytes, { headers: { "content-type": "image/png" } })); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  const next = renderer!.root.findByType("output").props["data-url"];
  assert.match(next, /^blob:/);
  assert.notEqual(next, previous);
});

test("an old world's delayed media authentication failure cannot clear the next world's preview", async (context) => {
  const originalFetch = globalThis.fetch;
  let resolveOld!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { resolveOld = resolve; });
  const calls: { url: string; signal?: AbortSignal | null }[] = [];
  let accessLost = 0;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), signal: init?.signal });
    return String(url).includes("/worlds/one/") ? pending : new Response(bytes, { headers: { "content-type": "image/png" } });
  };
  let renderer: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer?.unmount()); globalThis.fetch = originalFetch; });
  const props = { apiBaseUrl: "https://install.test/proxy/api/v1/worlds/one", token: "world_first_private_token", onAccessLost() { accessLost += 1; } };
  await act(async () => { renderer = TestRenderer.create(createElement(Probe, props)); });
  await act(async () => { renderer!.update(createElement(Probe, { ...props, apiBaseUrl: "https://install.test/proxy/api/v1/worlds/two", token: "world_second_private_token" })); });
  await act(async () => { resolveOld(new Response(null, { status: 401 })); await new Promise((resolve) => setTimeout(resolve, 10)); });
  assert.equal(accessLost, 0);
  assert.equal(calls[0].signal?.aborted, true);
  assert.match(renderer!.root.findByType("output").props["data-url"], /^blob:/);
  assert.equal(renderer!.root.findByType("output").props["data-error"], null);
});
