"use client";

import { useEffect, useRef, useState } from "react";

import { VttApiError } from "./vtt-client";
import type { VttTableView } from "./vtt-access";
import {
  assertPresenceViewMatchesTable,
  buildPresenceHeartbeatRequest,
  getPresenceView,
  postPresenceHeartbeat,
  presenceSignalForRequest,
  streamPresenceEvents,
  type PresenceHeartbeatRequest,
  type PresenceView,
} from "./vtt-presence";

export type PresenceConnectionStatus =
  | "loading"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable"
  | "error";

function errorMessage(error: unknown): string {
  if (error instanceof VttApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Participant presence could not be synchronized.";
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function isUnavailable(error: unknown): boolean {
  return (
    error instanceof VttApiError &&
    (error.status === 404 || error.code === "not_found")
  );
}

function reconnectDelay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = window.setTimeout(finish, 750);
    signal.addEventListener("abort", finish, { once: true });
  });
}

function refreshInterval(view: PresenceView): number {
  return Math.max(1, Math.min(15_000, Math.floor(view.away_after_ms / 2)));
}

function heartbeatInterval(view: PresenceView): number {
  return Math.max(1, Math.min(10_000, Math.floor(view.away_after_ms / 2)));
}

export function useVttPresence(input: {
  sessionId: string | null;
  bearerToken: string | null;
  table: VttTableView | null;
}) {
  const [view, setView] = useState<PresenceView | null>(null);
  const [status, setStatus] = useState<PresenceConnectionStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const viewRef = useRef<PresenceView | null>(null);
  const cursorRef = useRef(0);

  useEffect(() => {
    if (input.sessionId === null || input.table === null) {
      viewRef.current = null;
      cursorRef.current = 0;
      return;
    }

    const controller = new AbortController();
    const table = input.table;
    const sessionId = input.sessionId;
    const clientId = `web-${crypto.randomUUID()}`;
    let active = true;
    let heartbeatTimer: number | null = null;
    let refreshTimer: number | null = null;
    let heartbeatInFlight = false;

    const adoptView = (nextView: PresenceView) => {
      assertPresenceViewMatchesTable(nextView, table);
      viewRef.current = nextView;
      cursorRef.current = Math.max(cursorRef.current, nextView.revision);
      setView(nextView);
    };

    const hydrate = async () => {
      const nextView = await getPresenceView(controller.signal, input.bearerToken);
      if (!active) return nextView;
      adoptView(nextView);
      return nextView;
    };

    const postWithOneNetworkRetry = async (request: PresenceHeartbeatRequest) => {
      try {
        return await postPresenceHeartbeat(
          request,
          controller.signal,
          input.bearerToken,
        );
      } catch (postError) {
        if (!(postError instanceof TypeError) || controller.signal.aborted) {
          throw postError;
        }
        await reconnectDelay(controller.signal);
        if (controller.signal.aborted) throw postError;
        return postPresenceHeartbeat(
          request,
          controller.signal,
          input.bearerToken,
        );
      }
    };

    const buildHeartbeat = (current: PresenceView) =>
      buildPresenceHeartbeatRequest({
        sessionId,
        tableId: table.table_id,
        expectedRevision: current.revision,
        participantId: table.current_participant.participant_id,
        clientId,
      });

    const sendHeartbeat = async () => {
      if (heartbeatInFlight || controller.signal.aborted) return;
      heartbeatInFlight = true;
      try {
        let current = viewRef.current ?? (await hydrate());
        let request = buildHeartbeat(current);
        let response;
        try {
          response = await postWithOneNetworkRetry(request);
        } catch (postError) {
          if (
            !(postError instanceof VttApiError) ||
            postError.code !== "presence_stale_revision"
          ) {
            throw postError;
          }
          current = await hydrate();
          request = buildHeartbeat(current);
          response = await postWithOneNetworkRetry(request);
        }
        const signal = presenceSignalForRequest(request, response);
        cursorRef.current = Math.max(cursorRef.current, signal.sequence);
        await hydrate();
        if (active) {
          setStatus("live");
          setError(null);
        }
      } finally {
        heartbeatInFlight = false;
      }
    };

    const scheduleHeartbeat = () => {
      if (!active || controller.signal.aborted || viewRef.current === null) return;
      heartbeatTimer = window.setTimeout(async () => {
        try {
          await sendHeartbeat();
        } catch (heartbeatError) {
          if (!active || isAbort(heartbeatError)) return;
          setStatus(isUnavailable(heartbeatError) ? "unavailable" : "reconnecting");
          setError(errorMessage(heartbeatError));
        }
        scheduleHeartbeat();
      }, heartbeatInterval(viewRef.current));
    };

    const scheduleRefresh = () => {
      if (!active || controller.signal.aborted || viewRef.current === null) return;
      refreshTimer = window.setTimeout(async () => {
        try {
          await hydrate();
        } catch (refreshError) {
          if (!active || isAbort(refreshError)) return;
          setStatus(isUnavailable(refreshError) ? "unavailable" : "reconnecting");
          setError(errorMessage(refreshError));
        }
        scheduleRefresh();
      }, refreshInterval(viewRef.current));
    };

    const followSignals = async () => {
      while (active && !controller.signal.aborted) {
        try {
          const cursor = await streamPresenceEvents({
            after: cursorRef.current,
            bearerToken: input.bearerToken,
            signal: controller.signal,
            onOpen: () => {
              if (!active) return;
              setStatus("live");
              setError(null);
            },
            onSignal: (signal) => {
              if (!active || signal.sequence <= cursorRef.current) return;
              cursorRef.current = signal.sequence;
              void hydrate().catch((streamHydrationError) => {
                if (!active || isAbort(streamHydrationError)) return;
                setStatus("reconnecting");
                setError(errorMessage(streamHydrationError));
              });
            },
          });
          cursorRef.current = Math.max(cursorRef.current, cursor);
          if (!active || controller.signal.aborted) return;
          setStatus("reconnecting");
          setError("Participant presence is reconnecting.");
        } catch (streamError) {
          if (!active || isAbort(streamError)) return;
          if (isUnavailable(streamError)) {
            setStatus("unavailable");
            setError("This table has no participant presence service.");
            return;
          }
          setStatus("reconnecting");
          setError(errorMessage(streamError));
        }
        await reconnectDelay(controller.signal);
      }
    };

    const start = async () => {
      setStatus("loading");
      setError(null);
      try {
        await hydrate();
        if (!active) return;
        setStatus("connecting");
        await sendHeartbeat();
        if (!active) return;
        scheduleHeartbeat();
        scheduleRefresh();
        void followSignals();
      } catch (startError) {
        if (!active || isAbort(startError)) return;
        if (isUnavailable(startError)) {
          setStatus("unavailable");
          setError("This table has no participant presence service.");
        } else {
          setStatus("error");
          setError(errorMessage(startError));
        }
      }
    };

    void start();
    return () => {
      active = false;
      controller.abort();
      if (heartbeatTimer !== null) window.clearTimeout(heartbeatTimer);
      if (refreshTimer !== null) window.clearTimeout(refreshTimer);
    };
  }, [input.bearerToken, input.sessionId, input.table, refreshKey]);

  return {
    view,
    records: view?.records ?? [],
    status,
    error,
    available: view !== null && status !== "unavailable" && status !== "error",
    retry: () => setRefreshKey((current) => current + 1),
  };
}
