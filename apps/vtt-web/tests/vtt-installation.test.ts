import assert from "node:assert/strict";
import test from "node:test";

import {
  InstallationApi,
  InstallationApiError,
  parseAdminPublic,
  parseInstallationView,
  parseInstallationLogin,
  parseInstallationSession,
  parseWorldDashboard,
  parseWorldDashboardMutation,
} from "../app/vtt-installation";

const admin = {
  schema_version: "vtt.admin_public.v1",
  admin_id: "adm_abc",
  username: "keeper",
  display_name: "The Keeper",
  created_at: 1,
};
const session = {
  schema_version: "vtt.admin_session_public.v1",
  session_id: "ses_abc",
  admin_id: "adm_abc",
  issued_at: 2,
  expires_at: 9999999999,
  revoked: false,
};
const world = {
  schema_version: "vtt.world_record.v1",
  world_id: "world-a",
  table_id: "table-a",
  system_id: "dnd5e",
  name: "The Echo Vault",
};
const dashboard = {
  schema_version: "vtt.world_dashboard.v1",
  catalog: {
    schema_version: "vtt.world_catalog_view.v1",
    revision: 1,
    worlds: [{ world, archived: false }],
  },
  launch_supported: false,
  launch_unavailable_reason: "world_provisioning_not_implemented",
};
const receipt = {
  schema_version: "vtt.world_catalog_receipt.v1",
  command_id: "cmd-a",
  revision: 1,
  event: {
    schema_version: "vtt.world_catalog_event.v1",
    event_id: "event-a",
    command_id: "cmd-a",
    revision: 1,
    sequence: 1,
    event_type: "created",
    world,
  },
};

test("installation codec enforces state integrity and exact secret-free schemas", () => {
  const ready = {
    schema_version: "vtt.installation_view.v1",
    state: "ready",
    revision: 1,
    setup_claimed: true,
    active_admin_count: 1,
    integrity_status: "verified",
  };
  assert.deepEqual(parseInstallationView(ready), ready);
  for (const invalid of [
    { ...ready, schema_version: "vtt.installation_view.v2" },
    { ...ready, revision: -1 },
    { ...ready, revision: 1.5 },
    { ...ready, revision: Number.MAX_SAFE_INTEGER + 1 },
    { ...ready, active_admin_count: 0 },
    { ...ready, setup_claimed: 1 },
    { ...ready, integrity_status: "failed" },
    { ...ready, bootstrap_claim: "secret" },
    { ...ready, state: "safe_mode" },
  ])
    assert.throws(() => parseInstallationView(invalid));
  assert.equal(
    parseInstallationView({
      ...ready,
      state: "safe_mode",
      setup_claimed: null,
      active_admin_count: null,
      integrity_status: "failed",
    }).state,
    "safe_mode",
  );
  assert.throws(() => parseAdminPublic({ ...admin, admin_id: "not-an-admin" }));
  assert.throws(() => parseAdminPublic({ ...admin, username: " keeper" }));
  assert.throws(() => parseAdminPublic({ ...admin, display_name: "Ｋeeper" }));
  assert.throws(() =>
    parseAdminPublic({ ...admin, display_name: "Keeper\u200b" }),
  );
  assert.throws(() =>
    parseAdminPublic({ ...admin, password: "do not expose" }),
  );
});

test("login and session codecs reject identity disagreement, expired lifetime and invalid credentials", () => {
  const login = {
    schema_version: "vtt.installation_login.v1",
    admin,
    session,
    bearer_token: "opaque_token-abc",
  };
  assert.deepEqual(parseInstallationLogin(login), login);
  const view = {
    schema_version: "vtt.installation_session.v1",
    admin,
    session,
  };
  assert.deepEqual(parseInstallationSession(view), view);
  for (const invalid of [
    { ...login, session: { ...session, admin_id: "adm_other" } },
    { ...login, session: { ...session, expires_at: session.issued_at } },
    { ...login, session: { ...session, revoked: true } },
    { ...login, session: { ...session, revoked: "false" } },
    { ...login, bearer_token: " token " },
    { ...login, bearer_token: "a\nb" },
    { ...login, bearer_token: "" },
    { ...login, password: "secret" },
  ])
    assert.throws(() => parseInstallationLogin(invalid));
  assert.throws(() =>
    parseInstallationSession({ ...view, bearer_token: "secret" }),
  );
});

test("world dashboard codec enforces bounds, identities, names, ordering and unavailable launch", () => {
  assert.deepEqual(parseWorldDashboard(dashboard), dashboard);
  for (const invalid of [
    { ...dashboard, launch_supported: true },
    { ...dashboard, launch_unavailable_reason: "ready" },
    { ...dashboard, catalog: { ...dashboard.catalog, worlds: null } },
    {
      ...dashboard,
      catalog: { ...dashboard.catalog, worlds: [{ world, archived: 0 }] },
    },
    {
      ...dashboard,
      catalog: {
        ...dashboard.catalog,
        worlds: [
          { world: { ...world, world_id: "../secret" }, archived: false },
        ],
      },
    },
    {
      ...dashboard,
      catalog: {
        ...dashboard.catalog,
        worlds: [{ world: { ...world, name: " " }, archived: false }],
      },
    },
    {
      ...dashboard,
      catalog: {
        ...dashboard.catalog,
        worlds: [{ world: { ...world, name: "bad\nname" }, archived: false }],
      },
    },
    {
      ...dashboard,
      catalog: {
        ...dashboard.catalog,
        worlds: [{ world: { ...world, system_id: "other" }, archived: false }],
      },
    },
    {
      ...dashboard,
      catalog: {
        ...dashboard.catalog,
        worlds: [dashboard.catalog.worlds[0], dashboard.catalog.worlds[0]],
      },
    },
  ])
    assert.throws(() => parseWorldDashboard(invalid));
  const entry = (id: string, name: string, table = `table-${id}`) => ({
    world: { ...world, world_id: id, table_id: table, name },
    archived: false,
  });
  for (const worlds of [
    [entry("b", "B"), entry("a", "A")],
    [entry("a", "A", "same"), entry("b", "B", "same")],
    [entry("a", "Straße"), entry("b", "STRASSE")],
    [entry("a", "Fullwidth"), entry("b", "Ｆullwidth")],
    Array.from({ length: 129 }, (_, i) =>
      entry(`w${String(i).padStart(3, "0")}`, `World ${i}`),
    ),
  ])
    assert.throws(() =>
      parseWorldDashboard({
        ...dashboard,
        catalog: { ...dashboard.catalog, worlds },
      }),
    );
});

test("mutation codec verifies receipt identity and dashboard revision", () => {
  const mutation = {
    schema_version: "vtt.world_dashboard_mutation.v1",
    receipt,
    replayed: false,
    dashboard,
  };
  assert.deepEqual(parseWorldDashboardMutation(mutation), mutation);
  for (const invalid of [
    { ...mutation, replayed: 1 },
    { ...mutation, receipt: { ...receipt, command_id: "different" } },
    {
      ...mutation,
      receipt: { ...receipt, event: { ...receipt.event, sequence: 2 } },
    },
    {
      ...mutation,
      dashboard: {
        ...dashboard,
        catalog: { ...dashboard.catalog, revision: 0 },
      },
    },
  ])
    assert.throws(() => parseWorldDashboardMutation(invalid));
});

test("installation transport uses dedicated origin, no-store and header-only secrets", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const api = new InstallationApi(
    "http://installation.test/",
    async (input, init) => {
      calls.push({ url: String(input), init: init! });
      return new Response(JSON.stringify(admin), { status: 201 });
    },
  );
  await api.setup(
    { username: "keeper", display_name: "Keeper", password: "long-password" },
    "secret-claim",
    new AbortController().signal,
  );
  assert.equal(
    calls[0].url,
    "http://installation.test/api/v1/installation/setup",
  );
  assert.equal(
    new Headers(calls[0].init.headers).get("X-VTT-Setup-Claim"),
    "secret-claim",
  );
  assert.equal(calls[0].init.cache, "no-store");
  assert.equal(calls[0].init.credentials, "omit");
  assert.equal(
    JSON.parse(String(calls[0].init.body)).bootstrap_claim,
    undefined,
  );
  assert.equal(calls[0].url.includes("secret"), false);
});

test("transport preserves unauthorized status even when an error envelope is malformed", async () => {
  const api = new InstallationApi(
    "http://installation.test",
    async () => new Response("not JSON", { status: 401 }),
  );
  await assert.rejects(
    api.worlds("token", new AbortController().signal),
    (error: unknown) =>
      error instanceof InstallationApiError && error.status === 401,
  );
});
