/** Strict, secret-free public projections and a dedicated installation transport.
 * Bearers are returned only to the caller; this module never persists credentials.
 */

export interface InstallationView {
  schema_version: "vtt.installation_view.v1";
  state: "uninitialized" | "ready" | "safe_mode";
  revision: number;
  setup_claimed: boolean | null;
  active_admin_count: number | null;
  integrity_status: "verified" | "failed";
}

export interface AdminPublic {
  schema_version: "vtt.admin_public.v1";
  admin_id: string;
  username: string;
  display_name: string;
  created_at: number;
}

export interface SessionPublic {
  schema_version: "vtt.admin_session_public.v1";
  session_id: string;
  admin_id: string;
  issued_at: number;
  expires_at: number;
  revoked: boolean;
}

export interface InstallationSession {
  schema_version: "vtt.installation_session.v1";
  admin: AdminPublic;
  session: SessionPublic;
}

export interface InstallationLogin {
  schema_version: "vtt.installation_login.v1";
  admin: AdminPublic;
  session: SessionPublic;
  bearer_token: string;
}

export interface WorldRecord {
  schema_version: "vtt.world_record.v1";
  world_id: string;
  name: string;
  system_id: "dnd5e";
  table_id: string;
}

export interface WorldCatalogEntry {
  world: WorldRecord;
  archived: boolean;
}
export interface WorldCatalogView {
  schema_version: "vtt.world_catalog_view.v1";
  revision: number;
  worlds: WorldCatalogEntry[];
}
export interface WorldDashboard {
  schema_version: "vtt.world_dashboard.v1";
  catalog: WorldCatalogView;
  launch_supported: false;
  launch_unavailable_reason: "world_provisioning_not_implemented";
}

interface WorldEventBase {
  schema_version: "vtt.world_catalog_event.v1";
  event_id: string;
  sequence: number;
  revision: number;
  command_id: string;
}
export type WorldMutationEvent = WorldEventBase &
  (
    | { event_type: "created"; world: WorldRecord }
    | {
        event_type: "renamed";
        world_id: string;
        old_name: string;
        new_name: string;
      }
    | { event_type: "archived"; world_id: string }
  );
export interface WorldMutationReceipt {
  schema_version: "vtt.world_catalog_receipt.v1";
  command_id: string;
  revision: number;
  event: WorldMutationEvent;
}
export interface WorldDashboardMutation {
  schema_version: "vtt.world_dashboard_mutation.v1";
  receipt: WorldMutationReceipt;
  replayed: boolean;
  dashboard: WorldDashboard;
}

export type WorldCommand =
  | {
      kind: "create";
      command_id: string;
      expected_revision: number;
      name: string;
    }
  | {
      kind: "rename";
      command_id: string;
      expected_revision: number;
      world_id: string;
      name: string;
    }
  | {
      kind: "archive";
      command_id: string;
      expected_revision: number;
      world_id: string;
    };

function invalid(): never {
  throw new Error("The installation service returned an invalid response.");
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function exact(value: unknown, keys: string[]): Record<string, unknown> {
  const object = record(value);
  if (
    Object.keys(object).length !== keys.length ||
    keys.some((key) => !Object.hasOwn(object, key))
  )
    invalid();
  return object;
}
function literal<T extends string | boolean>(value: unknown, expected: T): T {
  if (value !== expected) invalid();
  return expected;
}
function integer(value: unknown, minimum = 0): number {
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  )
    invalid();
  return value;
}
function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") invalid();
  return value;
}
function humanText(
  value: unknown,
  minimum: number,
  maximum: number,
  canonical = true,
): string {
  if (typeof value !== "string" || value !== value.trim()) invalid();
  const length = [...value].length;
  if (length < minimum || length > maximum) invalid();
  if (
    canonical
      ? value.normalize("NFKC") !== value || /\p{C}/u.test(value)
      : /[\p{Cc}\p{Cs}]/u.test(value)
  )
    invalid();
  return value;
}
function identity(value: unknown, prefix = ""): string {
  const text = humanText(value, 1, 128);
  if (
    !(
      prefix
        ? new RegExp(`^${prefix}[A-Za-z0-9_-]+$`)
        : /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/
    ).test(text)
  )
    invalid();
  return text;
}
function worldName(value: unknown): string {
  return humanText(value, 1, 160, false);
}

export function parseInstallationView(value: unknown): InstallationView {
  const item = exact(value, [
    "schema_version",
    "state",
    "revision",
    "setup_claimed",
    "active_admin_count",
    "integrity_status",
  ]);
  const schema_version = literal(
    item.schema_version,
    "vtt.installation_view.v1",
  );
  const revision = integer(item.revision);
  if (item.state === "safe_mode") {
    if (
      item.setup_claimed !== null ||
      item.active_admin_count !== null ||
      item.integrity_status !== "failed"
    )
      invalid();
    return {
      schema_version,
      revision,
      state: "safe_mode",
      setup_claimed: null,
      active_admin_count: null,
      integrity_status: "failed",
    };
  }
  if (item.state !== "ready" && item.state !== "uninitialized") invalid();
  const setup_claimed = boolean(item.setup_claimed);
  const active_admin_count = integer(item.active_admin_count);
  const integrity_status = literal(item.integrity_status, "verified");
  if (
    item.state === "ready"
      ? !setup_claimed || active_admin_count < 1
      : setup_claimed || active_admin_count !== 0
  )
    invalid();
  return {
    schema_version,
    state: item.state,
    revision,
    setup_claimed,
    active_admin_count,
    integrity_status,
  };
}

export function parseAdminPublic(value: unknown): AdminPublic {
  const item = exact(value, [
    "schema_version",
    "admin_id",
    "username",
    "display_name",
    "created_at",
  ]);
  return {
    schema_version: literal(item.schema_version, "vtt.admin_public.v1"),
    admin_id: identity(item.admin_id, "adm_"),
    username: humanText(item.username, 3, 64),
    display_name: humanText(item.display_name, 1, 80),
    created_at: integer(item.created_at),
  };
}

export function parseSessionPublic(value: unknown): SessionPublic {
  const item = exact(value, [
    "schema_version",
    "session_id",
    "admin_id",
    "issued_at",
    "expires_at",
    "revoked",
  ]);
  const issued_at = integer(item.issued_at);
  const expires_at = integer(item.expires_at, 1);
  if (expires_at <= issued_at) invalid();
  return {
    schema_version: literal(item.schema_version, "vtt.admin_session_public.v1"),
    session_id: identity(item.session_id, "ses_"),
    admin_id: identity(item.admin_id, "adm_"),
    issued_at,
    expires_at,
    revoked: boolean(item.revoked),
  };
}

function authenticatedIdentity(item: Record<string, unknown>) {
  const admin = parseAdminPublic(item.admin);
  const session = parseSessionPublic(item.session);
  if (admin.admin_id !== session.admin_id || session.revoked) invalid();
  return { admin, session };
}

export function parseInstallationLogin(value: unknown): InstallationLogin {
  const item = exact(value, [
    "schema_version",
    "admin",
    "session",
    "bearer_token",
  ]);
  const bearer_token = humanText(item.bearer_token, 1, 256);
  if (!/^[A-Za-z0-9_-]+$/.test(bearer_token)) invalid();
  return {
    schema_version: literal(item.schema_version, "vtt.installation_login.v1"),
    ...authenticatedIdentity(item),
    bearer_token,
  };
}

export function parseInstallationSession(value: unknown): InstallationSession {
  const item = exact(value, ["schema_version", "admin", "session"]);
  return {
    schema_version: literal(item.schema_version, "vtt.installation_session.v1"),
    ...authenticatedIdentity(item),
  };
}

export function parseWorldRecord(value: unknown): WorldRecord {
  const item = exact(value, [
    "schema_version",
    "world_id",
    "name",
    "system_id",
    "table_id",
  ]);
  return {
    schema_version: literal(item.schema_version, "vtt.world_record.v1"),
    world_id: identity(item.world_id),
    table_id: identity(item.table_id),
    name: worldName(item.name),
    system_id: literal(item.system_id, "dnd5e"),
  };
}

// Caseless equivalence includes expansions (ß → ss) and final sigma. Preserve
// dotless i: unlike ordinary upper/lower conversion, Unicode casefold keeps it.
function worldNameKey(value: string): string {
  return [...value.normalize("NFKC")]
    .map((character) =>
      character === "ı"
        ? character
        : character === "ẞ"
          ? "ss"
          : character.toUpperCase().toLowerCase(),
    )
    .join("");
}

export function parseWorldCatalog(value: unknown): WorldCatalogView {
  const item = exact(value, ["schema_version", "revision", "worlds"]);
  const schema_version = literal(
    item.schema_version,
    "vtt.world_catalog_view.v1",
  );
  const revision = integer(item.revision);
  if (!Array.isArray(item.worlds) || item.worlds.length > 1024) invalid();
  const worlds = item.worlds.map((entry) => {
    const parsed = exact(entry, ["world", "archived"]);
    return {
      world: parseWorldRecord(parsed.world),
      archived: boolean(parsed.archived),
    };
  });
  const tables = new Set<string>();
  const names = new Set<string>();
  let previousId = "";
  for (const entry of worlds) {
    if (entry.world.world_id <= previousId || tables.has(entry.world.table_id))
      invalid();
    previousId = entry.world.world_id;
    tables.add(entry.world.table_id);
    if (!entry.archived) {
      const key = worldNameKey(entry.world.name);
      if (names.has(key)) invalid();
      names.add(key);
    }
  }
  if (names.size > 128) invalid();
  return { schema_version, revision, worlds };
}

export function parseWorldDashboard(value: unknown): WorldDashboard {
  const item = exact(value, [
    "schema_version",
    "catalog",
    "launch_supported",
    "launch_unavailable_reason",
  ]);
  return {
    schema_version: literal(item.schema_version, "vtt.world_dashboard.v1"),
    catalog: parseWorldCatalog(item.catalog),
    launch_supported: literal(item.launch_supported, false),
    launch_unavailable_reason: literal(
      item.launch_unavailable_reason,
      "world_provisioning_not_implemented",
    ),
  };
}

export function parseWorldMutationReceipt(
  value: unknown,
): WorldMutationReceipt {
  const item = exact(value, [
    "schema_version",
    "command_id",
    "revision",
    "event",
  ]);
  const rawEvent = record(item.event);
  const baseKeys = [
    "schema_version",
    "event_id",
    "sequence",
    "revision",
    "command_id",
    "event_type",
  ];
  const eventType = rawEvent.event_type;
  exact(rawEvent, [
    ...baseKeys,
    ...(eventType === "created"
      ? ["world"]
      : eventType === "renamed"
        ? ["world_id", "old_name", "new_name"]
        : eventType === "archived"
          ? ["world_id"]
          : invalid()),
  ]);
  const base: WorldEventBase = {
    schema_version: literal(
      rawEvent.schema_version,
      "vtt.world_catalog_event.v1",
    ),
    event_id: identity(rawEvent.event_id),
    command_id: identity(rawEvent.command_id),
    sequence: integer(rawEvent.sequence, 1),
    revision: integer(rawEvent.revision, 1),
  };
  if (base.sequence !== base.revision) invalid();
  let event: WorldMutationEvent;
  if (eventType === "created")
    event = {
      ...base,
      event_type: eventType,
      world: parseWorldRecord(rawEvent.world),
    };
  else if (eventType === "renamed") {
    const old_name = worldName(rawEvent.old_name);
    const new_name = worldName(rawEvent.new_name);
    if (old_name === new_name) invalid();
    event = {
      ...base,
      event_type: eventType,
      world_id: identity(rawEvent.world_id),
      old_name,
      new_name,
    };
  } else
    event = {
      ...base,
      event_type: "archived",
      world_id: identity(rawEvent.world_id),
    };
  const command_id = identity(item.command_id);
  const revision = integer(item.revision, 1);
  if (command_id !== event.command_id || revision !== event.revision) invalid();
  return {
    schema_version: literal(
      item.schema_version,
      "vtt.world_catalog_receipt.v1",
    ),
    command_id,
    revision,
    event,
  };
}

export function parseWorldDashboardMutation(
  value: unknown,
): WorldDashboardMutation {
  const item = exact(value, [
    "schema_version",
    "receipt",
    "replayed",
    "dashboard",
  ]);
  const receipt = parseWorldMutationReceipt(item.receipt);
  const dashboard = parseWorldDashboard(item.dashboard);
  if (dashboard.catalog.revision < receipt.revision) invalid();
  return {
    schema_version: literal(
      item.schema_version,
      "vtt.world_dashboard_mutation.v1",
    ),
    receipt,
    dashboard,
    replayed: boolean(item.replayed),
  };
}

export class InstallationApiError extends Error {
  constructor(
    public readonly status: number | null,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "InstallationApiError";
  }
}

function errorForStatus(status: number): string {
  if (status === 401)
    return "Your credentials were not accepted. Please sign in again.";
  if (status === 409)
    return "The world catalog changed. Refresh it before trying again.";
  if (status === 422) return "Check the form values and try again.";
  if (status === 429)
    return "Too many attempts. Wait a minute before trying again.";
  if (status === 503)
    return "The installation service is unavailable. Please try again.";
  return "The installation service could not complete this request.";
}

export class InstallationApi {
  private readonly baseUrl: string;
  constructor(
    baseUrl = process.env.NEXT_PUBLIC_VTT_INSTALLATION_API_BASE_URL ??
      "http://127.0.0.1:8001",
    private readonly fetcher: typeof fetch = (...args) => fetch(...args),
  ) {
    const url = new URL(baseUrl);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    )
      throw new Error("Invalid installation API origin.");
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  private async request<T>(
    path: string,
    parser: ((value: unknown) => T) | null,
    signal: AbortSignal,
    options: {
      token?: string;
      claim?: string;
      body?: unknown;
      method?: string;
      expectedStatus?: number;
    } = {},
  ): Promise<T> {
    const headers = new Headers({ Accept: "application/json" });
    if (options.token) headers.set("Authorization", `Bearer ${options.token}`);
    if (options.claim) headers.set("X-VTT-Setup-Claim", options.claim);
    if (options.body !== undefined)
      headers.set("Content-Type", "application/json");
    let response: Response;
    try {
      response = await this.fetcher(
        `${this.baseUrl}/api/v1/installation${path}`,
        {
          method: options.method ?? "GET",
          headers,
          signal,
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
          ...(options.body !== undefined
            ? { body: JSON.stringify(options.body) }
            : {}),
        },
      );
    } catch (error) {
      if (signal.aborted) throw error;
      throw new InstallationApiError(
        null,
        "connection_unavailable",
        "Cannot reach the installation service. Check that it is running, then retry.",
      );
    }
    if (!response.ok) {
      let code = "request_failed";
      try {
        const envelope = exact(await response.json(), [
          "schema_version",
          "code",
          "message",
          "details",
        ]);
        literal(envelope.schema_version, "vtt.error.v1");
        humanText(envelope.message, 1, 2048, false);
        record(envelope.details);
        code = identity(envelope.code);
      } catch {
        /* Preserve the HTTP status even when the error body is unsafe. */
      }
      // Error prose is local: never echo arbitrary request inputs or server secrets.
      throw new InstallationApiError(
        response.status,
        code,
        code === "storage_unavailable"
          ? "World storage is unavailable. Existing records have not been replaced or initialized."
          : code === "installation_safe_mode"
            ? "Installation safe mode is active. Changes are disabled."
            : errorForStatus(response.status),
      );
    }
    if (response.status !== (options.expectedStatus ?? 200))
      throw new InstallationApiError(
        null,
        "invalid_response",
        "The installation service returned an unexpected response.",
      );
    if (!parser) return undefined as T;
    try {
      return parser(await response.json());
    } catch {
      throw new InstallationApiError(
        null,
        "invalid_response",
        "The installation service returned an invalid response. No unverified data was loaded.",
      );
    }
  }

  view(signal: AbortSignal) {
    return this.request("", parseInstallationView, signal);
  }
  setup(
    admin: { username: string; display_name: string; password: string },
    claim: string,
    signal: AbortSignal,
  ) {
    return this.request("/setup", parseAdminPublic, signal, {
      claim,
      body: admin,
      method: "POST",
      expectedStatus: 201,
    });
  }
  login(username: string, password: string, signal: AbortSignal) {
    return this.request("/login", parseInstallationLogin, signal, {
      body: { username, password },
      method: "POST",
    });
  }
  session(token: string, signal: AbortSignal) {
    return this.request("/session", parseInstallationSession, signal, {
      token,
    });
  }
  logout(token: string, signal: AbortSignal) {
    return this.request<void>("/logout", null, signal, {
      token,
      method: "POST",
      expectedStatus: 204,
    });
  }
  worlds(token: string, signal: AbortSignal) {
    return this.request("/worlds", parseWorldDashboard, signal, { token });
  }
  async mutate(token: string, command: WorldCommand, signal: AbortSignal) {
    const { kind, ...body } = command;
    const result = await this.request(
      `/worlds/${kind}`,
      parseWorldDashboardMutation,
      signal,
      { token, body, method: "POST" },
    );
    const event = result.receipt.event;
    const expectedType = {
      create: "created",
      rename: "renamed",
      archive: "archived",
    }[kind];
    if (
      result.receipt.command_id !== command.command_id ||
      event.event_type !== expectedType ||
      result.receipt.revision !== command.expected_revision + 1 ||
      (kind !== "create" &&
        "world_id" in event &&
        event.world_id !== command.world_id) ||
      (kind === "create" &&
        event.event_type === "created" &&
        event.world.name !== command.name) ||
      (kind === "rename" &&
        event.event_type === "renamed" &&
        event.new_name !== command.name)
    ) {
      throw new InstallationApiError(
        null,
        "invalid_response",
        "The service returned a receipt for a different command. Retry to confirm the original operation.",
      );
    }
    return result;
  }
}
