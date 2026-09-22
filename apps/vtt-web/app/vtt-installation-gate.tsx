"use client";

/* eslint-disable @next/next/no-html-link-for-pages -- Full document navigation intentionally ends the in-memory administrator session at the demo boundary. */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  InstallationApi,
  InstallationApiError,
  type AdminPublic,
  type SessionPublic,
  type WorldCatalogEntry,
  type WorldCommand,
  type WorldDashboard,
} from "./vtt-installation";

type Screen =
  | { kind: "loading" | "setup" | "login" | "safe_mode" }
  | {
      kind: "unavailable";
      retry: "installation" | "dashboard";
      admin?: AdminPublic;
    }
  | { kind: "dashboard_loading"; admin: AdminPublic }
  | { kind: "dashboard"; admin: AdminPublic; dashboard: WorldDashboard };
type Credentials = {
  token: string;
  admin: AdminPublic;
  session: SessionPublic;
};
type RequestGeneration = { generation: number; controller: AbortController };
type Feedback = { message: string; error: boolean } | null;

function requestError(error: unknown): InstallationApiError {
  return error instanceof InstallationApiError
    ? error
    : new InstallationApiError(
        null,
        "connection_unavailable",
        "The installation service is unavailable. Check the connection and retry.",
      );
}

function canonicalInput(value: string, min: number, max: number): boolean {
  return (
    value === value.trim() &&
    [...value].length >= min &&
    [...value].length <= max &&
    value.normalize("NFKC") === value &&
    !/\p{C}/u.test(value)
  );
}

function validWorldName(value: string): boolean {
  return (
    value === value.trim() &&
    [...value].length > 0 &&
    [...value].length <= 160 &&
    !/[\p{Cc}\p{Cs}]/u.test(value)
  );
}

export function VttInstallationGate({ apiBaseUrl }: { apiBaseUrl?: string }) {
  const api = useMemo(() => {
    try {
      return new InstallationApi(apiBaseUrl);
    } catch {
      return null;
    }
  }, [apiBaseUrl]);
  const [screen, setScreen] = useState<Screen>({ kind: "loading" });
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [claim, setClaim] = useState("");
  const [worldName, setWorldName] = useState("");
  const [editing, setEditing] = useState<WorldCatalogEntry | null>(null);
  const [renamedWorld, setRenamedWorld] = useState("");
  const [archiving, setArchiving] = useState<WorldCatalogEntry | null>(null);
  const [retryCommand, setRetryCommand] = useState<WorldCommand | null>(null);
  const credentials = useRef<Credentials | null>(null);
  const activeRequest = useRef<RequestGeneration | null>(null);
  const generation = useRef(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const renameInput = useRef<HTMLInputElement>(null);
  const archiveConfirm = useRef<HTMLButtonElement>(null);

  const invalidate = useCallback(() => {
    generation.current += 1;
    activeRequest.current?.controller.abort();
    activeRequest.current = null;
  }, []);

  const begin = useCallback((): RequestGeneration => {
    invalidate();
    const request = {
      generation: generation.current,
      controller: new AbortController(),
    };
    activeRequest.current = request;
    return request;
  }, [invalidate]);

  const current = useCallback(
    (request: RequestGeneration): boolean =>
      generation.current === request.generation &&
      !request.controller.signal.aborted,
    [],
  );

  const clearPrivateState = useCallback(() => {
    credentials.current = null;
    setUsername("");
    setDisplayName("");
    setPassword("");
    setClaim("");
    setWorldName("");
    setEditing(null);
    setRenamedWorld("");
    setArchiving(null);
    setRetryCommand(null);
    setBusy(null);
  }, []);

  const rejectAuthentication = useCallback(
    (message = "Your session ended. Sign in again to access your worlds.") => {
      invalidate();
      clearPrivateState();
      setScreen({ kind: "login" });
      setFeedback({ message, error: true });
    },
    [invalidate, clearPrivateState],
  );

  const safeMode = useCallback(() => {
    invalidate();
    clearPrivateState();
    setScreen({ kind: "safe_mode" });
    setFeedback(null);
  }, [invalidate, clearPrivateState]);

  const discover = useCallback(async () => {
    const request = begin();
    clearPrivateState();
    setScreen({ kind: "loading" });
    setFeedback(null);
    if (!api) {
      setScreen({ kind: "unavailable", retry: "installation" });
      setFeedback({
        message:
          "The installation API address is invalid. Check NEXT_PUBLIC_VTT_INSTALLATION_API_BASE_URL.",
        error: true,
      });
      return;
    }
    try {
      const view = await api.view(request.controller.signal);
      if (!current(request)) return;
      setScreen({
        kind:
          view.state === "uninitialized"
            ? "setup"
            : view.state === "ready"
              ? "login"
              : "safe_mode",
      });
    } catch (error) {
      if (!current(request)) return;
      const failure = requestError(error);
      if (failure.status === 503 && failure.code === "installation_safe_mode") {
        safeMode();
        return;
      }
      setScreen({ kind: "unavailable", retry: "installation" });
      setFeedback({ message: failure.message, error: true });
    }
  }, [api, begin, clearPrivateState, current, safeMode]);

  useEffect(() => {
    let subscribed = true;
    queueMicrotask(() => {
      if (subscribed) void discover();
    });
    return () => {
      subscribed = false;
      invalidate();
      credentials.current = null;
    };
  }, [discover, invalidate]);

  useEffect(() => {
    heading.current?.focus();
  }, [screen.kind]);
  useEffect(() => {
    if (editing) renameInput.current?.focus();
  }, [editing]);
  useEffect(() => {
    if (archiving) archiveConfirm.current?.focus();
  }, [archiving]);

  // Remove private content at local expiry even if no further request is made.
  useEffect(() => {
    if (!("admin" in screen) || !screen.admin) return;
    const auth = credentials.current;
    if (!auth) return;
    const remaining = auth.session.expires_at * 1000 - Date.now();
    const timer = setTimeout(
      () => rejectAuthentication(),
      Math.max(0, Math.min(remaining, 2_147_483_647)),
    );
    return () => clearTimeout(timer);
  }, [screen, rejectAuthentication]);

  const hydrate = async (
    request: RequestGeneration,
    successMessage?: string,
  ) => {
    const auth = credentials.current;
    if (!api || !auth) return;
    setScreen({ kind: "dashboard_loading", admin: auth.admin });
    try {
      const verified = await api.session(auth.token, request.controller.signal);
      if (!current(request)) return;
      if (
        verified.admin.admin_id !== auth.admin.admin_id ||
        verified.session.session_id !== auth.session.session_id ||
        verified.session.expires_at * 1000 <= Date.now()
      ) {
        rejectAuthentication(
          "The administrator session could not be verified. Please sign in again.",
        );
        return;
      }
      const dashboard = await api.worlds(auth.token, request.controller.signal);
      if (!current(request)) return;
      credentials.current = { token: auth.token, ...verified };
      setScreen({ kind: "dashboard", admin: verified.admin, dashboard });
      if (successMessage)
        setFeedback({ message: successMessage, error: false });
    } catch (error) {
      if (!current(request)) return;
      const failure = requestError(error);
      if (failure.status === 401) {
        rejectAuthentication();
        return;
      }
      if (failure.status === 503 && failure.code === "installation_safe_mode") {
        safeMode();
        return;
      }
      setScreen({ kind: "unavailable", retry: "dashboard", admin: auth.admin });
      setFeedback({ message: failure.message, error: true });
    } finally {
      if (current(request)) setBusy(null);
    }
  };

  const submitAuthentication = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || !api || (screen.kind !== "setup" && screen.kind !== "login"))
      return;
    const setup = screen.kind === "setup";
    setFeedback(null);
    if (
      !canonicalInput(username, 3, 64) ||
      !canonicalInput(password, 12, 256) ||
      (setup && (!canonicalInput(displayName, 1, 80) || !claim))
    ) {
      setFeedback({
        message:
          "Use a 3–64 character username and a 12–256 character password, without surrounding spaces or unsupported characters. Setup also requires a display name and the original setup claim.",
        error: true,
      });
      setPassword("");
      setClaim("");
      return;
    }
    const request = begin();
    setBusy(setup ? "setup" : "login");
    try {
      if (setup) {
        await api.setup(
          { username, display_name: displayName, password },
          claim,
          request.controller.signal,
        );
        if (!current(request)) return;
        setScreen({ kind: "login" });
        setDisplayName("");
        setFeedback({
          message:
            "Your administrator account is ready. Sign in to manage your worlds.",
          error: false,
        });
      } else {
        const login = await api.login(
          username,
          password,
          request.controller.signal,
        );
        if (!current(request)) return;
        credentials.current = {
          token: login.bearer_token,
          admin: login.admin,
          session: login.session,
        };
        setPassword("");
        setClaim("");
        await hydrate(request);
      }
    } catch (error) {
      if (!current(request)) return;
      const failure = requestError(error);
      if (failure.status === 503 && failure.code === "installation_safe_mode") {
        safeMode();
        return;
      }
      if (failure.status === 401) {
        clearPrivateState();
        setScreen({ kind: setup ? "setup" : "login" });
        setFeedback({
          message: setup
            ? "The setup claim was not accepted. Use the original claim shown in the local server terminal."
            : "Username or password was not accepted. Please try again.",
          error: true,
        });
        return;
      }
      if (setup && failure.status === 409) {
        await discover();
        return;
      }
      setFeedback({ message: failure.message, error: true });
    } finally {
      if (current(request)) {
        setPassword("");
        setClaim("");
        setBusy(null);
      }
    }
  };

  const logout = async () => {
    const auth = credentials.current;
    const request = begin();
    clearPrivateState();
    setScreen({ kind: "login" });
    setFeedback({
      message:
        "Signed out. Your session and world catalog have been cleared from this page.",
      error: false,
    });
    if (!api || !auth) return;
    setBusy("logout");
    try {
      await api.logout(auth.token, request.controller.signal);
    } catch (error) {
      if (!current(request)) return;
      const failure = requestError(error);
      if (failure.status !== 401)
        setFeedback({
          message:
            "Signed out on this page. Server-side revocation could not be confirmed; the server session will expire automatically.",
          error: true,
        });
    } finally {
      if (current(request)) setBusy(null);
    }
  };

  const refreshDashboard = async () => {
    if (busy) return;
    setFeedback(null);
    setBusy("refresh");
    await hydrate(begin());
  };

  const execute = async (command: WorldCommand) => {
    const auth = credentials.current;
    if (!api || !auth || busy || screen.kind !== "dashboard") return;
    const request = begin();
    setBusy(command.kind);
    setFeedback(null);
    try {
      const result = await api.mutate(
        auth.token,
        command,
        request.controller.signal,
      );
      if (!current(request)) return;
      setScreen({
        kind: "dashboard",
        admin: auth.admin,
        dashboard: result.dashboard,
      });
      setRetryCommand(null);
      if (command.kind === "create") setWorldName("");
      if (command.kind === "rename") {
        setEditing(null);
        setRenamedWorld("");
      }
      if (command.kind === "archive") setArchiving(null);
      setFeedback({
        message:
          command.kind === "archive"
            ? "World archived. Its record and data are retained."
            : command.kind === "rename"
              ? "World renamed."
              : "World created. Workspace provisioning is not available yet.",
        error: false,
      });
    } catch (error) {
      if (!current(request)) return;
      const failure = requestError(error);
      if (failure.status === 401) {
        rejectAuthentication();
        return;
      }
      if (failure.status === 503 && failure.code === "installation_safe_mode") {
        safeMode();
        return;
      }
      if (failure.status === 503 && failure.code === "storage_unavailable") {
        setScreen({
          kind: "unavailable",
          retry: "dashboard",
          admin: auth.admin,
        });
        setRetryCommand(command);
        setFeedback({
          message:
            "World storage is unavailable. No catalog is shown; reconnect before confirming the original operation.",
          error: true,
        });
        return;
      }
      if (failure.status === 409) {
        setRetryCommand(null);
        await hydrate(
          request,
          "The catalog changed or the operation conflicts with an existing world. The latest catalog is loaded; review it before submitting again.",
        );
        return;
      }
      const uncertain = failure.status === null || failure.status >= 500;
      setRetryCommand(uncertain ? command : null);
      setFeedback({
        message: uncertain
          ? "The outcome could not be confirmed. Retry the same operation to check its result safely; its command identity will be preserved."
          : failure.status === 422
            ? "That world name or command was not accepted. Use 1–160 characters without surrounding spaces or control characters."
            : failure.message,
        error: true,
      });
    } finally {
      if (current(request)) setBusy(null);
    }
  };

  const submitWorld = async (
    event: FormEvent<HTMLFormElement>,
    kind: "create" | "rename",
  ) => {
    event.preventDefault();
    if (screen.kind !== "dashboard" || retryCommand || busy) return;
    const name = kind === "create" ? worldName : renamedWorld;
    if (!validWorldName(name)) {
      setFeedback({
        message:
          "World names must contain 1–160 characters, without surrounding spaces or control characters.",
        error: true,
      });
      return;
    }
    if (kind === "rename" && (!editing || editing.world.name === name)) {
      setFeedback({
        message: "Choose a different name for this world.",
        error: true,
      });
      return;
    }
    const base = {
      command_id: `cmd_${crypto.randomUUID()}`,
      expected_revision: screen.dashboard.catalog.revision,
      name,
    };
    await execute(
      kind === "create"
        ? { ...base, kind }
        : { ...base, kind, world_id: editing!.world.world_id },
    );
  };

  const confirmArchive = async () => {
    if (screen.kind !== "dashboard" || !archiving || busy || retryCommand)
      return;
    await execute({
      kind: "archive",
      command_id: `cmd_${crypto.randomUUID()}`,
      expected_revision: screen.dashboard.catalog.revision,
      world_id: archiving.world.world_id,
    });
  };

  const admin = "admin" in screen ? screen.admin : undefined;
  const dashboard = screen.kind === "dashboard" ? screen.dashboard : null;
  const activeWorlds =
    dashboard?.catalog.worlds.filter((entry) => !entry.archived) ?? [];
  const archivedWorlds =
    dashboard?.catalog.worlds.filter((entry) => entry.archived) ?? [];
  const locked = Boolean(busy || retryCommand);
  const renderWorld = (entry: WorldCatalogEntry, index: number) => (
    <article
      className={`vi-world-card${entry.archived ? " vi-world-card-archived" : ""}`}
      key={entry.world.world_id}
      aria-label={`World: ${entry.world.name}`}
    >
      <div className="vi-world-art" aria-hidden="true">
        <span>{String(index + 1).padStart(2, "0")}</span>
        <WorldMark />
      </div>
      <div className="vi-world-content">
        <div className="vi-world-meta">
          <span>D&amp;D 5E</span>
          <span className="vi-badge">
            {entry.archived ? "Archived" : "Metadata saved"}
          </span>
        </div>
        <h3>{entry.world.name}</h3>
        <p>
          {entry.archived
            ? "Archived — retained, cannot launch."
            : "Workspace provisioning is not available yet"}
        </p>
        <div className="vi-world-actions">
          <button
            type="button"
            className="vi-button vi-primary"
            disabled
            title="Workspace provisioning is not available yet"
          >
            Launch world <span aria-hidden="true">↗</span>
          </button>
          {!entry.archived && (
            <>
              <button
                type="button"
                className="vi-button vi-quiet"
                aria-label={`Rename ${entry.world.name}`}
                disabled={locked}
                onClick={() => {
                  setEditing(entry);
                  setRenamedWorld(entry.world.name);
                  setArchiving(null);
                  setFeedback(null);
                }}
              >
                Rename
              </button>
              <button
                type="button"
                className="vi-button vi-quiet vi-danger-text"
                aria-label={`Archive ${entry.world.name}`}
                disabled={locked}
                onClick={() => {
                  setArchiving(entry);
                  setEditing(null);
                  setFeedback(null);
                }}
              >
                Archive
              </button>
            </>
          )}
        </div>
      </div>
    </article>
  );

  return (
    <div className="vi-app">
      <a className="skip-link" href="#installation-main">
        Skip to installation administration
      </a>
      <header className="vi-topbar">
        <a
          className="vi-brand"
          href="/setup"
          aria-label="DND Sim installation home"
        >
          <span className="vi-brand-mark" aria-hidden="true">
            ◇
          </span>
          <span>
            DND Sim <small>WORLD ADMINISTRATION</small>
          </span>
        </a>
        <nav className="vi-topnav" aria-label="Installation navigation">
          <a href="/" className="vi-demo-link">
            Open demonstration table <span aria-hidden="true">↗</span>
          </a>
          {admin && (
            <>
              <span className="vi-admin-name">{admin.display_name}</span>
              <button
                type="button"
                className="vi-button vi-secondary"
                onClick={() => void logout()}
              >
                Log out
              </button>
            </>
          )}
        </nav>
      </header>
      <main
        id="installation-main"
        className="vi-main"
        aria-busy={
          screen.kind === "loading" || screen.kind === "dashboard_loading"
        }
      >
        <div
          className="vi-feedback"
          id="installation-feedback"
          role={feedback?.error ? "alert" : "status"}
          aria-live={feedback?.error ? "assertive" : "polite"}
        >
          {feedback && (
            <p
              className={
                feedback.error ? "vi-notice vi-notice-error" : "vi-notice"
              }
            >
              {feedback.message}
            </p>
          )}
        </div>
        {(screen.kind === "setup" || screen.kind === "login") && (
          <div className="vi-welcome-grid">
            <section className="vi-introduction">
              <p className="vi-eyebrow">YOUR TABLE. YOUR WORLDS.</p>
              <h1 ref={heading} tabIndex={-1}>
                {screen.kind === "setup" ? (
                  <>
                    Every adventure
                    <br />
                    starts somewhere.
                  </>
                ) : (
                  <>
                    A place for
                    <br />
                    your next chapter.
                  </>
                )}
              </h1>
              <p className="vi-lede">
                A private home for the worlds you imagine. Set the foundation,
                keep your campaigns organized, and make room for what comes
                next.
              </p>
              <div className="vi-intro-note">
                <WorldMark />
                <div>
                  <strong>Built around your world</strong>
                  <p>
                    Manage world records here. Play stays in the separately
                    labeled demonstration table until workspace provisioning is
                    ready.
                  </p>
                </div>
              </div>
              <p className="vi-footnote">
                Standalone installation · D&amp;D 5E
              </p>
            </section>
            <section className="vi-auth-card">
              <p className="vi-eyebrow">
                {screen.kind === "setup"
                  ? "01 / INSTALLATION SETUP"
                  : "ADMINISTRATOR ACCESS"}
              </p>
              <h2>
                {screen.kind === "setup" ? "Make it yours" : "Welcome back"}
              </h2>
              <p>
                {screen.kind === "setup"
                  ? "Create the first administrator using the one-time claim from your local server terminal."
                  : "Sign in to manage this installation’s world catalog."}
              </p>
              <form
                aria-label={
                  screen.kind === "setup"
                    ? "Create installation administrator"
                    : "Administrator login"
                }
                onSubmit={submitAuthentication}
                className="vi-form"
              >
                {screen.kind === "setup" && (
                  <label htmlFor="setup-claim">
                    Setup claim
                    <input
                      id="setup-claim"
                      name="setup_claim"
                      type="password"
                      required
                      value={claim}
                      onChange={(event) => setClaim(event.target.value)}
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      disabled={Boolean(busy)}
                      maxLength={256}
                      aria-describedby="claim-help installation-feedback"
                    />
                    <small id="claim-help">
                      Use the original claim shown when the server was first
                      created.
                    </small>
                  </label>
                )}
                <label htmlFor="username">
                  Username
                  <input
                    id="username"
                    name="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    required
                    minLength={3}
                    maxLength={64}
                    disabled={Boolean(busy)}
                    aria-describedby="installation-feedback"
                  />
                </label>
                {screen.kind === "setup" && (
                  <label htmlFor="display-name">
                    Display name
                    <input
                      id="display-name"
                      name="display_name"
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                      autoComplete="nickname"
                      required
                      maxLength={80}
                      disabled={Boolean(busy)}
                      aria-describedby="installation-feedback"
                    />
                  </label>
                )}
                <label htmlFor="password">
                  Password
                  <input
                    id="password"
                    name="password"
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete={
                      screen.kind === "setup"
                        ? "new-password"
                        : "current-password"
                    }
                    required
                    minLength={12}
                    maxLength={256}
                    disabled={Boolean(busy)}
                    aria-describedby="password-help installation-feedback"
                  />
                  <small id="password-help">
                    {screen.kind === "setup"
                      ? "At least 12 characters. No surrounding spaces."
                      : "Your administrator password, not a table credential."}
                  </small>
                </label>
                <button
                  type="submit"
                  className="vi-button vi-primary"
                  disabled={Boolean(busy)}
                >
                  {busy
                    ? busy === "setup"
                      ? "Creating administrator…"
                      : busy === "logout"
                        ? "Ending session…"
                        : "Signing in…"
                    : screen.kind === "setup"
                      ? "Create administrator"
                      : "Sign in"}
                  <span aria-hidden="true">→</span>
                </button>
              </form>
              <p className="vi-security-note">
                Session credentials stay in this page’s memory. Reloading
                requires a new sign-in.
              </p>
            </section>
          </div>
        )}

        {(screen.kind === "loading" || screen.kind === "dashboard_loading") && (
          <section className="vi-state-card">
            <span className="vi-loading-mark" aria-hidden="true">
              ◇
            </span>
            <p className="vi-eyebrow">
              {screen.kind === "loading"
                ? "CONNECTING"
                : "VERIFYING YOUR SESSION"}
            </p>
            <h1 ref={heading} tabIndex={-1}>
              {screen.kind === "loading"
                ? "Checking your installation"
                : "Loading your worlds"}
            </h1>
            <p role="status">
              {screen.kind === "loading"
                ? "Reading the installation’s verified state…"
                : "Your catalog appears only after authenticated loading completes."}
            </p>
          </section>
        )}

        {screen.kind === "safe_mode" && (
          <section className="vi-state-card">
            <p className="vi-eyebrow">PROTECTED STATE</p>
            <h1 ref={heading} tabIndex={-1}>
              Installation safe mode
            </h1>
            <p>
              The server could not verify this installation’s integrity. Setup,
              sign-in, and world changes are disabled to protect existing
              records.
            </p>
            <p>
              Ask the local operator to inspect the server and restore its
              verified state. Do not delete or replace its data to restart
              setup.
            </p>
            <button
              type="button"
              className="vi-button vi-secondary"
              onClick={() => void discover()}
            >
              Check installation again
            </button>
          </section>
        )}

        {screen.kind === "unavailable" && (
          <section className="vi-state-card">
            <p className="vi-eyebrow">CONNECTION NEEDS ATTENTION</p>
            <h1 ref={heading} tabIndex={-1}>
              {screen.retry === "dashboard"
                ? "Your worlds could not be loaded"
                : "Installation unavailable"}
            </h1>
            <p>
              {screen.retry === "dashboard"
                ? "No world catalog is shown because the authenticated request did not complete. Your saved worlds have not been replaced with an empty catalog."
                : "Start the standalone installation service, check its configured address, and try again."}
            </p>
            <button
              type="button"
              className="vi-button vi-primary"
              onClick={() =>
                void (screen.retry === "dashboard"
                  ? refreshDashboard()
                  : discover())
              }
            >
              Retry connection
            </button>
          </section>
        )}

        {screen.kind === "dashboard" && dashboard && (
          <>
            <section className="vi-dashboard-header">
              <div>
                <p className="vi-eyebrow">YOUR INSTALLATION</p>
                <h1 ref={heading} tabIndex={-1}>
                  Worlds worth returning to.
                </h1>
                <p>
                  Keep each adventure in its own world. This catalog manages
                  metadata; workspaces are not provisioned yet.
                </p>
              </div>
              <div className="vi-catalog-stats">
                <span>
                  <strong>{activeWorlds.length}</strong> active{" "}
                  {activeWorlds.length === 1 ? "world" : "worlds"}
                </span>
                <span>Catalog revision {dashboard.catalog.revision}</span>
                <button
                  type="button"
                  className="vi-button vi-quiet"
                  disabled={Boolean(busy)}
                  onClick={() => void refreshDashboard()}
                >
                  Refresh catalog
                </button>
              </div>
            </section>

            {retryCommand && (
              <section
                className="vi-retry-card"
                aria-label="Unconfirmed world operation"
              >
                <div>
                  <h2>Confirm the previous operation</h2>
                  <p>
                    The original command will be reused. Do not create a
                    replacement while its outcome is unknown.
                  </p>
                </div>
                <button
                  type="button"
                  className="vi-button vi-secondary"
                  disabled={Boolean(busy)}
                  onClick={() => void execute(retryCommand)}
                >
                  {busy ? "Confirming…" : "Retry operation"}
                </button>
              </section>
            )}

            <div className="vi-dashboard-grid">
              <div className="vi-catalog">
                <div className="vi-section-heading">
                  <h2>Active worlds</h2>
                  <span>{activeWorlds.length} / 128</span>
                </div>
                {activeWorlds.length > 0 ? (
                  <div className="vi-world-grid">
                    {activeWorlds.map(renderWorld)}
                  </div>
                ) : (
                  <section className="vi-empty-card">
                    <WorldMark />
                    <h3>Your first world is a name away.</h3>
                    <p>
                      Create a world record to start organizing your next
                      adventure. You can rename it or archive it later.
                    </p>
                    <span>No active worlds in this verified catalog</span>
                  </section>
                )}
                {archivedWorlds.length > 0 && (
                  <section className="vi-archive-section">
                    <div className="vi-section-heading">
                      <h2>Archived worlds</h2>
                      <span>{archivedWorlds.length} retained</span>
                    </div>
                    <p>
                      Archived records remain in the catalog. Archiving does not
                      delete their data.
                    </p>
                    <div className="vi-world-grid">
                      {archivedWorlds.map(renderWorld)}
                    </div>
                  </section>
                )}
              </div>
              <aside className="vi-sidebar">
                <section className="vi-create-card">
                  <p className="vi-eyebrow">A NEW BEGINNING</p>
                  <h2>Create a world</h2>
                  <p>
                    Give your adventure a name. World and table identities are
                    assigned by the server.
                  </p>
                  <form
                    aria-label="Create world"
                    className="vi-form"
                    onSubmit={(event) => submitWorld(event, "create")}
                  >
                    <label htmlFor="world-name">
                      World name
                      <input
                        id="world-name"
                        name="world_name"
                        value={worldName}
                        onChange={(event) => setWorldName(event.target.value)}
                        required
                        maxLength={160}
                        placeholder="The Lantern Coast"
                        disabled={locked || activeWorlds.length >= 128}
                        aria-describedby="world-help installation-feedback"
                      />
                    </label>
                    <p id="world-help">D&amp;D 5E · Engine-native system</p>
                    <button
                      type="submit"
                      className="vi-button vi-primary"
                      disabled={locked || activeWorlds.length >= 128}
                    >
                      {busy === "create" ? "Creating world…" : "Create world"}
                      <span aria-hidden="true">+</span>
                    </button>
                  </form>
                </section>
                <section className="vi-provisioning-note">
                  <span aria-hidden="true">↗</span>
                  <div>
                    <h2>What comes next</h2>
                    <p>
                      Workspace provisioning is not available yet. Creating a
                      record does not launch or connect a playable table.
                    </p>
                    <a href="/">Explore the demonstration table →</a>
                  </div>
                </section>
              </aside>
            </div>

            {editing && (
              <section
                className="vi-editor-card"
                aria-labelledby="rename-heading"
              >
                <form
                  aria-label="Rename world"
                  className="vi-form"
                  onSubmit={(event) => submitWorld(event, "rename")}
                >
                  <h2 id="rename-heading">Rename world</h2>
                  <p>
                    Update the display name for {editing.world.name}. Its
                    identities and retained data stay the same.
                  </p>
                  <label htmlFor="rename-world-name">
                    New world name
                    <input
                      ref={renameInput}
                      id="rename-world-name"
                      value={renamedWorld}
                      onChange={(event) => setRenamedWorld(event.target.value)}
                      required
                      maxLength={160}
                      disabled={locked}
                      aria-describedby="installation-feedback"
                    />
                  </label>
                  <div className="vi-inline-actions">
                    <button
                      type="submit"
                      className="vi-button vi-primary"
                      disabled={locked}
                    >
                      {busy === "rename" ? "Saving name…" : "Save name"}
                    </button>
                    <button
                      type="button"
                      className="vi-button vi-secondary"
                      disabled={locked}
                      onClick={() => setEditing(null)}
                    >
                      Cancel rename
                    </button>
                  </div>
                </form>
              </section>
            )}

            {archiving && (
              <section
                className="vi-editor-card vi-archive-confirm"
                aria-labelledby="archive-heading"
              >
                <p className="vi-eyebrow">PLEASE CONFIRM</p>
                <h2 id="archive-heading">Archive {archiving.world.name}?</h2>
                <p>
                  This removes the world from the active list and prevents
                  launch. Its record and data are retained, not deleted.
                  Restoring archived worlds is not available in this interface.
                </p>
                <div className="vi-inline-actions">
                  <button
                    ref={archiveConfirm}
                    type="button"
                    className="vi-button vi-danger"
                    disabled={locked}
                    onClick={() => void confirmArchive()}
                  >
                    {busy === "archive" ? "Archiving…" : "Confirm archive"}
                  </button>
                  <button
                    type="button"
                    className="vi-button vi-secondary"
                    disabled={locked}
                    onClick={() => setArchiving(null)}
                  >
                    Keep world active
                  </button>
                </div>
              </section>
            )}
          </>
        )}
      </main>
      <footer className="vi-footer">
        <span>DND Sim · Standalone administration</span>
        <span>World records now. New adventures ahead.</span>
      </footer>
    </div>
  );
}

function WorldMark() {
  return (
    <svg viewBox="0 0 80 80" fill="none" aria-hidden="true">
      <path d="M40 5 72 23v34L40 75 8 57V23L40 5Z" stroke="currentColor" />
      <path
        d="m40 5 16 28-16 42-16-42L40 5Zm-32 18 32 52 32-52M8 57l48-24-16-28-16 28 48 24M8 23h64"
        stroke="currentColor"
        opacity=".55"
      />
      <circle cx="40" cy="40" r="5" fill="currentColor" />
    </svg>
  );
}
