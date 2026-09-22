"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { VttTableParticipant } from "./vtt-access";
import { VttApiError } from "./vtt-client";
import {
  buildSceneActivateRequest,
  buildSceneArchiveRequest,
  buildSceneCreateRequest,
  buildSceneDuplicateRequest,
  buildSceneImportRequest,
  buildSceneUpdateRequest,
  getSceneLibraryView,
  postSceneLibraryRequest,
  streamSceneEvents,
  type SceneExportBundle,
  type SceneLibraryRequest,
  type SceneLibraryView,
  type SceneMapMetadata,
  type SceneRecord,
} from "./vtt-scenes";

export type SceneConnectionStatus =
  | "loading"
  | "connecting"
  | "live"
  | "reconnecting"
  | "unavailable"
  | "error";

export type SceneMutationOperation =
  | "creating"
  | "duplicating"
  | "updating"
  | "activating"
  | "archiving"
  | "importing"
  | null;

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function sceneErrorMessage(error: unknown): string {
  if (error instanceof VttApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "The scene library could not be synchronized.";
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

export function useVttScenes(input: {
  sessionId: string | null;
  tableId: string | null;
  bearerToken: string | null;
  participant: VttTableParticipant | null;
}) {
  const [view, setView] = useState<SceneLibraryView | null>(null);
  const [status, setStatus] = useState<SceneConnectionStatus>("loading");
  const [operation, setOperation] = useState<SceneMutationOperation>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const viewRef = useRef<SceneLibraryView | null>(null);
  const cursorRef = useRef(0);
  const mutationInFlightRef = useRef(false);

  useEffect(() => {
    if (
      input.sessionId === null ||
      input.tableId === null ||
      input.participant === null
    ) return;
    const controller = new AbortController();
    let active = true;

    const synchronize = async () => {
      setStatus("loading");
      setError(null);
      let hydrated: SceneLibraryView;
      try {
        hydrated = await getSceneLibraryView(
          controller.signal,
          input.bearerToken,
        );
        if (hydrated.table_id !== input.tableId) {
          throw new Error("The scene library belongs to another table.");
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
          setError("Scene lifecycle is not enabled on this table.");
          return;
        }
        setStatus("error");
        setError(sceneErrorMessage(loadError));
        return;
      }
      if (!active) return;
      viewRef.current = hydrated;
      cursorRef.current = hydrated.revision;
      setView(hydrated);
      setStatus("connecting");

      while (active && !controller.signal.aborted) {
        try {
          const cursor = await streamSceneEvents({
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
              if (active) setRefreshKey((current) => current + 1);
            },
          });
          cursorRef.current = Math.max(cursorRef.current, cursor);
          if (!active || controller.signal.aborted) return;
          setStatus("reconnecting");
        } catch (streamError) {
          if (!active || isAbort(streamError)) return;
          if (streamError instanceof VttApiError) {
            setStatus("error");
            setError(sceneErrorMessage(streamError));
            return;
          }
          if (!(streamError instanceof TypeError)) {
            setStatus("error");
            setError("The scene event stream returned invalid data.");
            return;
          }
          setStatus("reconnecting");
          setError("The scene library is reconnecting.");
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
    input.sessionId,
    input.tableId,
    refreshKey,
  ]);

  const requireView = useCallback((): SceneLibraryView => {
    const current = viewRef.current;
    if (current === null || input.sessionId === null) {
      throw new Error("The scene library is not available.");
    }
    return current;
  }, [input.sessionId]);

  const submit = useCallback(
    async (
      nextOperation: Exclude<SceneMutationOperation, null>,
      build: (current: SceneLibraryView) => SceneLibraryRequest,
    ) => {
      if (input.participant?.role !== "gm") {
        throw new Error("Only a Game Master can change the scene library.");
      }
      if (mutationInFlightRef.current) {
        throw new Error("Another scene change is still being saved.");
      }
      mutationInFlightRef.current = true;
      setOperation(nextOperation);
      setError(null);
      try {
        const current = requireView();
        await postSceneLibraryRequest(
          build(current),
          undefined,
          input.bearerToken,
        );
        const hydrated = await getSceneLibraryView(
          undefined,
          input.bearerToken,
        );
        if (hydrated.table_id !== current.table_id) {
          throw new Error("The refreshed scene library belongs to another table.");
        }
        viewRef.current = hydrated;
        cursorRef.current = hydrated.revision;
        setView(hydrated);
      } catch (mutationError) {
        setError(sceneErrorMessage(mutationError));
        if (
          mutationError instanceof VttApiError &&
          mutationError.code === "scene_stale_revision"
        ) {
          setRefreshKey((current) => current + 1);
        }
        throw mutationError;
      } finally {
        mutationInFlightRef.current = false;
        setOperation(null);
      }
    },
    [
      input.bearerToken,
      input.participant,
      requireView,
    ],
  );

  const createScene = useCallback(
    (scene: SceneRecord) =>
      submit("creating", (current) =>
        buildSceneCreateRequest({
          sessionId: input.sessionId as string,
          tableId: current.table_id,
          expectedRevision: current.revision,
          scene,
        }),
      ),
    [input.sessionId, submit],
  );

  const duplicateScene = useCallback(
    (sourceSceneId: string, newSceneId: string, newName: string) =>
      submit("duplicating", (current) =>
        buildSceneDuplicateRequest({
          sessionId: input.sessionId as string,
          tableId: current.table_id,
          expectedRevision: current.revision,
          sourceSceneId,
          newSceneId,
          newName,
        }),
      ),
    [input.sessionId, submit],
  );

  const updateScene = useCallback(
    (sceneId: string, mapMetadata: SceneMapMetadata) =>
      submit("updating", (current) =>
        buildSceneUpdateRequest({
          sessionId: input.sessionId as string,
          tableId: current.table_id,
          expectedRevision: current.revision,
          sceneId,
          mapMetadata,
        }),
      ),
    [input.sessionId, submit],
  );

  const activateScene = useCallback(
    (sceneId: string) =>
      submit("activating", (current) =>
        buildSceneActivateRequest({
          sessionId: input.sessionId as string,
          tableId: current.table_id,
          expectedRevision: current.revision,
          sceneId,
        }),
      ),
    [input.sessionId, submit],
  );

  const archiveScene = useCallback(
    (sceneId: string, successorSceneId: string | null) =>
      submit("archiving", (current) =>
        buildSceneArchiveRequest({
          sessionId: input.sessionId as string,
          tableId: current.table_id,
          expectedRevision: current.revision,
          sceneId,
          successorSceneId,
        }),
      ),
    [input.sessionId, submit],
  );

  const importScene = useCallback(
    (bundle: SceneExportBundle) =>
      submit("importing", (current) =>
        buildSceneImportRequest({
          sessionId: input.sessionId as string,
          tableId: current.table_id,
          expectedRevision: current.revision,
          bundle,
        }),
      ),
    [input.sessionId, submit],
  );

  const available =
    view !== null &&
    status !== "loading" &&
    status !== "unavailable" &&
    status !== "error";
  const pending = operation !== null;

  return {
    view,
    status,
    operation,
    error,
    pending,
    available,
    canMutate:
      available && !pending && input.participant?.role === "gm",
    createScene,
    duplicateScene,
    updateScene,
    activateScene,
    archiveScene,
    importScene,
    retry: () => setRefreshKey((current) => current + 1),
  };
}

export type VttScenesController = ReturnType<typeof useVttScenes>;
