"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { VttApiError } from "./vtt-client";
import {
  canDeleteParticipantRecord,
  type VttTableParticipant,
} from "./vtt-access";
import {
  applyChatEvent,
  buildChatDeleteRequest,
  buildChatPostRequest,
  chatEventForRequest,
  getChatView,
  postChatRequest,
  streamChatEvents,
  type ChatEvent,
  type ChatMutationRequest,
  type ChatResponse,
  type ChatView,
} from "./vtt-chat";

export type ChatConnectionStatus =
  | "loading"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable"
  | "error";

export type ChatMutationOperation = "posting" | "deleting" | null;

function chatErrorMessage(error: unknown): string {
  if (error instanceof VttApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Plain-text chat could not be synchronized.";
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

function waitForReconnect(signal: AbortSignal): Promise<void> {
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

export function useVttChat(input: {
  sessionId: string | null;
  bearerToken: string | null;
  participant: VttTableParticipant | null;
}) {
  const [view, setView] = useState<ChatView | null>(null);
  const [status, setStatus] = useState<ChatConnectionStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [operation, setOperation] = useState<ChatMutationOperation>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const viewRef = useRef<ChatView | null>(null);
  const cursorRef = useRef(0);
  const mutationInFlightRef = useRef(false);
  const preserveErrorRef = useRef(false);

  const adoptEvent = useCallback((event: ChatEvent) => {
    if (event.sequence <= cursorRef.current) return;
    const current = viewRef.current;
    if (current === null) {
      throw new Error("A chat event arrived before view hydration.");
    }
    const next = applyChatEvent(current, event);
    cursorRef.current = event.sequence;
    viewRef.current = next;
    setView(next);
  }, []);

  useEffect(() => {
    if (input.sessionId === null || input.participant === null) return;
    const controller = new AbortController();
    let active = true;

    const synchronize = async () => {
      setStatus("loading");
      if (!preserveErrorRef.current) setError(null);
      let hydrated: ChatView;
      try {
        hydrated = await getChatView(controller.signal, input.bearerToken);
        if (hydrated.session_id !== input.sessionId) {
          throw new Error(
            "The chat view does not belong to the active table session.",
          );
        }
      } catch (loadError) {
        if (!active || isAbort(loadError)) return;
        if (isUnavailable(loadError)) {
          viewRef.current = null;
          cursorRef.current = 0;
          setView(null);
          setStatus("unavailable");
          setError("Plain-text chat is not enabled on this table.");
          return;
        }
        setStatus("error");
        setError(chatErrorMessage(loadError));
        return;
      }

      if (!active) return;
      viewRef.current = hydrated;
      cursorRef.current = hydrated.revision;
      setView(hydrated);
      setStatus("connecting");

      while (active && !controller.signal.aborted) {
        try {
          const cursor = await streamChatEvents({
            after: cursorRef.current,
            bearerToken: input.bearerToken,
            signal: controller.signal,
            onOpen: () => {
              if (active) {
                setStatus("live");
                if (!preserveErrorRef.current) setError(null);
              }
            },
            onEvent: adoptEvent,
          });
          cursorRef.current = Math.max(cursorRef.current, cursor);
          if (!active || controller.signal.aborted) return;
          setStatus("reconnecting");
        } catch (streamError) {
          if (!active || isAbort(streamError)) return;
          if (isUnavailable(streamError)) {
            viewRef.current = null;
            cursorRef.current = 0;
            setView(null);
            setStatus("unavailable");
            setError("Plain-text chat is not enabled on this table.");
            return;
          }
          if (streamError instanceof VttApiError) {
            setStatus("error");
            setError(chatErrorMessage(streamError));
            return;
          }
          if (!(streamError instanceof TypeError)) {
            setStatus("error");
            setError("The chat event stream returned invalid data.");
            return;
          }
          setStatus("reconnecting");
          setError("Plain-text chat is reconnecting.");
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
    adoptEvent,
    input.bearerToken,
    input.participant,
    input.sessionId,
    refreshKey,
  ]);

  const requireCurrentView = useCallback((): ChatView => {
    const current = viewRef.current;
    if (current === null || input.sessionId === null) {
      throw new Error("Plain-text chat is not available for this table.");
    }
    return current;
  }, [input.sessionId]);

  const requestAuthoritativeRefresh = useCallback((message: string) => {
    preserveErrorRef.current = true;
    setError(message);
    setStatus("loading");
    setRefreshKey((currentKey) => currentKey + 1);
  }, []);

  const submitMutation = useCallback(
    async (request: ChatMutationRequest): Promise<ChatResponse> => {
      const response = await postChatRequest(
        request,
        undefined,
        input.bearerToken,
      );
      const event = chatEventForRequest(request, response);
      if (event === null) {
        requestAuthoritativeRefresh(
          "The server accepted the chat change without returning a visible event. Refreshing authoritative chat.",
        );
      } else {
        adoptEvent(event);
      }
      return response;
    },
    [adoptEvent, input.bearerToken, requestAuthoritativeRefresh],
  );

  const beginMutation = useCallback(
    (nextOperation: Exclude<ChatMutationOperation, null>) => {
      if (mutationInFlightRef.current) {
        throw new Error("Another chat change is still being saved.");
      }
      mutationInFlightRef.current = true;
      preserveErrorRef.current = false;
      setError(null);
      setOperation(nextOperation);
    },
    [],
  );

  const finishMutation = useCallback(() => {
    mutationInFlightRef.current = false;
    setOperation(null);
  }, []);

  const reportMutationError = useCallback(
    (mutationError: unknown, retryGuidance: string) => {
      if (
        mutationError instanceof VttApiError &&
        mutationError.code === "chat_stale_revision"
      ) {
        requestAuthoritativeRefresh(
          `Chat changed on the server. Refreshing messages; ${retryGuidance}.`,
        );
      } else if (
        mutationError instanceof VttApiError &&
        mutationError.code === "chat_forbidden"
      ) {
        preserveErrorRef.current = true;
        setError(
          "The server refused this deletion because the message belongs to another participant.",
        );
      } else {
        preserveErrorRef.current = true;
        setError(chatErrorMessage(mutationError));
      }
    },
    [requestAuthoritativeRefresh],
  );

  const postMessage = useCallback(
    async (text: string, audience: string[]) => {
      beginMutation("posting");
      try {
        const current = requireCurrentView();
        if (input.participant === null || input.participant.role === "spectator") {
          throw new Error("Spectators cannot post table messages.");
        }
        const request = buildChatPostRequest({
          sessionId: current.session_id,
          tableId: current.table_id,
          expectedRevision: current.revision,
          text,
          authorId: input.participant.participant_id,
          audience,
        });
        await submitMutation(request);
      } catch (postError) {
        reportMutationError(postError, "review your text and send it again");
        throw postError;
      } finally {
        finishMutation();
      }
    },
    [
      beginMutation,
      finishMutation,
      input.participant,
      reportMutationError,
      requireCurrentView,
      submitMutation,
    ],
  );

  const deleteMessage = useCallback(
    async (messageId: string) => {
      beginMutation("deleting");
      try {
        const current = requireCurrentView();
        const target = current.messages.find(
          (message) => message.message_id === messageId,
        );
        if (!target) throw new Error("The selected message no longer exists.");
        if (
          input.participant === null ||
          !canDeleteParticipantRecord(input.participant, target.author_id)
        ) {
          throw new Error(
            "Only the author or a Game Master can delete this message.",
          );
        }
        const request = buildChatDeleteRequest({
          sessionId: current.session_id,
          tableId: current.table_id,
          expectedRevision: current.revision,
          messageId,
        });
        await submitMutation(request);
      } catch (deleteError) {
        reportMutationError(deleteError, "review the messages and delete it again");
        throw deleteError;
      } finally {
        finishMutation();
      }
    },
    [
      beginMutation,
      finishMutation,
      input.participant,
      reportMutationError,
      requireCurrentView,
      submitMutation,
    ],
  );

  const pending = operation !== null;
  const available =
    view !== null &&
    status !== "loading" &&
    status !== "unavailable" &&
    status !== "error";
  const canMutate =
    available && !pending && input.participant?.role !== "spectator";

  return {
    view,
    messages: view?.messages ?? [],
    status,
    error,
    operation,
    pending,
    available,
    canMutate,
    canDeleteMessage: (authorId: string) =>
      canMutate &&
      input.participant !== null &&
      canDeleteParticipantRecord(input.participant, authorId),
    postMessage,
    deleteMessage,
    retry: () => {
      preserveErrorRef.current = false;
      setError(null);
      setRefreshKey((currentKey) => currentKey + 1);
    },
  };
}
