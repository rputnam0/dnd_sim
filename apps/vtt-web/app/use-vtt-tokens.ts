"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { VttTableParticipant } from "./vtt-access";
import { VttApiError } from "./vtt-client";
import {
  buildTokenCreateRequest,
  buildTokenDeleteRequest,
  buildTokenDuplicateRequest,
  buildTokenUpdateRequest,
  getTokenView,
  postTokenRequest,
  streamTokenEvents,
  type TokenPose,
  type TokenRecord,
  type TokenView,
} from "./vtt-tokens";

export type TokenConnectionStatus =
  | "loading"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable"
  | "error";

export type TokenMutationOperation =
  | "creating"
  | "updating"
  | "duplicating"
  | "deleting"
  | null;

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "The token projection could not be synchronized.";
}

function waitForReconnect(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = window.setTimeout(finish, 750);
    signal.addEventListener("abort", finish, { once: true });
  });
}

export function useVttTokens(input: {
  sessionId: string | null;
  tableId: string | null;
  sceneId: string | null;
  bearerToken: string | null;
  participant: VttTableParticipant | null;
}) {
  const [view, setView] = useState<TokenView | null>(null);
  const [status, setStatus] = useState<TokenConnectionStatus>("loading");
  const [operation, setOperation] = useState<TokenMutationOperation>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const viewRef = useRef<TokenView | null>(null);
  const cursorRef = useRef(0);
  const mutationRef = useRef(false);

  useEffect(() => {
    if (
      input.sessionId === null ||
      input.tableId === null ||
      input.sceneId === null ||
      input.participant === null
    ) return;
    const controller = new AbortController();
    let active = true;
    const hydrate = async () => {
      const next = await getTokenView(
        input.sceneId!,
        controller.signal,
        input.bearerToken,
      );
      if (next.table_id !== input.tableId || next.scene_id !== input.sceneId) {
        throw new Error("The token projection belongs to another table or scene.");
      }
      if (!active) return next;
      viewRef.current = next;
      cursorRef.current = Math.max(cursorRef.current, next.revision);
      setView(next);
      return next;
    };
    const synchronize = async () => {
      setStatus("loading");
      setError(null);
      try {
        await hydrate();
      } catch (loadError) {
        if (!active || isAbort(loadError)) return;
        if (
          loadError instanceof VttApiError &&
          (loadError.status === 404 || loadError.code === "not_found")
        ) {
          setStatus("unavailable");
          setError("Authoritative tokens are not enabled on this table.");
          return;
        }
        setStatus("error");
        setError(errorMessage(loadError));
        return;
      }
      setStatus("connecting");
      while (active && !controller.signal.aborted) {
        try {
          const cursor = await streamTokenEvents({
            sceneId: input.sceneId!,
            after: cursorRef.current,
            bearerToken: input.bearerToken,
            signal: controller.signal,
            onOpen: () => {
              if (active) {
                setStatus("live");
                setError(null);
              }
            },
            onEvent: (signal) => {
              cursorRef.current = Math.max(cursorRef.current, signal.sequence);
              if (active) void hydrate().catch(() => undefined);
            },
          });
          cursorRef.current = Math.max(cursorRef.current, cursor);
          if (!active || controller.signal.aborted) return;
          setStatus("reconnecting");
        } catch (streamError) {
          if (!active || isAbort(streamError)) return;
          if (streamError instanceof VttApiError && streamError.status !== 0) {
            setStatus("error");
            setError(errorMessage(streamError));
            return;
          }
          setStatus("reconnecting");
          setError("The token projection is reconnecting.");
        }
        await waitForReconnect(controller.signal);
      }
    };
    void synchronize();
    return () => {
      active = false;
      controller.abort();
    };
  }, [
    input.bearerToken,
    input.participant,
    input.sceneId,
    input.sessionId,
    input.tableId,
    refreshKey,
  ]);

  const mutate = useCallback(
    async (
      nextOperation: Exclude<TokenMutationOperation, null>,
      build: (current: TokenView) => ReturnType<typeof buildTokenCreateRequest>,
    ) => {
      if (input.participant?.role !== "gm") {
        throw new Error("Only a Game Master can change tabletop tokens.");
      }
      if (mutationRef.current || viewRef.current === null) {
        throw new Error("The token projection is not ready for another change.");
      }
      mutationRef.current = true;
      setOperation(nextOperation);
      setError(null);
      try {
        const current = viewRef.current;
        await postTokenRequest(build(current), undefined, input.bearerToken);
        const next = await getTokenView(current.scene_id, undefined, input.bearerToken);
        viewRef.current = next;
        cursorRef.current = Math.max(cursorRef.current, next.revision);
        setView(next);
      } catch (mutationError) {
        setError(errorMessage(mutationError));
        if (
          mutationError instanceof VttApiError &&
          mutationError.code === "token_stale_revision"
        ) setRefreshKey((current) => current + 1);
        throw mutationError;
      } finally {
        mutationRef.current = false;
        setOperation(null);
      }
    },
    [input.bearerToken, input.participant],
  );

  return {
    view,
    status,
    operation,
    error,
    canMutate: status === "live" && operation === null && input.participant?.role === "gm",
    createToken: (token: TokenRecord) =>
      mutate("creating", (current) =>
        buildTokenCreateRequest({
          sessionId: input.sessionId!,
          tableId: current.table_id,
          expectedRevision: current.revision,
          token,
        }),
      ),
    updateToken: (token: TokenRecord) =>
      mutate("updating", (current) =>
        buildTokenUpdateRequest({
          sessionId: input.sessionId!,
          tableId: current.table_id,
          expectedRevision: current.revision,
          token,
        }),
      ),
    duplicateToken: (sourceTokenId: string, newTokenId: string, pose: TokenPose) =>
      mutate("duplicating", (current) =>
        buildTokenDuplicateRequest({
          sessionId: input.sessionId!,
          tableId: current.table_id,
          expectedRevision: current.revision,
          sourceTokenId,
          newTokenId,
          pose,
        }),
      ),
    deleteToken: (sceneId: string, tokenId: string) =>
      mutate("deleting", (current) =>
        buildTokenDeleteRequest({
          sessionId: input.sessionId!,
          tableId: current.table_id,
          expectedRevision: current.revision,
          sceneId,
          tokenId,
        }),
      ),
    retry: () => setRefreshKey((current) => current + 1),
  };
}

export type VttTokensController = ReturnType<typeof useVttTokens>;
