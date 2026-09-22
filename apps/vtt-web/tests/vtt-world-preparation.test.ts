import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { InstallationApi, parseWorldDashboard, parseWorldLaunch, type WorldRecord } from "../app/vtt-installation";
import { getSceneLibraryView, sceneEventsUrl, streamSceneEvents } from "../app/vtt-scenes";
import { fetchAuthenticatedMapAsset, getMapAssetCatalog } from "../app/vtt-map-assets";

const world: WorldRecord = {
  schema_version: "vtt.world_record.v1", world_id: "world_one", table_id: "table_one",
  name: "The Lantern Coast", system_id: "dnd5e",
};
const participant = {
  schema_version: "vtt.participant.v1", participant_id: "gm_one", display_name: "Keeper",
  role: "gm", owned_actor_ids: [],
};
const launch = {
  schema_version: "vtt.world_launch.v1", world, session_id: "workspace_one",
  table: {
    schema_version: "vtt.table_view.v1", table_id: world.table_id, access_mode: "protected",
    current_participant: participant, participants: [participant],
  },
  workspace_api_path: "/api/v1/worlds/world_one", bearer_token: "world_private_bearer_123456",
};
const scoped = "https://installation.test/standalone/api/v1/worlds/world_one";

test("launch codec accepts only the requested world, protected table and exact local mount", () => {
  assert.deepEqual(parseWorldLaunch(launch, world), launch);
  for (const invalid of [
    { ...launch, schema_version: "vtt.world_launch.v2" },
    { ...launch, world: { ...world, world_id: "world_other" } },
    { ...launch, world: { ...world, table_id: "table_other" } },
    { ...launch, world: { ...world, name: "Unverified rename" } },
    { ...launch, table: { ...launch.table, table_id: "table_other" } },
    { ...launch, table: { ...launch.table, access_mode: "open_local" } },
    { ...launch, bearer_token: "short" },
    { ...launch, bearer_token: "world secret whitespace" },
    { ...launch, private_credentials: "leak" },
    ...["https://evil.test/api/v1/worlds/world_one", "//evil.test", "/api/v1/worlds/world_other", "/api/v1/worlds/world_one/../other", "/api/v1/worlds/world_one?token=secret"].map((workspace_api_path) => ({ ...launch, workspace_api_path })),
  ]) assert.throws(() => parseWorldLaunch(invalid, world));
});

test("dashboard launch capability and unavailability reason must agree", () => {
  const dashboard = {
    schema_version: "vtt.world_dashboard.v1",
    catalog: { schema_version: "vtt.world_catalog_view.v1", revision: 1, worlds: [{ world, archived: false }] },
    launch_supported: true, launch_unavailable_reason: null,
  };
  assert.deepEqual(parseWorldDashboard(dashboard), dashboard);
  assert.throws(() => parseWorldDashboard({ ...dashboard, launch_supported: false }));
  assert.throws(() => parseWorldDashboard({ ...dashboard, launch_unavailable_reason: "world_provisioning_not_implemented" }));
});

test("launch uses the administrator bearer but return uses only the world bearer, with no credentials in URLs", async () => {
  const requests: { url: string; init: RequestInit }[] = [];
  const api = new InstallationApi("https://installation.test/standalone/", async (url, init = {}) => {
    requests.push({ url: String(url), init });
    return String(url).endsWith("/return") ? new Response(null, { status: 204 }) : Response.json(launch);
  });
  const controller = new AbortController();
  const result = await api.launch("admin_private_bearer_123456", world, controller.signal);
  assert.equal(api.workspaceBaseUrl(result), scoped);
  await api.returnWorld(result.world.world_id, result.bearer_token, controller.signal);
  assert.deepEqual(requests.map((request) => request.url), [
    "https://installation.test/standalone/api/v1/installation/worlds/world_one/launch",
    "https://installation.test/standalone/api/v1/installation/worlds/world_one/return",
  ]);
  assert.deepEqual(requests.map(({ init }) => new Headers(init.headers).get("authorization")), [
    "Bearer admin_private_bearer_123456", `Bearer ${launch.bearer_token}`,
  ]);
  for (const { init } of requests) {
    assert.equal(init.method, "POST"); assert.equal(init.body, undefined);
    assert.equal(init.credentials, "omit"); assert.equal(init.redirect, "error");
  }
});

test("scene, stream, catalog and authenticated media preserve the same explicit workspace prefix", async (context) => {
  const original = globalThis.fetch;
  const requests: { url: string; init: RequestInit }[] = [];
  const content = new Uint8Array([137, 80, 78, 71]);
  globalThis.fetch = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    if (String(url).endsWith("/scenes")) return Response.json({ schema_version: "vtt.scene_library_view.v1", table_id: world.table_id, revision: 0, active_scene_id: null, scenes: [] });
    if (String(url).endsWith("/map-assets")) return Response.json({ schema_version: "vtt.map_asset_catalog.v1", table_id: world.table_id, revision: 0, assets: [] });
    if (String(url).includes("scene-events")) return new Response(": connected\n\n", { headers: { "content-type": "text/event-stream" } });
    return new Response(content, { headers: { "content-type": "image/png" } });
  };
  context.after(() => { globalThis.fetch = original; });
  await getSceneLibraryView(undefined, launch.bearer_token, scoped);
  await getMapAssetCatalog(undefined, launch.bearer_token, scoped);
  await streamSceneEvents({ after: 0, bearerToken: launch.bearer_token, apiBaseUrl: scoped, signal: new AbortController().signal, onEvent() {} });
  await fetchAuthenticatedMapAsset({
    schema_version: "vtt.scene_map_asset.v1", asset_id: "coast", media_type: "image/png",
    content_path: "/api/v1/map-assets/coast/content.png", alt_text: "Coast",
    sha256: createHash("sha256").update(content).digest("hex"),
  }, launch.bearer_token, undefined, scoped);
  assert.equal(sceneEventsUrl(0, scoped), `${scoped}/api/v1/scene-events?after=0`);
  assert.deepEqual(requests.map(({ url }) => url), [
    `${scoped}/api/v1/scenes`, `${scoped}/api/v1/map-assets`, `${scoped}/api/v1/scene-events?after=0`, `${scoped}/api/v1/map-assets/coast/content.png`,
  ]);
  for (const { init } of requests) {
    assert.equal(new Headers(init.headers).get("authorization"), `Bearer ${launch.bearer_token}`);
    assert.equal(init.credentials, "omit"); assert.equal(init.redirect, "error");
  }
});
