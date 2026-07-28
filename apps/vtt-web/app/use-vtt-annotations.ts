"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { VttApiError, type Position3 } from "./vtt-client";
import {
  canDeleteParticipantRecord,
  type VttTableParticipant,
} from "./vtt-access";
import type { AreaTemplateAnnotation } from "./vtt-template-geometry";
import {
  annotationEventForRequest,
  applyAnnotationEvent,
  buildAnnotationDeleteRequest,
  buildAnnotationPutRequest,
  buildPingPutRequest,
  getAnnotationsView,
  postAnnotationRequest,
  streamAnnotationEvents,
  type AnnotationEvent,
  type AnnotationMutationRequest,
  type AnnotationResponse,
  type AnnotationsView,
  type PingAnnotation,
  type VttAnnotation,
} from "./vtt-annotations";

export type AnnotationConnectionStatus =
  | "loading"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable"
  | "error";

export type AnnotationMutationOperation =
  | "placing"
  | "removing"
  | "clearing"
  | null;

function annotationErrorMessage(error: unknown): string {
  if (error instanceof VttApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Shared annotations could not be synchronized.";
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
  bearerToken: string | null;
  participant: VttTableParticipant | null;
}) {
  const [view, setView] = useState<AnnotationsView | null>(null);
  const [status, setStatus] = useState<AnnotationConnectionStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [operation, setOperation] =
    useState<AnnotationMutationOperation>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const viewRef = useRef<AnnotationsView | null>(null);
  const cursorRef = useRef(0);
  const mutationInFlightRef = useRef(false);
  const preserveErrorRef = useRef(false);

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
    if (
      input.sessionId === null ||
      input.sceneId === null ||
      input.participant === null
    ) return;
    const controller = new AbortController();
    let active = true;

    const synchronize = async () => {
      setStatus("loading");
      if (!preserveErrorRef.current) setError(null);
      let hydrated: AnnotationsView;
      try {
        hydrated = await getAnnotationsView(
          controller.signal,
          input.bearerToken,
        );
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
          setError("Shared annotations are not enabled on this table.");
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
            setError("The shared annotation stream returned invalid data.");
            return;
          }
          setStatus("reconnecting");
          setError("Shared annotations are reconnecting.");
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
    input.sceneId,
    input.sessionId,
    refreshKey,
  ]);

  const requireCurrentView = useCallback((): AnnotationsView => {
    const current = viewRef.current;
    if (
      current === null ||
      input.sessionId === null ||
      input.sceneId === null
    ) {
      throw new Error("Shared annotations are not available for this scene.");
    }
    return current;
  }, [input.sceneId, input.sessionId]);

  const submitMutation = useCallback(
    async (request: AnnotationMutationRequest): Promise<AnnotationResponse> => {
      const response = await postAnnotationRequest(
        request,
        undefined,
        input.bearerToken,
      );
      adoptEvent(annotationEventForRequest(request, response));
      return response;
    },
    [adoptEvent, input.bearerToken],
  );

  const beginMutation = useCallback(
    (nextOperation: Exclude<AnnotationMutationOperation, null>) => {
      if (mutationInFlightRef.current) {
        throw new Error("Another annotation change is still being saved.");
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
      preserveErrorRef.current = true;
      if (
        mutationError instanceof VttApiError &&
        mutationError.code === "annotation_stale_revision"
      ) {
        setError(
          `The shared map changed. Refreshing annotations; ${retryGuidance}.`,
        );
        setStatus("loading");
        setRefreshKey((currentKey) => currentKey + 1);
      } else if (
        mutationError instanceof VttApiError &&
        mutationError.code === "annotation_forbidden"
      ) {
        setError(
          "The server refused this deletion because the annotation belongs to another participant.",
        );
      } else {
        setError(annotationErrorMessage(mutationError));
      }
    },
    [],
  );

  const placePing = useCallback(
    async (position: Position3) => {
      beginMutation("placing");
      try {
        const current = requireCurrentView();
        if (input.participant === null || input.participant.role === "spectator") {
          throw new Error("Spectators cannot place shared annotations.");
        }
        const request = buildPingPutRequest({
          sessionId: current.session_id,
          tableId: current.table_id,
          sceneId: current.scene_id,
          authorId: input.participant.participant_id,
          expectedRevision: current.revision,
          position,
        });
        await submitMutation(request);
      } catch (placementError) {
        reportMutationError(placementError, "place it again");
        throw placementError;
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

  const placeAnnotation = useCallback(
    async (annotation: VttAnnotation) => {
      beginMutation("placing");
      try {
        const current = requireCurrentView();
        if (input.participant === null || input.participant.role === "spectator") {
          throw new Error("Spectators cannot place shared annotations.");
        }
        if (annotation.scene_id !== current.scene_id) {
          throw new Error("The template belongs to another scene.");
        }
        const request = buildAnnotationPutRequest({
          sessionId: current.session_id,
          tableId: current.table_id,
          expectedRevision: current.revision,
          annotation,
        });
        await submitMutation(request);
      } catch (placementError) {
        reportMutationError(placementError, "place it again");
        throw placementError;
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

  const removeAnnotation = useCallback(
    async (annotationId: string) => {
      beginMutation("removing");
      try {
        const current = requireCurrentView();
        const target = current.annotations.find(
          (annotation) => annotation.annotation_id === annotationId,
        );
        if (!target) throw new Error("The selected annotation no longer exists.");
        if (
          input.participant === null ||
          !canDeleteParticipantRecord(input.participant, target.author_id)
        ) {
          throw new Error(
            "Only the author or a Game Master can remove this annotation.",
          );
        }
        const request = buildAnnotationDeleteRequest({
          sessionId: current.session_id,
          tableId: current.table_id,
          expectedRevision: current.revision,
          annotationId,
        });
        await submitMutation(request);
      } catch (removalError) {
        reportMutationError(removalError, "select it and remove it again");
        throw removalError;
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

  const clearLocalAnnotations = useCallback(async () => {
    beginMutation("clearing");
    try {
      const initial = requireCurrentView();
      if (input.participant === null) {
        throw new Error("Participant identity is unavailable.");
      }
      const annotationIds = initial.annotations
        .filter(
          (annotation) =>
            annotation.author_id === input.participant?.participant_id,
        )
        .map((annotation) => annotation.annotation_id);
      for (const annotationId of annotationIds) {
        const current = requireCurrentView();
        const target = current.annotations.find(
          (annotation) => annotation.annotation_id === annotationId,
        );
        if (!target) continue;
        if (target.author_id !== input.participant.participant_id) {
          throw new Error(
            "An annotation owner changed while your markers were being cleared.",
          );
        }
        const request = buildAnnotationDeleteRequest({
          sessionId: current.session_id,
          tableId: current.table_id,
          expectedRevision: current.revision,
          annotationId,
        });
        await submitMutation(request);
      }
    } catch (clearError) {
      reportMutationError(clearError, "review the remaining markers and clear again");
      throw clearError;
    } finally {
      finishMutation();
    }
  }, [
    beginMutation,
    finishMutation,
    input.participant,
    reportMutationError,
    requireCurrentView,
    submitMutation,
  ]);

  const pings = useMemo(
    () =>
      (view?.annotations.filter(
        (annotation): annotation is PingAnnotation =>
          annotation.annotation_type === "ping",
      ) ?? []),
    [view],
  );
  const templates = useMemo(
    () =>
      (view?.annotations.filter(
        (annotation): annotation is AreaTemplateAnnotation =>
          annotation.annotation_type !== "ping" &&
          annotation.annotation_type !== "ruler",
      ) ?? []),
    [view],
  );
  const available =
    view !== null &&
    status !== "loading" &&
    status !== "unavailable" &&
    status !== "error";
  const pending = operation !== null;
  const canMutate =
    available && !pending && input.participant?.role !== "spectator";

  return {
    view,
    annotations: view?.annotations ?? [],
    pings,
    templates,
    status,
    error,
    pending,
    operation,
    available,
    canPlace: canMutate,
    canMutate,
    canManageAnnotation: (authorId: string) =>
      canMutate &&
      input.participant !== null &&
      canDeleteParticipantRecord(input.participant, authorId),
    placePing,
    placeAnnotation,
    removeAnnotation,
    clearLocalAnnotations,
    retry: () => {
      preserveErrorRef.current = false;
      setError(null);
      setRefreshKey((currentKey) => currentKey + 1);
    },
  };
}
