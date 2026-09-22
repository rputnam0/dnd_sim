"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { VttApiError } from "./vtt-client";
import type { VttTableParticipant } from "./vtt-access";
import {
  buildJournalDeleteDocumentRequest,
  buildJournalDeleteFolderRequest,
  buildJournalPutDocumentRequest,
  buildJournalPutFolderRequest,
  applyJournalEvent,
  getJournalView,
  journalViewMatchesIdentity,
  postJournalRequest,
  streamJournalEvents,
  type JournalEvent,
  type JournalDocument,
  type JournalFolder,
  type JournalView,
} from "./vtt-journal";

export type JournalConnectionStatus = "loading" | "connecting" | "live" | "reconnecting" | "unavailable" | "error";

interface JournalHydrationBinding {
  sessionId: string;
  tableId: string;
  bearerToken: string | null;
  participantIdentity: string;
}

function sameBinding(
  left: JournalHydrationBinding | null,
  right: JournalHydrationBinding | null,
): boolean {
  return left !== null
    && right !== null
    && left.sessionId === right.sessionId
    && left.tableId === right.tableId
    && left.bearerToken === right.bearerToken
    && left.participantIdentity === right.participantIdentity;
}

function message(error: unknown): string {
  if (error instanceof VttApiError || error instanceof Error) return error.message;
  return "The journal could not be synchronized.";
}

export function useVttJournal(input: {
  sessionId: string | null;
  tableId: string | null;
  bearerToken: string | null;
  participant: VttTableParticipant | null;
}) {
  const { sessionId, tableId, bearerToken, participant } = input;
  const participantId = participant?.participant_id ?? null;
  const participantRole = participant?.role ?? null;
  const participantIdentity = participant === null ? null : JSON.stringify(participant);
  const [view, setView] = useState<JournalView | null>(null);
  const [status, setStatus] = useState<JournalConnectionStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [operation, setOperation] = useState<"saving" | "deleting" | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [hydrationBinding, setHydrationBinding] = useState<JournalHydrationBinding | null>(null);
  const viewRef = useRef<JournalView | null>(null);
  const cursorRef = useRef(0);

  const currentBinding = useCallback((): JournalHydrationBinding | null => {
    if (sessionId === null || tableId === null || participantIdentity === null) return null;
    return { sessionId, tableId, bearerToken, participantIdentity };
  }, [bearerToken, participantIdentity, sessionId, tableId]);

  const hydrate = useCallback(async (signal: AbortSignal, nextQuery: string, connectStream = true) => {
    const binding = currentBinding();
    if (binding === null) throw new Error("The journal identity is unavailable.");
    const hydrated = await getJournalView(signal, bearerToken, nextQuery);
    if (!journalViewMatchesIdentity(hydrated, { sessionId, tableId })) {
      throw new Error("The journal view does not belong to the active table.");
    }
    viewRef.current = hydrated;
    cursorRef.current = hydrated.revision;
    setView(hydrated);
    setHydrationBinding(binding);
    if (connectStream) setStatus("connecting");
    setError(null);
  }, [bearerToken, currentBinding, sessionId, tableId]);

  const adoptEvent = useCallback((event: JournalEvent) => {
    if (event.sequence <= cursorRef.current) return;
    const active = viewRef.current;
    if (!active) throw new Error("A journal event arrived before hydration.");
    const next = applyJournalEvent(active, event);
    cursorRef.current = event.sequence;
    viewRef.current = next;
    setView(next);
  }, []);

  const invalidateSearchFromEvent = useCallback((event: JournalEvent) => {
    if (event.sequence <= cursorRef.current) return;
    cursorRef.current = event.sequence;
    viewRef.current = null;
    setView(null);
    setStatus("loading");
    setError(null);
    setRefresh((value) => value + 1);
  }, []);

  useEffect(() => {
    if (sessionId === null || tableId === null || participantId === null) return;
    const controller = new AbortController();
    const synchronize = async () => {
      const attemptedBinding = currentBinding();
      if (attemptedBinding === null) return;
      try {
        await hydrate(controller.signal, query);
        while (!controller.signal.aborted) {
          try {
            await streamJournalEvents({
              after: cursorRef.current,
              bearerToken,
              signal: controller.signal,
              onOpen: () => setStatus("live"),
              onEvent: query || participantRole !== "gm"
                ? invalidateSearchFromEvent
                : adoptEvent,
            });
            if (!controller.signal.aborted) setStatus("reconnecting");
          } catch (streamError) {
            if (controller.signal.aborted) return;
            if (!(streamError instanceof TypeError)) throw streamError;
            setStatus("reconnecting");
          }
          await new Promise<void>((resolve) => window.setTimeout(resolve, 750));
        }
      } catch (loadError) {
        if (controller.signal.aborted) return;
        viewRef.current = null;
        setView(null);
        setHydrationBinding(attemptedBinding);
        if (loadError instanceof VttApiError && loadError.status === 404) {
          setStatus("unavailable");
        } else {
          setStatus("error");
        }
        setError(message(loadError));
      }
    };
    void synchronize();
    return () => controller.abort();
  }, [adoptEvent, bearerToken, currentBinding, hydrate, invalidateSearchFromEvent, participantId, participantRole, query, refresh, sessionId, tableId]);

  const current = useCallback(() => {
    const candidate = viewRef.current;
    const binding = currentBinding();
    if (
      !candidate
      || binding === null
      || hydrationBinding === null
      || !sameBinding(hydrationBinding, binding)
      || !journalViewMatchesIdentity(candidate, { sessionId, tableId })
    ) {
      throw new Error("The journal is not available for this table.");
    }
    return candidate;
  }, [currentBinding, hydrationBinding, sessionId, tableId]);

  const saveDocument = useCallback(async (document: JournalDocument) => {
    if (participantRole !== "gm") throw new Error("Only a Game Master may change the journal.");
    setOperation("saving");
    try {
      const active = current();
      await postJournalRequest(buildJournalPutDocumentRequest({ sessionId: active.session_id, tableId: active.table_id, expectedRevision: active.revision, document }), bearerToken);
      await hydrate(new AbortController().signal, query, false);
    } catch (saveError) {
      setError(message(saveError));
      throw saveError;
    } finally {
      setOperation(null);
    }
  }, [bearerToken, current, hydrate, participantRole, query]);

  const deleteDocument = useCallback(async (documentId: string) => {
    if (participantRole !== "gm") throw new Error("Only a Game Master may change the journal.");
    setOperation("deleting");
    try {
      const active = current();
      await postJournalRequest(buildJournalDeleteDocumentRequest({ sessionId: active.session_id, tableId: active.table_id, expectedRevision: active.revision, documentId }), bearerToken);
      await hydrate(new AbortController().signal, query, false);
    } catch (deleteError) {
      setError(message(deleteError));
      throw deleteError;
    } finally {
      setOperation(null);
    }
  }, [bearerToken, current, hydrate, participantRole, query]);

  const saveFolder = useCallback(async (folder: JournalFolder) => {
    if (participantRole !== "gm") throw new Error("Only a Game Master may change the journal.");
    setOperation("saving");
    try {
      const active = current();
      await postJournalRequest(buildJournalPutFolderRequest({ sessionId: active.session_id, tableId: active.table_id, expectedRevision: active.revision, folder }), bearerToken);
      await hydrate(new AbortController().signal, query, false);
    } catch (saveError) {
      setError(message(saveError));
      throw saveError;
    } finally {
      setOperation(null);
    }
  }, [bearerToken, current, hydrate, participantRole, query]);

  const deleteFolder = useCallback(async (folderId: string) => {
    if (participantRole !== "gm") throw new Error("Only a Game Master may change the journal.");
    setOperation("deleting");
    try {
      const active = current();
      await postJournalRequest(buildJournalDeleteFolderRequest({ sessionId: active.session_id, tableId: active.table_id, expectedRevision: active.revision, folderId }), bearerToken);
      await hydrate(new AbortController().signal, query, false);
    } catch (deleteError) {
      setError(message(deleteError));
      throw deleteError;
    } finally {
      setOperation(null);
    }
  }, [bearerToken, current, hydrate, participantRole, query]);

  const binding = currentBinding();
  const bindingMatches = sameBinding(binding, hydrationBinding);
  const available = bindingMatches && view !== null && journalViewMatchesIdentity(view, { sessionId, tableId }) && status === "live";
  const presentedView = bindingMatches ? view : null;
  const presentedStatus: JournalConnectionStatus = bindingMatches ? status : "loading";
  const documents = useMemo(() => available && presentedView ? presentedView.documents : [], [available, presentedView]);
  return {
    view: presentedView,
    documents,
    folders: available && participantRole === "gm" ? view.folders : [],
    status: presentedStatus,
    error,
    query,
    operation,
    available,
    canMutate: available && operation === null && participantRole === "gm",
    setQuery: (value: string) => {
      setStatus("loading");
      setError(null);
      setQuery(value);
    },
    saveDocument,
    deleteDocument,
    saveFolder,
    deleteFolder,
    retry: () => setRefresh((value) => value + 1),
  };
}
