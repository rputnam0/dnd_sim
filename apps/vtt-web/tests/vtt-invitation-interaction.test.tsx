import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test, { type TestContext } from "node:test";
import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";
import { VttJoinGate } from "../app/vtt-join-gate";
import { VttInvitationsPanel } from "../app/vtt-invitations-panel";
import type { WorldLaunch } from "../app/vtt-installation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const BASE = "https://installation.test";
const CODE = "invitation_private_token_123456";
const TOKEN = "guest_private_bearer_123456";
const world = { schema_version: "vtt.world_record.v1", world_id: "world_one", table_id: "table_one", name: "Lantern Coast", system_id: "dnd5e" } as const;
const guest = { schema_version: "vtt.participant.v1", participant_id: "guest_one", display_name: "River", role: "player", owned_actor_ids: [] } as const;
const gm = { ...guest, participant_id: "gm_one", display_name: "Keeper", role: "gm" };
const launch = { schema_version: "vtt.world_launch.v1", world, session_id: "guest_session", workspace_api_path: "/api/v1/worlds/world_one", bearer_token: TOKEN, table: { schema_version: "vtt.table_view.v1", table_id: world.table_id, access_mode: "protected", current_participant: guest, participants: [gm, guest] } };
const invitation = { invitation_id: "inv_one", role: "player", created_at: 100, expires_at: 86500, status: "pending", participant: null };
const text = (node: TestRenderer.ReactTestInstance | string | number): string => typeof node === "object" ? node.children.map(text).join("") : String(node);
function button(root: TestRenderer.ReactTestInstance, label: string) { const found = root.findAllByType("button").find((item) => text(item) === label); assert.ok(found, `Missing button: ${label}`); return found; }
async function fill(root: TestRenderer.ReactTestInstance, id: string, value: string) { await act(async () => root.findByProps({ id }).props.onChange({ target: { value } })); }
async function click(root: TestRenderer.ReactTestInstance, label: string) { await act(async () => button(root, label).props.onClick()); }
async function redeem(root: TestRenderer.ReactTestInstance) {
  await fill(root, "invitation-code", CODE); await fill(root, "guest-display-name", "River");
  await act(async () => { void root.findByProps({ "aria-label": "Join a world" }).props.onSubmit({ preventDefault() {} }); });
}
function installFetch(context: TestContext, handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const original = globalThis.fetch;
  const calls: { url: string; init: RequestInit }[] = [];
  globalThis.fetch = async (url, init = {}) => { calls.push({ url: String(url), init }); return handler(String(url), init); };
  context.after(() => { globalThis.fetch = original; });
  return calls;
}
function workspace(url: string, init: RequestInit) {
  if (url.endsWith("/table")) return Response.json(launch.table);
  if (url.endsWith("/scenes")) return Response.json({ schema_version: "vtt.scene_library_view.v1", table_id: world.table_id, revision: 0, active_scene_id: null, scenes: [] });
  if (url.includes("scene-events")) return new Promise<Response>((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))));
  throw new Error(`Unexpected guest request: ${url}`);
}

test("join is memory-only, read-only and leaves before a delayed return completes", async (context) => {
  const storage: string[] = [];
  for (const key of ["localStorage", "sessionStorage"] as const) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, get() { storage.push(key); throw new Error("Guest credentials must never use storage"); } });
    context.after(() => { if (previous) Object.defineProperty(globalThis, key, previous); else Reflect.deleteProperty(globalThis, key); });
  }
  let resolveReturn!: (response: Response) => void;
  const calls = installFetch(context, (url, init) => url.endsWith("/join") ? Response.json(launch) : url.endsWith("/return") ? new Promise((resolve) => { resolveReturn = resolve; }) : workspace(url, init));
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttJoinGate, { apiBaseUrl: BASE })); });
  const root = renderer.root;
  assert.equal(root.findByProps({ id: "invitation-code" }).props.type, "password");
  await redeem(root);
  assert.match(text(root), /Lantern Coast/);
  assert.doesNotMatch(text(root), /Create scene|Upload|Activate|Archive|Scene library|Echo Vault|Initiative|Return to worlds/);
  assert.equal(JSON.stringify(renderer.toJSON()).includes(TOKEN), false);
  assert.equal(JSON.stringify(renderer.toJSON()).includes(CODE), false);
  assert.ok(calls.every(({ url }) => !url.includes(CODE) && !url.includes(TOKEN) && !url.includes("map-assets")));
  await click(root, "Leave world");
  assert.doesNotMatch(text(root), /Lantern Coast/);
  assert.match(text(root), /Join a world/);
  assert.ok(calls.filter(({ url }) => url.includes("scene-events")).every(({ init }) => init.signal?.aborted));
  await act(async () => resolveReturn(new Response(null, { status: 204 })));
  assert.equal(root.findByProps({ id: "invitation-code" }).props.value, "");
  assert.deepEqual(storage, []);
});

test("cancelled redemption cannot reopen a world or report its late failure", async (context) => {
  let settle!: (response: Response) => void;
  const calls = installFetch(context, () => new Promise((resolve) => { settle = resolve; }));
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttJoinGate, { apiBaseUrl: BASE })); });
  const root = renderer.root;
  await redeem(root);
  await click(root, "Cancel joining");
  assert.equal(calls[0].init.signal?.aborted, true);
  await act(async () => settle(Response.json(launch)));
  assert.doesNotMatch(text(root), /Lantern Coast/);
  assert.equal(root.findByProps({ id: "invitation-code" }).props.value, "");
});

test("a late failure from a cancelled redemption cannot clear a newer guest world", async (context) => {
  let settle!: (response: Response) => void; let joins = 0;
  const calls = installFetch(context, (url, init) => url.endsWith("/join") ? ++joins === 1 ? new Promise((resolve) => { settle = resolve; }) : Response.json(launch) : workspace(url, init));
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttJoinGate, { apiBaseUrl: BASE })); });
  await redeem(renderer.root);
  await click(renderer.root, "Cancel joining");
  await redeem(renderer.root);
  assert.match(text(renderer.root), /Lantern Coast/);
  await act(async () => settle(Response.json({ schema_version: "vtt.error.v1", code: "invalid_invitation", message: "Rejected", details: {} }, { status: 401 })));
  assert.match(text(renderer.root), /Lantern Coast/);
  assert.equal(calls[0].init.signal?.aborted, true);
});

test("focus revalidation immediately removes a revoked guest view and aborts scene streams", async (context) => {
  const priorWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const listeners = new Map<string, () => void>();
  Object.defineProperty(globalThis, "window", { configurable: true, value: { addEventListener: (name: string, listener: () => void) => listeners.set(name, listener), removeEventListener: (name: string) => listeners.delete(name) } });
  context.after(() => { if (priorWindow) Object.defineProperty(globalThis, "window", priorWindow); else Reflect.deleteProperty(globalThis, "window"); });
  let revoked = false;
  const calls = installFetch(context, (url, init) => {
    if (url.endsWith("/join")) return Response.json(launch);
    if (revoked && url.endsWith("/table")) return new Response(null, { status: 401 });
    return workspace(url, init);
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttJoinGate, { apiBaseUrl: BASE })); });
  await redeem(renderer.root);
  assert.match(text(renderer.root), /Lantern Coast/);
  revoked = true;
  await act(async () => listeners.get("focus")?.());
  assert.doesNotMatch(text(renderer.root), /Lantern Coast/);
  assert.match(text(renderer.root), /Access to this world ended/);
  assert.ok(calls.filter(({ url }) => url.includes("scene-events")).every(({ init }) => init.signal?.aborted));
  assert.equal(listeners.has("focus"), false);
});

test("guest principals cannot render invitation administration or fetch its records", async (context) => {
  const calls = installFetch(context, () => { throw new Error("No guest invitation request is allowed"); });
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttInvitationsPanel, { launch: JSON.parse(JSON.stringify(launch)) as WorldLaunch, apiBaseUrl: `${BASE}${launch.workspace_api_path}`, onAccessLost() {} })); });
  assert.equal(renderer.toJSON(), null);
  assert.deepEqual(calls, []);
});

test("published guest maps use authenticated media and clear on a refresh hint before rehydration", async (context) => {
  const bytes = new Uint8Array([137, 80, 78, 71]);
  const reference = { schema_version: "vtt.scene_map_asset.v1", asset_id: "public-map", media_type: "image/png", content_path: "/api/v1/map-assets/public-map/content.png", sha256: createHash("sha256").update(bytes).digest("hex"), alt_text: "Published coastline" };
  const scene = { schema_version: "vtt.scene_record.v1", scene_id: "coast", map_metadata: {
    schema_version: "vtt.scene_map_metadata.v1", name: "Published Coast", width_px: 800, height_px: 600, grid_size_px: 70, gridless: false,
    calibration: { schema_version: "vtt.board_calibration.v1", topology: "square", origin_x_px: 0, origin_y_px: 0, cell_extent_px: 70, distance_ft: 5 }, asset: reference,
  } };
  let stream!: ReadableStreamDefaultController<Uint8Array>;
  let resolveRefresh!: (response: Response) => void;
  let reads = 0;
  const revoked: string[] = []; const previousRevoke = URL.revokeObjectURL;
  URL.revokeObjectURL = (url) => { revoked.push(url); previousRevoke(url); };
  context.after(() => { URL.revokeObjectURL = previousRevoke; });
  const calls = installFetch(context, (url, init) => {
    if (url.endsWith("/join")) return Response.json(launch);
    if (url.endsWith("/scenes")) return ++reads === 1 ? Response.json({ schema_version: "vtt.scene_library_view.v1", table_id: world.table_id, revision: 1, active_scene_id: "coast", scenes: [{ scene, archived: false }] }) : new Promise((resolve) => { resolveRefresh = resolve; });
    if (url.endsWith(reference.content_path)) return new Response(bytes, { headers: { "content-type": "image/png" } });
    if (url.includes("scene-events")) return new Response(new ReadableStream({ start(controller) { stream = controller; init.signal?.addEventListener("abort", () => controller.close()); } }), { headers: { "content-type": "text/event-stream" } });
    return workspace(url, init);
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttJoinGate, { apiBaseUrl: BASE })); });
  await redeem(renderer.root);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  const preview = renderer.root.findByProps({ alt: "Published coastline" });
  assert.match(preview.props.src, /^blob:/);
  const previousUrl = preview.props.src;
  const content = calls.find(({ url }) => url.endsWith(reference.content_path));
  assert.equal(content?.url, `${BASE}${launch.workspace_api_path}${reference.content_path}`);
  assert.equal(new Headers(content?.init.headers).get("authorization"), `Bearer ${TOKEN}`);
  assert.equal(calls.some(({ url }) => url.endsWith("/map-assets")), false);
  await act(async () => stream.enqueue(new TextEncoder().encode('id: 2\nevent: vtt.scene_refresh\ndata: {"revision":2}\n\n')));
  assert.equal(renderer.root.findAllByType("img").length, 0);
  assert.ok(revoked.includes(previousUrl));
  await act(async () => resolveRefresh(Response.json({ schema_version: "vtt.scene_library_view.v1", table_id: world.table_id, revision: 2, active_scene_id: null, scenes: [] })));
  assert.match(text(renderer.root), /Waiting for the scene/);
});

test("redemption error clears the code and explains single-use recovery without leaking server prose", async (context) => {
  installFetch(context, () => Response.json({ schema_version: "vtt.error.v1", code: "invalid_invitation", message: CODE, details: {} }, { status: 401 }));
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttJoinGate, { apiBaseUrl: BASE })); });
  await redeem(renderer.root);
  assert.match(text(renderer.root), /new invitation/);
  assert.equal(renderer.root.findByProps({ id: "invitation-code" }).props.value, "");
  assert.equal(JSON.stringify(renderer.toJSON()).includes(CODE), false);
});

test("a guest explicitly retries a failed published map without rejoining or requesting authoring data", async (context) => {
  const bytes = new Uint8Array([137, 80, 78, 71]);
  const reference = { schema_version: "vtt.scene_map_asset.v1", asset_id: "retry-map", media_type: "image/png", content_path: "/api/v1/map-assets/retry-map/content.png", sha256: createHash("sha256").update(bytes).digest("hex"), alt_text: "Recovered published map" };
  const scene = { schema_version: "vtt.scene_record.v1", scene_id: "coast", map_metadata: {
    schema_version: "vtt.scene_map_metadata.v1", name: "Published Coast", width_px: 800, height_px: 600, grid_size_px: 70, gridless: false,
    calibration: { schema_version: "vtt.board_calibration.v1", topology: "square", origin_x_px: 0, origin_y_px: 0, cell_extent_px: 70, distance_ft: 5 }, asset: reference,
  } };
  let mediaRequests = 0;
  const calls = installFetch(context, (url, init) => {
    if (url.endsWith("/join")) return Response.json(launch);
    if (url.endsWith("/scenes")) return Response.json({ schema_version: "vtt.scene_library_view.v1", table_id: world.table_id, revision: 1, active_scene_id: "coast", scenes: [{ scene, archived: false }] });
    if (url.endsWith(reference.content_path)) {
      mediaRequests += 1;
      return mediaRequests === 1 ? new Response(null, { status: 503 }) : new Response(bytes, { headers: { "content-type": "image/png" } });
    }
    return workspace(url, init);
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  await act(async () => { renderer = TestRenderer.create(createElement(VttJoinGate, { apiBaseUrl: BASE })); });
  await redeem(renderer.root);
  assert.equal(mediaRequests, 1);
  assert.equal(renderer.root.findAllByType("img").length, 0);
  assert.match(text(renderer.root), /published map image could not be verified/);
  await click(renderer.root, "Retry published map");
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  assert.match(renderer.root.findByProps({ alt: "Recovered published map" }).props.src, /^blob:/);
  assert.equal(mediaRequests, 2);
  assert.doesNotMatch(text(renderer.root), /published map image could not be verified/);
  assert.equal(calls.filter(({ url }) => url.endsWith("/join")).length, 1);
  assert.equal(calls.filter(({ url }) => url.endsWith("/scenes")).length, 2);
  assert.equal(calls.some(({ url }) => url.endsWith("/map-assets")), false);
  assert.ok(calls.filter(({ url }) => url.endsWith(reference.content_path)).every(({ init }) => new Headers(init.headers).get("authorization") === `Bearer ${TOKEN}`));
});

test("GM explicitly copies an issued code and confirms revocation; replay never invents a secret", async (context) => {
  let copied = ""; let issues = 0;
  const calls = installFetch(context, (url, init) => {
    if (url.endsWith("/revoke")) return new Response(null, { status: 204 });
    if (init.method === "POST") { issues += 1; return Response.json({ schema_version: "vtt.invitation_issued.v1", invitation, replayed: issues > 1, invitation_token: issues > 1 ? null : CODE }, { status: 201 }); }
    return Response.json({ schema_version: "vtt.world_invitations.v1", world_id: world.world_id, table_id: world.table_id, invitations: [invitation] });
  });
  let renderer!: TestRenderer.ReactTestRenderer;
  context.after(async () => { await act(async () => renderer.unmount()); });
  const gmLaunch = JSON.parse(JSON.stringify({ ...launch, table: { ...launch.table, current_participant: gm } })) as WorldLaunch;
  await act(async () => { renderer = TestRenderer.create(createElement(VttInvitationsPanel, { launch: gmLaunch, apiBaseUrl: `${BASE}${launch.workspace_api_path}`, onAccessLost() {}, copyCode: async (code: string) => { copied = code; } })); });
  await click(renderer.root, "Create player invitation");
  assert.equal(copied, "");
  await click(renderer.root, "Copy invitation code");
  assert.equal(copied, CODE);
  await click(renderer.root, "Revoke invitation");
  assert.equal(calls.filter(({ url }) => url.endsWith("/revoke")).length, 0);
  await click(renderer.root, "Confirm revoke");
  assert.equal(calls.filter(({ url }) => url.endsWith("/revoke")).length, 1);
  await click(renderer.root, "Create player invitation");
  assert.match(text(renderer.root), /cannot be recovered/);
  assert.equal(renderer.root.findAllByType("button").some((item) => text(item) === "Copy invitation code"), false);
});
