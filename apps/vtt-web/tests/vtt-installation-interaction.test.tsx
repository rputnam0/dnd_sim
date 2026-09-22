import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test, { type TestContext } from "node:test";
import { createElement } from "react";
import TestRenderer, { act } from "react-test-renderer";

import { VttInstallationGate } from "../app/vtt-installation-gate";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const API_BASE = "http://installation.test:8001";
const API_ROOT = `${API_BASE}/api/v1/installation`;
const PASSWORD = "private administrator password 84019";
const CLAIM = "setup_private_claim_94829_do_not_persist";
const BEARER = "vtt1_private_session_48920_do_not_persist";
const admin = {
  schema_version: "vtt.admin_public.v1",
  admin_id: "adm_keeper",
  username: "keeper",
  display_name: "The Keeper",
  created_at: 1,
};
const session = {
  schema_version: "vtt.admin_session_public.v1",
  session_id: "ses_keeper",
  admin_id: admin.admin_id,
  issued_at: Math.floor(Date.now() / 1_000),
  expires_at: Math.floor(Date.now() / 1_000) + 3_600,
  revoked: false,
};
const privateWorld = {
  schema_version: "vtt.world_record.v1",
  world_id: "world_private",
  table_id: "table_private",
  name: "Private Moonlit Archive",
  system_id: "dnd5e",
};

function installation(state: "uninitialized" | "ready" | "safe_mode") {
  return {
    schema_version: "vtt.installation_view.v1",
    state,
    revision: state === "uninitialized" ? 0 : 1,
    setup_claimed: state === "safe_mode" ? null : state === "ready",
    active_admin_count: state === "safe_mode" ? null : state === "ready" ? 1 : 0,
    integrity_status: state === "safe_mode" ? "failed" : "verified",
  };
}

function dashboard(worlds = [{ world: privateWorld, archived: false }], revision = 1) {
  return {
    schema_version: "vtt.world_dashboard.v1",
    catalog: { schema_version: "vtt.world_catalog_view.v1", revision, worlds },
    launch_supported: false,
    launch_unavailable_reason: "world_provisioning_not_implemented",
  };
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

function apiError(status: number, code: string): Response {
  return json({ schema_version: "vtt.error.v1", code, message: "Request rejected.", details: {} }, status);
}

interface ApiCall {
  path: string;
  url: string;
  method: string;
  init: RequestInit;
}

type RequestHandler = (call: ApiCall) => Response | Promise<Response>;

async function mountGate(context: TestContext, handler: RequestHandler) {
  const originalFetch = globalThis.fetch;
  const calls: ApiCall[] = [];
  let renderer: TestRenderer.ReactTestRenderer | undefined;
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    assert.ok(url.startsWith(API_ROOT) || url.startsWith(`${API_BASE}/api/v1/worlds/`), `Unexpected service request: ${url}`);
    const call = { path: url.startsWith(API_ROOT) ? url.slice(API_ROOT.length) : `/workspace${url.slice(API_BASE.length)}`, url, method: init.method ?? "GET", init };
    calls.push(call);
    return handler(call);
  };
  context.after(async () => {
    try {
      await act(async () => renderer?.unmount());
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
  await act(async () => {
    renderer = TestRenderer.create(createElement(VttInstallationGate, { apiBaseUrl: API_BASE }));
  });
  assert.ok(renderer);
  return { renderer, root: renderer.root, calls };
}

function textContent(node: TestRenderer.ReactTestInstance | string | number): string {
  return typeof node === "object" ? node.children.map(textContent).join("") : String(node);
}

function button(root: TestRenderer.ReactTestInstance, name: string | RegExp) {
  const found = root.findAllByType("button").find((item) => {
    const label = String(item.props["aria-label"] ?? textContent(item));
    return typeof name === "string" ? label === name : name.test(label);
  });
  assert.ok(found, `Missing button ${name}`);
  return found;
}

async function fill(root: TestRenderer.ReactTestInstance, id: string, value: string) {
  await act(async () => {
    root.findByProps({ id }).props.onChange({ target: { value }, currentTarget: { value } });
  });
}

async function submit(root: TestRenderer.ReactTestInstance, label: string) {
  await act(async () => {
    await root.findByProps({ "aria-label": label }).props.onSubmit({ preventDefault() {} });
  });
}

async function click(root: TestRenderer.ReactTestInstance, name: string | RegExp) {
  await act(async () => { await button(root, name).props.onClick(); });
}

async function login(root: TestRenderer.ReactTestInstance) {
  await fill(root, "username", admin.username);
  await fill(root, "password", PASSWORD);
  await submit(root, "Administrator login");
}

function authenticatedHandler(overrides?: RequestHandler): RequestHandler {
  return (call) => {
    if (call.path === "") return json(installation("ready"));
    if (call.path === "/login") {
      return json({ schema_version: "vtt.installation_login.v1", admin, session, bearer_token: BEARER });
    }
    if (call.path === "/session") {
      return json({ schema_version: "vtt.installation_session.v1", admin, session });
    }
    if (overrides) return overrides(call);
    if (call.path === "/worlds") return json(dashboard());
    if (call.path === "/logout") return new Response(null, { status: 204 });
    throw new Error(`Unexpected request: ${call.method} ${call.path}`);
  };
}

function observeStorage(context: TestContext): string[] {
  const operations: string[] = [];
  for (const name of ["localStorage", "sessionStorage"] as const) {
    const original = Object.getOwnPropertyDescriptor(globalThis, name);
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value: {
        getItem(key: string) { operations.push(`${name}.getItem:${key}`); return null; },
        setItem(key: string, value: string) { operations.push(`${name}.setItem:${key}:${value}`); },
        removeItem(key: string) { operations.push(`${name}.removeItem:${key}`); },
        clear() { operations.push(`${name}.clear`); },
        key() { return null; },
        length: 0,
      },
    });
    context.after(() => {
      if (original) Object.defineProperty(globalThis, name, original);
      else Reflect.deleteProperty(globalThis, name);
    });
  }
  return operations;
}

const WORLD_BEARER = "world_private_launch_bearer_123456";
function worldLaunch(world = privateWorld, token = WORLD_BEARER) {
  const participant = { schema_version: "vtt.participant.v1", participant_id: "gm_keeper", display_name: admin.display_name, role: "gm", owned_actor_ids: [] };
  return {
    schema_version: "vtt.world_launch.v1", world, session_id: `workspace_${world.world_id}`,
    table: { schema_version: "vtt.table_view.v1", table_id: world.table_id, access_mode: "protected", current_participant: participant, participants: [participant] },
    workspace_api_path: `/api/v1/worlds/${world.world_id}`, bearer_token: token,
  };
}
function preparationDashboard(worlds = [{ world: privateWorld, archived: false }]) {
  return { ...dashboard(worlds), launch_supported: true, launch_unavailable_reason: null };
}
function emptyWorkspace(call: ApiCall, world = privateWorld, token = WORLD_BEARER): Response | Promise<Response> {
  assert.equal(new Headers(call.init.headers).get("authorization"), `Bearer ${token}`);
  if (call.url.endsWith("/api/v1/table")) return json(worldLaunch(world).table);
  if (call.url.endsWith("/api/v1/scenes")) return json({ schema_version: "vtt.scene_library_view.v1", table_id: world.table_id, revision: 0, active_scene_id: null, scenes: [] });
  if (call.url.endsWith("/api/v1/map-assets")) return json({ schema_version: "vtt.map_asset_catalog.v1", table_id: world.table_id, revision: 0, assets: [] });
  if (call.url.includes("/api/v1/scene-events")) return new Promise((_resolve, reject) => {
    call.init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  });
  throw new Error(`Unexpected workspace request: ${call.url}`);
}

test("mounted preparation opens an honest empty world with isolated credentials and returns to its catalog", async (context) => {
  const storage = observeStorage(context);
  const { root, renderer, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard());
    if (call.path.endsWith("/launch")) return json(worldLaunch());
    if (call.path.endsWith("/return")) return new Response(null, { status: 204 });
    return emptyWorkspace(call);
  }));
  await login(root);
  assert.match(textContent(root), /initial Game Master/);
  await click(root, /Prepare & open/);
  assert.match(textContent(root), /A blank canvas for your world/);
  assert.match(textContent(root), /Scene library/);
  assert.doesNotMatch(textContent(root), /Echo Vault|Initiative|Round 1|encounter running/i);
  for (const secret of [BEARER, WORLD_BEARER]) assert.equal(JSON.stringify(renderer.toJSON()).includes(secret), false);
  assert.equal(calls.some((call) => call.url.includes(BEARER) || call.url.includes(WORLD_BEARER)), false);
  assert.deepEqual(storage, []);
  await click(root, "Return to worlds");
  assert.match(textContent(root), /Worlds worth returning to/);
  assert.doesNotMatch(textContent(root), /Scene library|A blank canvas/);
  const returned = calls.find((call) => call.path.endsWith("/return"));
  assert.equal(new Headers(returned?.init.headers).get("authorization"), `Bearer ${WORLD_BEARER}`);
  assert.ok(calls.filter((call) => call.path.includes("scene-events")).every((call) => call.init.signal?.aborted));
});

test("mounted failed return clears private world immediately and reports unconfirmed server revocation", async (context) => {
  let resolveReturn!: (response: Response) => void;
  const pendingReturn = new Promise<Response>((resolve) => { resolveReturn = resolve; });
  const { root } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard());
    if (call.path.endsWith("/launch")) return json(worldLaunch());
    if (call.path.endsWith("/return")) return pendingReturn;
    return emptyWorkspace(call);
  }));
  await login(root);
  await click(root, /Prepare & open/);
  let returning!: Promise<void>;
  await act(async () => { returning = button(root, "Return to worlds").props.onClick(); });
  assert.doesNotMatch(textContent(root), /Scene library|A blank canvas/);
  await act(async () => { resolveReturn(apiError(503, "storage_unavailable")); await returning; });
  assert.match(textContent(root), /revocation could not be confirmed/i);
  assert.doesNotMatch(textContent(root), /Scene library/);
});

test("mounted logout aborts an in-flight launch and ignores its late response", async (context) => {
  let resolveLaunch!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { resolveLaunch = resolve; });
  const { root, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard());
    if (call.path.endsWith("/launch")) return pending;
    if (call.path === "/logout") return new Response(null, { status: 204 });
    throw new Error(`Unexpected request ${call.path}`);
  }));
  await login(root);
  let launching!: Promise<void>;
  await act(async () => { launching = button(root, /Prepare & open/).props.onClick(); });
  await click(root, "Log out");
  await act(async () => { resolveLaunch(json(worldLaunch())); await launching; });
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive|Scene library/);
  assert.equal(calls.find((call) => call.path.endsWith("/launch"))?.init.signal?.aborted, true);
  assert.equal(calls.some((call) => call.path.startsWith("/workspace")), false);
});

test("mounted revoked world access removes the workspace and keeps the administrator catalog separate", async (context) => {
  const { root } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard());
    if (call.path.endsWith("/launch")) return json(worldLaunch());
    if (call.url.endsWith("/api/v1/table")) return apiError(401, "world_session_revoked");
    return emptyWorkspace(call);
  }));
  await login(root);
  await click(root, /Prepare & open/);
  assert.match(textContent(root), /World access ended/i);
  assert.match(textContent(root), /Worlds worth returning to/);
  assert.doesNotMatch(textContent(root), /Scene library/);
});

test("mounted world switching isolates tokens and ignores a previous world's late unauthorized scene reply", async (context) => {
  const second = { ...privateWorld, world_id: "world_second", table_id: "table_second", name: "Second Private World" };
  const secondToken = "world_second_launch_bearer_987654";
  let resolveOldScenes!: (response: Response) => void;
  const oldScenes = new Promise<Response>((resolve) => { resolveOldScenes = resolve; });
  const { root, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard([{ world: privateWorld, archived: false }, { world: second, archived: false }]));
    if (call.path === `/worlds/${privateWorld.world_id}/launch`) return json(worldLaunch());
    if (call.path === `/worlds/${second.world_id}/launch`) return json(worldLaunch(second, secondToken));
    if (call.path.endsWith("/return")) return new Response(null, { status: 204 });
    if (call.url.endsWith(`/worlds/${privateWorld.world_id}/api/v1/scenes`)) return oldScenes;
    return call.url.includes(`/worlds/${second.world_id}/`) ? emptyWorkspace(call, second, secondToken) : emptyWorkspace(call);
  }));
  await login(root);
  await click(root.findByProps({ "aria-label": `World: ${privateWorld.name}` }), /Prepare & open/);
  await click(root, "Return to worlds");
  await click(root.findByProps({ "aria-label": `World: ${second.name}` }), /Prepare & open/);
  await act(async () => { resolveOldScenes(apiError(401, "world_session_revoked")); });
  assert.equal(root.findAllByProps({ "aria-label": `World preparation: ${second.name}` }).length, 1);
  assert.match(textContent(root), /A blank canvas/);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive|World access ended/);
  assert.ok(calls.filter((call) => call.path.startsWith("/workspace") && call.url.includes(`/worlds/${privateWorld.world_id}/`)).every((call) => call.init.signal?.aborted));
  for (const call of calls.filter((call) => call.path.startsWith("/workspace") && call.url.includes(`/worlds/${second.world_id}/`))) {
    assert.equal(new Headers(call.init.headers).get("authorization"), `Bearer ${secondToken}`);
  }
});

test("mounted scene creation shows only persisted scene metadata and a truthful raw map preview", async (context) => {
  let savedScene: unknown = null;
  const { root, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard());
    if (call.path.endsWith("/launch")) return json(worldLaunch());
    if (call.path.endsWith("/return")) return new Response(null, { status: 204 });
    if (call.url.endsWith("/api/v1/scene-commands")) {
      const request = JSON.parse(String(call.init.body));
      savedScene = request.command.scene;
      assert.equal(request.session_id, `workspace_${privateWorld.world_id}`);
      assert.equal(request.command.table_id, privateWorld.table_id);
      return json({ schema_version: "vtt.scene_library_response.v1", session_id: request.session_id,
        table_id: privateWorld.table_id, command_id: request.command.command_id, revision: 1, replayed: false,
        event: { schema_version: "vtt.scene_event.v1", table_id: privateWorld.table_id, event_id: "created_scene", sequence: 1, revision: 1, command_id: request.command.command_id, event_type: "created", scene: savedScene, became_active: true },
      });
    }
    if (savedScene && call.url.endsWith("/api/v1/scenes")) return json({ schema_version: "vtt.scene_library_view.v1", table_id: privateWorld.table_id, revision: 1, active_scene_id: "quiet-coast", scenes: [{ scene: savedScene, archived: false }] });
    return emptyWorkspace(call);
  }));
  await login(root);
  await click(root, /Prepare & open/);
  const form = root.findAllByType("form").find((node) => textContent(node).startsWith("Create scene"));
  assert.ok(form);
  await act(async () => {
    form.findByProps({ placeholder: "moon-temple" }).props.onChange({ target: { value: "quiet-coast" } });
    form.findByProps({ placeholder: "Moon Temple" }).props.onChange({ target: { value: "The Quiet Coast" } });
  });
  await act(async () => { await form.props.onSubmit({ preventDefault() {} }); });
  assert.match(textContent(root), /The Quiet Coast/);
  assert.match(textContent(root), /Your scene is ready for a map/);
  assert.match(textContent(root), /Raw map preview/);
  assert.doesNotMatch(textContent(root), /A blank canvas|Echo Vault|Initiative/);
  assert.equal(calls.filter((call) => call.url.endsWith("/api/v1/scene-commands")).length, 1);
  await click(root, "Return to worlds");
  await click(root, /Prepare & open/);
  assert.match(textContent(root), /The Quiet Coast/);
});

for (const topology of ["hex_flat", "gridless"] as const) {
test(`mounted authenticated ${topology} map preview reports honest scale and revokes its blob URL on close`, async (context) => {
  const bytes = new Uint8Array([137, 80, 78, 71]);
  const reference = { schema_version: "vtt.scene_map_asset.v1", asset_id: "private-map", media_type: "image/png", content_path: "/api/v1/map-assets/private-map/content.png", sha256: createHash("sha256").update(bytes).digest("hex"), alt_text: "Private coastline" };
  const scene = { schema_version: "vtt.scene_record.v1", scene_id: "coast", map_metadata: {
    schema_version: "vtt.scene_map_metadata.v1", name: "Private Coast", width_px: 800, height_px: 600, grid_size_px: 70, gridless: topology === "gridless",
    calibration: { schema_version: "vtt.board_calibration.v1", topology, origin_x_px: 0, origin_y_px: 0, cell_extent_px: 70, distance_ft: 5 }, asset: reference,
  } };
  const revoked: string[] = [];
  const originalRevoke = URL.revokeObjectURL;
  URL.revokeObjectURL = (url) => { revoked.push(url); originalRevoke(url); };
  context.after(() => { URL.revokeObjectURL = originalRevoke; });
  const { root, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard());
    if (call.path.endsWith("/launch")) return json(worldLaunch());
    if (call.path.endsWith("/return")) return new Response(null, { status: 204 });
    if (call.url.endsWith("/api/v1/scenes")) return json({ schema_version: "vtt.scene_library_view.v1", table_id: privateWorld.table_id, revision: 1, active_scene_id: "coast", scenes: [{ scene, archived: false }] });
    if (call.url.endsWith(reference.content_path)) return new Response(bytes, { headers: { "content-type": reference.media_type } });
    return emptyWorkspace(call);
  }));
  await login(root);
  await click(root, /Prepare & open/);
  // WebCrypto completes outside React's initial promise chain.
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  const preview = root.findByProps({ alt: "Private coastline" });
  assert.match(preview.props.src, /^blob:/);
  assert.match(textContent(root), new RegExp(topology.replaceAll("_", " ")));
  if (topology === "gridless") {
    assert.match(textContent(root), /5 ft \/ 70 px/);
    assert.doesNotMatch(textContent(root), /ft \/ cell/);
  } else assert.match(textContent(root), /5 ft \/ cell/);
  assert.match(textContent(root), /no tactical grid or encounter is rendered/);
  const content = calls.find((call) => call.url.endsWith(reference.content_path));
  assert.equal(content?.url, `${API_BASE}/api/v1/worlds/${privateWorld.world_id}${reference.content_path}`);
  assert.equal(new Headers(content?.init.headers).get("authorization"), `Bearer ${WORLD_BEARER}`);
  const objectUrl = preview.props.src;
  await click(root, "Return to worlds");
  assert.ok(revoked.includes(objectUrl));
  assert.equal(root.findAllByType("img").length, 0);
});
}

test("mounted administrator logout clears an active workspace and aborts all private requests", async (context) => {
  const { root, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(preparationDashboard());
    if (call.path.endsWith("/launch")) return json(worldLaunch());
    if (call.path === "/logout") return new Response(null, { status: 204 });
    return emptyWorkspace(call);
  }));
  await login(root);
  await click(root, /Prepare & open/);
  await click(root, "Log out");
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive|Scene library/);
  assert.ok(calls.filter((call) => call.path.startsWith("/workspace")).every((call) => call.init.signal?.aborted));
  const logout = calls.find((call) => call.path === "/logout");
  assert.equal(new Headers(logout?.init.headers).get("authorization"), `Bearer ${BEARER}`);
});

test("mounted discovery does not invent setup, login, or a catalog before hydration", async (context) => {
  let resolve!: (response: Response) => void;
  const pending = new Promise<Response>((done) => { resolve = done; });
  const { root, calls } = await mountGate(context, () => pending);
  assert.equal(root.findAllByType("form").length, 0);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
  assert.deepEqual(calls.map((call) => call.path), [""]);
  await act(async () => { resolve(json(installation("uninitialized"))); });
  assert.equal(root.findAllByProps({ "aria-label": "Create installation administrator" }).length, 1);
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 0);
  assert.deepEqual(calls.map((call) => call.path), [""]);
});

test("mounted setup proceeds to login and authenticated dashboard without persisting secrets", async (context) => {
  const storage = observeStorage(context);
  let claimed = false;
  const authenticated = authenticatedHandler();
  const { root, renderer, calls } = await mountGate(context, (call) => {
    if (call.path === "") return json(installation(claimed ? "ready" : "uninitialized"));
    if (call.path === "/setup") {
      claimed = true;
      return json(admin, 201);
    }
    return authenticated(call);
  });
  await fill(root, "setup-claim", CLAIM);
  await fill(root, "username", admin.username);
  await fill(root, "display-name", admin.display_name);
  await fill(root, "password", PASSWORD);
  await submit(root, "Create installation administrator");
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.equal(root.findAllByProps({ id: "setup-claim" }).length, 0);
  assert.equal(root.findByProps({ id: "password" }).props.value, "");
  assert.equal(calls.filter((call) => call.path === "/worlds").length, 0);
  const setup = calls.find((call) => call.path === "/setup");
  assert.ok(setup);
  assert.equal(new Headers(setup.init.headers).get("X-VTT-Setup-Claim"), CLAIM);
  assert.deepEqual(JSON.parse(String(setup.init.body)), {
    username: admin.username, display_name: admin.display_name, password: PASSWORD,
  });

  await login(root);
  assert.match(textContent(root), /Private Moonlit Archive/);
  assert.equal(button(root, /launch/i).props.disabled, true);
  const paths = calls.map((call) => call.path);
  assert.ok(paths.indexOf("/login") < paths.indexOf("/session"));
  assert.ok(paths.indexOf("/session") < paths.indexOf("/worlds"));
  for (const call of calls.filter((entry) => ["/session", "/worlds"].includes(entry.path))) {
    assert.equal(new Headers(call.init.headers).get("authorization"), `Bearer ${BEARER}`);
  }
  for (const secret of [CLAIM, PASSWORD, BEARER]) {
    assert.equal(JSON.stringify(renderer.toJSON()).includes(secret), false);
    assert.equal(calls.some((call) => call.url.includes(secret)), false);
  }
  assert.deepEqual(storage, []);

  await click(root, "Log out");
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
  const logoutCalls = calls.filter((call) => call.path === "/logout");
  assert.equal(logoutCalls.length, 1);
  assert.equal(new Headers(logoutCalls[0].init.headers).get("authorization"), `Bearer ${BEARER}`);
  assert.deepEqual(storage, []);
});

test("mounted safe mode exposes no authentication form or world actions", async (context) => {
  const { root, calls } = await mountGate(context, () => json(installation("safe_mode")));
  assert.match(textContent(root), /safe mode/i);
  assert.equal(root.findAllByType("form").length, 0);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
  assert.deepEqual(calls.map((call) => call.path), [""]);
});

test("mounted failed discovery stays unavailable until an explicit successful retry", async (context) => {
  let count = 0;
  const { root, calls } = await mountGate(context, () => {
    count += 1;
    if (count === 1) throw new TypeError("offline");
    return json(installation("ready"));
  });
  assert.equal(root.findAllByType("form").length, 0);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
  await click(root, /retry/i);
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.deepEqual(calls.map((call) => call.path), ["", ""]);
});

test("mounted login rejection clears the password and never requests a private catalog", async (context) => {
  const { root, calls } = await mountGate(context, (call) => {
    if (call.path === "") return json(installation("ready"));
    if (call.path === "/login") return apiError(401, "authentication_required");
    throw new Error(`Unexpected request ${call.path}`);
  });
  await login(root);
  assert.equal(root.findByProps({ id: "password" }).props.value, "");
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.ok(root.findAllByProps({ role: "alert" }).length > 0);
  assert.equal(calls.some((call) => ["/worlds", "/session"].includes(call.path)), false);
});

test("mounted dashboard hydration cannot fabricate an empty catalog on failure", async (context) => {
  const { root } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") throw new TypeError("catalog unavailable");
    throw new Error(`Unexpected request ${call.path}`);
  }));
  await login(root);
  assert.equal(root.findAllByProps({ "aria-label": "Create world" }).length, 0);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive|No worlds yet/);
  assert.ok(root.findAllByProps({ role: "alert" }).length > 0);
});

test("mounted unauthorized world mutation removes the private dashboard immediately", async (context) => {
  const { root, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(dashboard());
    if (call.path === "/worlds/create") return apiError(401, "authentication_required");
    throw new Error(`Unexpected request ${call.path}`);
  }));
  await login(root);
  assert.match(textContent(root), /Private Moonlit Archive/);
  await fill(root, "world-name", "Another World");
  await submit(root, "Create world");
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
  assert.equal(root.findAllByProps({ "aria-label": "Create world" }).length, 0);
  assert.equal(calls.filter((call) => call.path === "/worlds/create").length, 1);
});

test("mounted uncertain create retries exactly the same command instead of duplicating a world", async (context) => {
  const commands: Record<string, unknown>[] = [];
  const createdWorld = { ...privateWorld, name: "A New World" };
  const { root } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(dashboard([], 0));
    if (call.path !== "/worlds/create") throw new Error(`Unexpected request ${call.path}`);
    const command = JSON.parse(String(call.init.body)) as Record<string, unknown>;
    commands.push(command);
    if (commands.length === 1) throw new TypeError("response was lost after commit");
    return json({
      schema_version: "vtt.world_dashboard_mutation.v1",
      replayed: true,
      receipt: {
        schema_version: "vtt.world_catalog_receipt.v1", command_id: command.command_id, revision: 1,
        event: {
          schema_version: "vtt.world_catalog_event.v1", event_type: "created",
          event_id: "event_create", command_id: command.command_id, sequence: 1, revision: 1,
          world: createdWorld,
        },
      },
      dashboard: dashboard([{ world: createdWorld, archived: false }]),
    });
  }));
  await login(root);
  await fill(root, "world-name", "A New World");
  await submit(root, "Create world");
  assert.equal(commands.length, 1);
  await click(root, /retry/i);
  assert.equal(commands.length, 2);
  assert.deepEqual(commands[1], commands[0]);
  assert.equal(commands[0].expected_revision, 0);
  assert.equal(commands[0].name, "A New World");
  assert.match(textContent(root), /A New World/);
  assert.equal(button(root, /launch/i).props.disabled, true);
});

test("mounted logout aborts pending hydration and ignores its late private response", async (context) => {
  let resolveWorlds!: (response: Response) => void;
  let hydrationSignal: AbortSignal | null | undefined;
  const pendingWorlds = new Promise<Response>((resolve) => { resolveWorlds = resolve; });
  const { root, calls } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") {
      hydrationSignal = call.init.signal;
      return pendingWorlds;
    }
    if (call.path === "/logout") return new Response(null, { status: 204 });
    throw new Error(`Unexpected request ${call.path}`);
  }));
  await fill(root, "username", admin.username);
  await fill(root, "password", PASSWORD);
  await act(async () => {
    void root.findByProps({ "aria-label": "Administrator login" }).props.onSubmit({ preventDefault() {} });
  });
  assert.equal(calls.filter((call) => call.path === "/worlds").length, 1);
  assert.equal(root.findAllByProps({ "aria-label": "Create world" }).length, 0);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
  await click(root, "Log out");
  assert.equal(hydrationSignal?.aborted, true);
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  await act(async () => { resolveWorlds(json(dashboard())); });
  assert.equal(root.findAllByProps({ "aria-label": "Administrator login" }).length, 1);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
});

test("mounted revision conflict reloads the catalog before a new command can be submitted", async (context) => {
  let reads = 0;
  const commands: Record<string, unknown>[] = [];
  const changedWorld = { ...privateWorld, name: "World Changed Elsewhere" };
  const { root } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") {
      reads += 1;
      return json(reads === 1 ? dashboard() : dashboard([{ world: changedWorld, archived: false }], 2));
    }
    if (call.path === "/worlds/create") {
      commands.push(JSON.parse(String(call.init.body)) as Record<string, unknown>);
      return commands.length === 1
        ? apiError(409, "world_revision_conflict")
        : apiError(422, "invalid_request");
    }
    throw new Error(`Unexpected request ${call.path}`);
  }));
  await login(root);
  await fill(root, "world-name", "A New World");
  await submit(root, "Create world");
  assert.equal(reads, 2);
  assert.match(textContent(root), /World Changed Elsewhere/);
  assert.doesNotMatch(textContent(root), /Private Moonlit Archive/);
  assert.equal(commands.length, 1);
  await submit(root, "Create world");
  assert.equal(commands.length, 2);
  assert.equal(commands[0].expected_revision, 1);
  assert.equal(commands[1].expected_revision, 2);
  assert.notEqual(commands[0].command_id, commands[1].command_id);
});

test("mounted rename preserves world identity and archive requires explicit confirmation", async (context) => {
  let current = dashboard();
  const mutations: { path: string; command: Record<string, unknown> }[] = [];
  const revisedWorld = { ...privateWorld, name: "Revised Moonlit Archive" };
  const { root } = await mountGate(context, authenticatedHandler((call) => {
    if (call.path === "/worlds") return json(current);
    const command = JSON.parse(String(call.init.body)) as Record<string, unknown>;
    mutations.push({ path: call.path, command });
    const revision = Number(command.expected_revision) + 1;
    const base = {
      schema_version: "vtt.world_catalog_event.v1", event_id: `event_${revision}`,
      command_id: command.command_id, revision, sequence: revision, world_id: command.world_id,
    };
    const event = call.path === "/worlds/rename"
      ? { ...base, event_type: "renamed", old_name: privateWorld.name, new_name: revisedWorld.name }
      : { ...base, event_type: "archived" };
    current = dashboard([{ world: revisedWorld, archived: call.path === "/worlds/archive" }], revision);
    return json({
      schema_version: "vtt.world_dashboard_mutation.v1", replayed: false, dashboard: current,
      receipt: { schema_version: "vtt.world_catalog_receipt.v1", command_id: command.command_id, revision, event },
    });
  }));
  await login(root);
  await click(root, `Rename ${privateWorld.name}`);
  await fill(root, "rename-world-name", revisedWorld.name);
  await submit(root, "Rename world");
  assert.equal(mutations.length, 1);
  assert.equal(mutations[0].path, "/worlds/rename");
  assert.equal(mutations[0].command.world_id, privateWorld.world_id);
  assert.equal(mutations[0].command.expected_revision, 1);
  assert.match(textContent(root), /Revised Moonlit Archive/);
  await click(root, `Archive ${revisedWorld.name}`);
  assert.equal(mutations.length, 1);
  assert.match(textContent(root), /retain|permanent|cannot.*undo|irreversible/i);
  await click(root, "Confirm archive");
  assert.equal(mutations.length, 2);
  assert.equal(mutations[1].path, "/worlds/archive");
  assert.equal(mutations[1].command.world_id, privateWorld.world_id);
  assert.equal(mutations[1].command.expected_revision, 2);
  assert.match(textContent(root), /Revised Moonlit Archive/);
  assert.match(textContent(root), /Archived — retained, cannot launch/);
  assert.equal(root.findAllByProps({ "aria-label": `Rename ${revisedWorld.name}` }).length, 0);
  assert.equal(root.findAllByProps({ "aria-label": `Archive ${revisedWorld.name}` }).length, 0);
  assert.equal(button(root, /launch/i).props.disabled, true);
});
