import assert from "node:assert/strict";
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
    assert.ok(url.startsWith(API_ROOT), `Unexpected service request: ${url}`);
    const call = { path: url.slice(API_ROOT.length), url, method: init.method ?? "GET", init };
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
