"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { VttTableParticipant } from "./vtt-access";
import { VTT_API_BASE_URL, VttApiError, responseJson } from "./vtt-client";
import {
  commandBase,
  fetchSoundBlob,
  getPresentation,
  parsePresentationSignal,
  postPresentationCommand,
  type PresentationCommand,
  type PresentationView,
  type SoundTrack,
} from "./vtt-presentation";
import { buildVttRequestHeaders } from "./vtt-transport";

type Status = "loading" | "live" | "reconnecting" | "unavailable" | "error";

interface PresentationBinding {
  key: string;
  view: PresentationView | null;
}

interface PresentationHookInput {
  sessionId: string | null;
  tableId: string | null;
  bearerToken: string | null;
  participant: VttTableParticipant | null;
  activeSceneId: string | null;
}

interface SignalStreamInput {
  after: number;
  token: string | null;
  signal: AbortSignal;
  onOpen: () => void;
  onSignal: (revision: number) => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Presentation state could not be synchronized.";
}

function parseSseFields(block: string): Map<string, string> {
  const fields = new Map<string, string>();
  for (const line of block.split("\n")) {
    const separator = line.indexOf(":");
    if (separator <= 0) throw new Error("Presentation SSE field is malformed.");
    const name = line.slice(0, separator);
    if (!new Set(["id", "event", "data"]).has(name) || fields.has(name)) {
      throw new Error("Presentation SSE field is duplicated or unsupported.");
    }
    fields.set(name, line.slice(separator + 1).trimStart());
  }
  return fields;
}

async function streamSignals(input: SignalStreamInput): Promise<void> {
  const response = await fetch(
    `${VTT_API_BASE_URL}/api/v1/presentation-events?after=${input.after}`,
    {
      signal: input.signal,
      headers: buildVttRequestHeaders({
        accept: "text/event-stream",
        bearerToken: input.token,
      }),
    },
  );
  if (!response.ok) await responseJson(response);
  if (!response.body) {
    throw new Error("Presentation event stream has no body.");
  }
  if (
    !(response.headers.get("content-type") ?? "")
      .toLowerCase()
      .startsWith("text/event-stream")
  ) {
    throw new Error("Presentation event stream returned an unsupported media type.");
  }
  input.onOpen();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    if (buffer.length > 65_536) {
      throw new Error("Presentation SSE block exceeds the supported size.");
    }
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      if (!block.startsWith(":")) {
        const fields = parseSseFields(block);
        if (fields.get("event") !== "vtt.presentation_changed") {
          throw new Error("Presentation SSE event type is invalid.");
        }
        const parsed = parsePresentationSignal(
          JSON.parse(fields.get("data") ?? "null"),
        );
        if (String(parsed.sequence) !== fields.get("id")) {
          throw new Error("Presentation SSE identity is invalid.");
        }
        input.onSignal(parsed.revision);
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) {
      if (buffer.trim()) {
        throw new Error("Presentation SSE ended with an incomplete event.");
      }
      return;
    }
  }
}

function localFollowPreference(): boolean {
  try {
    return window.localStorage.getItem("echo-vault-follow-camera") === "1";
  } catch {
    return false;
  }
}

export function useVttPresentation(input: PresentationHookInput) {
  const identity =
    input.participant === null ? null : JSON.stringify(input.participant);
  const [state, setState] = useState<PresentationBinding | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [followCamera, setFollowCameraState] = useState(localFollowPreference);
  const key =
    input.sessionId && input.tableId && identity
      ? `${input.sessionId}\u0000${input.tableId}\u0000${input.bearerToken ?? ""}\u0000${identity}`
      : null;

  useEffect(() => {
    if (key === null || input.sessionId === null || input.tableId === null) return;
    const controller = new AbortController();
    let cursor = 0;

    const hydrate = async () => {
      const view = await getPresentation(controller.signal, input.bearerToken);
      if (
        view.session_id !== input.sessionId ||
        view.table_id !== input.tableId
      ) {
        throw new Error("Presentation state belongs to another table.");
      }
      cursor = view.revision;
      setState({ key, view });
      setError(null);
    };

    const invalidate = (revision: number) => {
      if (revision <= cursor) return;
      cursor = revision;
      setState(null);
      setStatus("loading");
      setRefresh((value) => value + 1);
      controller.abort();
    };

    const synchronize = async () => {
      try {
        await hydrate();
        while (!controller.signal.aborted) {
          try {
            await streamSignals({
              after: cursor,
              token: input.bearerToken,
              signal: controller.signal,
              onOpen: () => setStatus("live"),
              onSignal: invalidate,
            });
          } catch (streamError) {
            if (controller.signal.aborted) return;
            if (!(streamError instanceof TypeError)) throw streamError;
            setStatus("reconnecting");
          }
          await new Promise<void>((resolve) => window.setTimeout(resolve, 750));
        }
      } catch (loadError) {
        if (controller.signal.aborted) return;
        setState({ key, view: null });
        setStatus(
          loadError instanceof VttApiError && loadError.status === 404
            ? "unavailable"
            : "error",
        );
        setError(errorMessage(loadError));
      }
    };

    void synchronize();
    return () => controller.abort();
  }, [
    identity,
    input.bearerToken,
    input.sessionId,
    input.tableId,
    key,
    refresh,
  ]);

  const view = state?.key === key ? state.view : null;
  const mutate = useCallback(
    async (commandType: string, fields: Record<string, unknown>) => {
      if (
        !view ||
        input.sessionId === null ||
        input.tableId === null ||
        input.participant?.role !== "gm"
      ) {
        throw new Error("GM presentation controls are unavailable.");
      }
      const command = {
        ...commandBase({
          tableId: input.tableId,
          revision: view.revision,
          commandType,
        }),
        ...fields,
      } as PresentationCommand;
      await postPresentationCommand(input.sessionId, command, input.bearerToken);
      setState(null);
      setStatus("loading");
      setRefresh((value) => value + 1);
    },
    [
      input.bearerToken,
      input.participant,
      input.sessionId,
      input.tableId,
      view,
    ],
  );

  const camera =
    view?.camera.enabled && view.camera.scene_id === input.activeSceneId
      ? view.camera
      : null;
  const setFollowCamera = useCallback((value: boolean) => {
    setFollowCameraState(value);
    try {
      window.localStorage.setItem(
        "echo-vault-follow-camera",
        value ? "1" : "0",
      );
    } catch {
      // Local follow state remains optional when browser storage is unavailable.
    }
  }, []);
  const bindingMatches = key !== null && state?.key === key;
  const presentedStatus = bindingMatches ? status : "loading";
  const presentedError = bindingMatches ? error : null;

  return useMemo(
    () => ({
      view,
      camera,
      followCamera,
      setFollowCamera,
      status: presentedStatus,
      error: presentedError,
      canManage:
        presentedStatus === "live" && input.participant?.role === "gm",
      mutate,
      retry: () => setRefresh((value) => value + 1),
    }),
    [
      camera,
      followCamera,
      input.participant,
      mutate,
      presentedError,
      presentedStatus,
      setFollowCamera,
      view,
    ],
  );
}

export function useSoundAssetUrl(
  track: SoundTrack | null,
  bearerToken: string | null,
) {
  const [loaded, setLoaded] = useState<{
    key: string;
    url: string | null;
    error: string | null;
  } | null>(null);
  const key = track === null ? null : `${track.content_path}:${track.sha256}`;

  useEffect(() => {
    if (track === null || key === null) return;
    const controller = new AbortController();
    let active = true;
    let url: string | null = null;
    void fetchSoundBlob(track, bearerToken, controller.signal)
      .then((blob) => {
        if (!active) return;
        url = URL.createObjectURL(blob);
        setLoaded({ key, url, error: null });
      })
      .catch((failure) => {
        if (active && !controller.signal.aborted) {
          setLoaded({ key, url: null, error: errorMessage(failure) });
        }
      });
    return () => {
      active = false;
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [bearerToken, key, track]);

  const current = loaded?.key === key ? loaded : null;
  return {
    url: current?.url ?? null,
    error: current?.error ?? null,
    loading: track !== null && current === null,
  };
}

export type VttPresentationController = ReturnType<typeof useVttPresentation>;
