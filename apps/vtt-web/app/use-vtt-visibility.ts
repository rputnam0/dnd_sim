"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { VttTableParticipant } from "./vtt-access";
import { VttApiError } from "./vtt-client";
import {
  buildDoorStateRequest,
  buildFogUndoRequest,
  buildVisibilityDeleteRequest,
  buildVisibilityPutRequest,
  getVisibilityCatalog,
  getVisibilityPreview,
  getVisibilityProjection,
  postVisibilityRequest,
  streamVisibilityEvents,
  type VisibilityCatalogView,
  type VisibilityProjection,
  type VisibilityProjectionSources,
  type VisibilityRecord,
  visibilityProjectionMatchesSources,
} from "./vtt-visibility";

export type VisibilityConnectionStatus =
  | "loading"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable"
  | "error";

export type VisibilityMutationOperation =
  | "saving"
  | "deleting"
  | "toggling"
  | "undoing"
  | null;

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function message(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The authoritative visibility projection could not be synchronized.";
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

export function useVttVisibility(input: {
  sessionId: string | null;
  tableId: string | null;
  sceneId: string | null;
  sceneRevision: number | null;
  tokenRevision: number | null;
  encounterRevision: number | null;
  bearerToken: string | null;
  participant: VttTableParticipant | null;
}) {
  const [catalog, setCatalog] = useState<VisibilityCatalogView | null>(null);
  const [projection, setProjection] = useState<VisibilityProjection | null>(null);
  const [preview, setPreview] = useState<VisibilityProjection | null>(null);
  const [previewParticipantId, setPreviewParticipantId] = useState<string | null>(null);
  const [status, setStatus] = useState<VisibilityConnectionStatus>("loading");
  const [operation, setOperation] = useState<VisibilityMutationOperation>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [expectedVisibilityRevision, setExpectedVisibilityRevision] = useState<
    number | null
  >(null);
  const catalogRef = useRef<VisibilityCatalogView | null>(null);
  const previewParticipantRef = useRef<string | null>(null);
  const cursorRef = useRef(0);
  const mutationRef = useRef(false);

  const sources = useMemo<VisibilityProjectionSources>(() => ({
    sceneId: input.sceneId,
    sceneRevision: input.sceneRevision,
    tokenRevision: input.tokenRevision,
    visibilityRevision: expectedVisibilityRevision,
    encounterRevision: input.encounterRevision,
  }), [
    expectedVisibilityRevision,
    input.encounterRevision,
    input.sceneId,
    input.sceneRevision,
    input.tokenRevision,
  ]);

  useEffect(() => {
    if (
      input.sessionId === null ||
      input.tableId === null ||
      input.sceneId === null ||
      input.sceneRevision === null ||
      input.tokenRevision === null ||
      input.encounterRevision === null ||
      input.participant === null
    ) return;
    const controller = new AbortController();
    let active = true;
    const hydrate = async () => {
      if (input.participant!.role === "gm") {
        const next = await getVisibilityCatalog(
          input.sceneId!,
          controller.signal,
          input.bearerToken,
        );
        if (next.table_id !== input.tableId || next.scene_id !== input.sceneId) {
          throw new Error("The visibility editor belongs to another table or scene.");
        }
        const selectedPreview = previewParticipantRef.current;
        const nextPreview = selectedPreview === null
          ? null
          : await getVisibilityPreview(
              selectedPreview,
              controller.signal,
              input.bearerToken,
            );
        if (
          nextPreview !== null &&
          !visibilityProjectionMatchesSources(nextPreview, {
            sceneId: input.sceneId,
            sceneRevision: input.sceneRevision,
            tokenRevision: input.tokenRevision,
            visibilityRevision: next.revision,
            encounterRevision: input.encounterRevision,
          })
        ) {
          throw new Error("The visibility preview is stale for the current table sources.");
        }
        if (!active) return next.revision;
        catalogRef.current = next;
        setCatalog(next);
        setProjection(null);
        setPreview(nextPreview);
        setExpectedVisibilityRevision(next.revision);
        cursorRef.current = Math.max(cursorRef.current, next.revision);
        return next.revision;
      }
      const next = await getVisibilityProjection(controller.signal, input.bearerToken);
      if (next.table_id !== input.tableId || next.scene_id !== input.sceneId) {
        throw new Error("The visibility projection belongs to another table or scene.");
      }
      if (!visibilityProjectionMatchesSources(next, {
        sceneId: input.sceneId,
        sceneRevision: input.sceneRevision,
        tokenRevision: input.tokenRevision,
        visibilityRevision: next.visibility_revision,
        encounterRevision: input.encounterRevision,
      })) {
        throw new Error("The visibility projection is stale for the current table sources.");
      }
      if (!active) return next.visibility_revision;
      setProjection(next);
      setCatalog(null);
      setExpectedVisibilityRevision(next.visibility_revision);
      cursorRef.current = Math.max(cursorRef.current, next.visibility_revision);
      return next.visibility_revision;
    };
    let refreshAgain = false;
    let refreshPromise: Promise<number> | null = null;
    const requestHydrate = (): Promise<number> => {
      if (refreshPromise !== null) {
        refreshAgain = true;
        return refreshPromise;
      }
      refreshPromise = (async () => {
        let revision = 0;
        do {
          refreshAgain = false;
          revision = await hydrate();
        } while (active && refreshAgain);
        return revision;
      })().finally(() => {
        refreshPromise = null;
      });
      return refreshPromise;
    };
    const synchronize = async () => {
      setStatus("loading");
      setError(null);
      setCatalog(null);
      setProjection(null);
      setPreview(null);
      setExpectedVisibilityRevision(null);
      try {
        await requestHydrate();
      } catch (loadError) {
        if (!active || isAbort(loadError)) return;
        if (
          loadError instanceof VttApiError &&
          (loadError.status === 404 || loadError.code === "not_found")
        ) {
          setStatus("unavailable");
          setError("Authoritative fog and vision are not enabled on this table.");
          return;
        }
        setStatus("error");
        setError(message(loadError));
        return;
      }
      setStatus("connecting");
      while (active && !controller.signal.aborted) {
        try {
          const cursor = await streamVisibilityEvents({
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
            onEvent: (event) => {
              cursorRef.current = Math.max(cursorRef.current, event.sequence);
              if (!active) return;
              setStatus("loading");
              setError(null);
              setCatalog(null);
              catalogRef.current = null;
              setProjection(null);
              setPreview(null);
              setExpectedVisibilityRevision(event.revision);
              void requestHydrate()
                .then(() => {
                  if (active) setStatus("live");
                })
                .catch((refreshError) => {
                  if (!active || isAbort(refreshError)) return;
                  setStatus("error");
                  setError(message(refreshError));
                });
            },
          });
          cursorRef.current = Math.max(cursorRef.current, cursor);
          if (!active || controller.signal.aborted) return;
          setStatus("reconnecting");
        } catch (streamError) {
          if (!active || isAbort(streamError)) return;
          if (streamError instanceof VttApiError && streamError.status !== 0) {
            setStatus("error");
            setError(message(streamError));
            return;
          }
          setStatus("reconnecting");
          setError("The visibility projection is reconnecting.");
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
    input.encounterRevision,
    input.participant,
    input.sceneId,
    input.sceneRevision,
    input.sessionId,
    input.tableId,
    input.tokenRevision,
    refreshKey,
  ]);

  const mutate = useCallback(async (
    nextOperation: Exclude<VisibilityMutationOperation, null>,
    build: (current: VisibilityCatalogView) => Parameters<typeof postVisibilityRequest>[0],
  ) => {
    if (input.participant?.role !== "gm") {
      throw new Error("Only a Game Master can author visibility.");
    }
    if (mutationRef.current || catalogRef.current === null) {
      throw new Error("The visibility editor is not ready for another change.");
    }
    mutationRef.current = true;
    setOperation(nextOperation);
    setError(null);
    if (previewParticipantRef.current !== null) setPreview(null);
    try {
      const current = catalogRef.current;
      await postVisibilityRequest(build(current), undefined, input.bearerToken);
      const next = await getVisibilityCatalog(current.scene_id, undefined, input.bearerToken);
      catalogRef.current = next;
      cursorRef.current = Math.max(cursorRef.current, next.revision);
      setCatalog(next);
      setExpectedVisibilityRevision(next.revision);
      if (previewParticipantRef.current) {
        const nextPreview = await getVisibilityPreview(
          previewParticipantRef.current,
          undefined,
          input.bearerToken,
        );
        if (!visibilityProjectionMatchesSources(nextPreview, {
          sceneId: input.sceneId,
          sceneRevision: input.sceneRevision,
          tokenRevision: input.tokenRevision,
          visibilityRevision: next.revision,
          encounterRevision: input.encounterRevision,
        })) {
          throw new Error("The visibility preview is stale for the current table sources.");
        }
        setPreview(nextPreview);
      }
    } catch (mutationError) {
      setError(message(mutationError));
      if (
        mutationError instanceof VttApiError &&
        mutationError.code === "visibility_stale_revision"
      ) setRefreshKey((current) => current + 1);
      throw mutationError;
    } finally {
      mutationRef.current = false;
      setOperation(null);
    }
  }, [
    input.bearerToken,
    input.encounterRevision,
    input.participant,
    input.sceneId,
    input.sceneRevision,
    input.tokenRevision,
  ]);

  const currentProjection = visibilityProjectionMatchesSources(projection, sources)
    ? projection
    : null;
  const currentPreview = visibilityProjectionMatchesSources(preview, sources)
    ? preview
    : null;

  return {
    catalog,
    projection: currentProjection,
    preview: currentPreview,
    sources,
    previewParticipantId,
    status,
    operation,
    error,
    canMutate: status === "live" && operation === null && input.participant?.role === "gm",
    putRecord: (record: VisibilityRecord) =>
      mutate("saving", (current) => buildVisibilityPutRequest({
        sessionId: input.sessionId!, tableId: current.table_id,
        expectedRevision: current.revision, record,
      })),
    deleteRecord: (recordId: string) =>
      mutate("deleting", (current) => buildVisibilityDeleteRequest({
        sessionId: input.sessionId!, tableId: current.table_id,
        expectedRevision: current.revision, sceneId: current.scene_id, recordId,
      })),
    toggleDoor: (barrierId: string, portalState: "open" | "closed") =>
      mutate("toggling", (current) => buildDoorStateRequest({
        sessionId: input.sessionId!, tableId: current.table_id,
        expectedRevision: current.revision, sceneId: current.scene_id,
        barrierId, portalState,
      })),
    undoFog: (targetRecordId: string) =>
      mutate("undoing", (current) => buildFogUndoRequest({
        sessionId: input.sessionId!, tableId: current.table_id,
        expectedRevision: current.revision, sceneId: current.scene_id,
        targetRecordId,
      })),
    loadPreview: async (participantId: string | null) => {
      previewParticipantRef.current = participantId;
      setPreviewParticipantId(participantId);
      setPreview(null);
      if (participantId === null) {
        return;
      }
      try {
        const next = await getVisibilityPreview(participantId, undefined, input.bearerToken);
        if (!visibilityProjectionMatchesSources(next, sources)) {
          throw new Error("The visibility preview is stale for the current table sources.");
        }
        setPreview(next);
      } catch (previewError) {
        setPreview(null);
        setError(message(previewError));
        throw previewError;
      }
    },
    retry: () => setRefreshKey((current) => current + 1),
  };
}

export type VttVisibilityController = ReturnType<typeof useVttVisibility>;
