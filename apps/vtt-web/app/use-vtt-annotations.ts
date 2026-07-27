"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { VttApiError, type Position3 } from "./vtt-client";
import {
  applyAnnotationEvent,
  buildPingPutRequest,
  getAnnotationsView,
  postAnnotationRequest,
  streamAnnotationEvents,
  type AnnotationEvent,
  type AnnotationsView,
  type PingAnnotation,
} from "./vtt-annotations";

export type AnnotationConnectionStatus =
  | "loading"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable"
  | "error";

function annotationErrorMessage(error: unknown): string {
  if (error instanceof VttApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Shared pings could not be synchronized.";
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
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

export function useVttAnnotations(input: {
  sessionId: string | null;
  sceneId: string | null;
}) {
  const [view, setView] = useState<AnnotationsView | null>(null);
  const [status, setStatus] = useState<AnnotationConnectionStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const viewRef = useRef<AnnotationsView | null>(null);
  const cursorRef = useRef(0);

  const adoptEvent = useCallback((event: AnnotationEvent) => {
    if (event.sequence <= cursorRef.current) return;
    const current = viewRef.current;
    if (current === null) {
      throw new Error("An annotation event arrived before view hydration");
    }
    const next = applyAnnotationEvent(current, event);
    cursorRef.current = event.sequence;
    viewRef.current = next;
    setView(next);
  }, []);

  useEffect(() => {
    if (input.sessionId === null || input.sceneId === null) return;
    const controller = new AbortController();
    let active = true;

    const synchronize = async () => {
      setStatus("loading");
      setError(null);
      let hydrated: AnnotationsView;
      try {
        hydrated = await getAnnotationsView(controller.signal);
        if (
          hydrated.session_id !== input.sessionId ||
          hydrated.scene_id !== input.sceneId
        ) {
          throw new Error(
            "The annotation view does not belong to the active table scene.",
          );
        }
      } catch (loadError) {
        if (!active || isAbort(loadError)) return;
        if (
          loadError instanceof VttApiError &&
          (loadError.status === 404 || loadError.code === "not_found")
        ) {
          viewRef.current = null;
          setView(null);
          setStatus("unavailable");
          setError("Shared pings are not enabled on this table.");
          return;
        }
        setStatus("error");
        setError(annotationErrorMessage(loadError));
        return;
      }

      if (!active) return;
      viewRef.current = hydrated;
      cursorRef.current = hydrated.revision;
      setView(hydrated);
      setStatus("connecting");

      while (active && !controller.signal.aborted) {
        try {
          await streamAnnotationEvents({
            after: cursorRef.current,
            signal: controller.signal,
            onOpen: () => {
              if (active) setStatus("live");
            },
            onEvent: adoptEvent,
          });
          if (!active || controller.signal.aborted) return;
          setStatus("reconnecting");
        } catch (streamError) {
          if (!active || isAbort(streamError)) return;
          if (streamError instanceof VttApiError) {
            setStatus("error");
            setError(annotationErrorMessage(streamError));
            return;
          }
          if (!(streamError instanceof TypeError)) {
            setStatus("error");
            setError("The shared ping stream returned invalid data.");
            return;
          }
          setStatus("reconnecting");
          setError("Shared pings are reconnecting.");
        }
        await waitForReconnect(controller.signal);
      }
    };

    void synchronize();
    return () => {
      active = false;
      controller.abort();
    };
  }, [adoptEvent, input.sceneId, input.sessionId, refreshKey]);

  const placePing = useCallback(
    async (position: Position3) => {
      const current = viewRef.current;
      if (current === null || input.sessionId === null || input.sceneId === null) {
        throw new Error("Shared pings are not available for this scene.");
      }
      setPending(true);
      setError(null);
      try {
        const request = buildPingPutRequest({
          sessionId: input.sessionId,
          tableId: current.table_id,
          sceneId: input.sceneId,
          authorId: "local",
          expectedRevision: current.revision,
          position,
        });
        const response = await postAnnotationRequest(request);
        if (
          response.session_id !== input.sessionId ||
          response.receipt.table_id !== current.table_id ||
          response.receipt.command_id !== request.command.command_id
        ) {
          throw new Error("The shared ping receipt does not match its request.");
        }
        adoptEvent(response.receipt.event);
      } catch (placementError) {
        if (
          placementError instanceof VttApiError &&
          placementError.code === "annotation_stale_revision"
        ) {
          setError("The shared map changed. Refreshing pings; place it again.");
          setRefreshKey((currentKey) => currentKey + 1);
        } else {
          setError(annotationErrorMessage(placementError));
        }
        throw placementError;
      } finally {
        setPending(false);
      }
    },
    [adoptEvent, input.sceneId, input.sessionId],
  );

  const pings = useMemo(
    () =>
      (view?.annotations.filter(
        (annotation): annotation is PingAnnotation =>
          annotation.annotation_type === "ping",
      ) ?? []),
    [view],
  );
  const available =
    view !== null &&
    status !== "loading" &&
    status !== "unavailable" &&
    status !== "error";

  return {
    view,
    pings,
    status,
    error,
    pending,
    available,
    canPlace: available && !pending,
    placePing,
    retry: () => setRefreshKey((currentKey) => currentKey + 1),
  };
}
