"use client";

import { useCallback, useEffect, useState } from "react";

import type { VttTableParticipant } from "./vtt-access";
import { VttApiError } from "./vtt-client";
import {
  blobToBase64,
  buildMapAssetUploadRequest,
  fetchAuthenticatedMapAsset,
  getMapAssetCatalog,
  postMapAssetUpload,
  type MapAssetCatalog,
  type MapAssetRecord,
} from "./vtt-map-assets";
import type { SceneMapAssetReference } from "./vtt-scenes";

type MapAssetStatus = "loading" | "ready" | "unavailable" | "error";

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function assetErrorMessage(error: unknown): string {
  if (error instanceof VttApiError || error instanceof Error) return error.message;
  return "The map asset catalog could not be synchronized.";
}

export function useVttMapAssets(input: {
  sessionId: string | null;
  tableId: string | null;
  bearerToken: string | null;
  participant: VttTableParticipant | null;
}) {
  const [catalog, setCatalog] = useState<MapAssetCatalog | null>(null);
  const [status, setStatus] = useState<MapAssetStatus>("loading");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (input.sessionId === null || input.tableId === null || input.participant === null) {
      return;
    }
    const controller = new AbortController();
    let active = true;
    const hydrate = async () => {
      setStatus("loading");
      setError(null);
      try {
        const next = await getMapAssetCatalog(controller.signal, input.bearerToken);
        if (next.table_id !== input.tableId) {
          throw new Error("The map asset catalog belongs to another table.");
        }
        if (!active) return;
        setCatalog(next);
        setStatus("ready");
      } catch (loadError) {
        if (!active || isAbort(loadError)) return;
        if (
          loadError instanceof VttApiError &&
          (loadError.status === 404 || loadError.code === "not_found")
        ) {
          setCatalog(null);
          setStatus("unavailable");
          setError("Map uploads are not enabled on this table.");
          return;
        }
        setStatus("error");
        setError(assetErrorMessage(loadError));
      }
    };
    void hydrate();
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

  const uploadAsset = useCallback(
    async (file: File, assetId: string, altText: string): Promise<MapAssetRecord> => {
      if (input.participant?.role !== "gm") {
        throw new Error("Only a Game Master can upload map assets.");
      }
      if (catalog === null || input.sessionId === null || input.tableId === null) {
        throw new Error("The map asset catalog is not available.");
      }
      if (uploading) throw new Error("Another map asset is still uploading.");
      setUploading(true);
      setError(null);
      try {
        const response = await postMapAssetUpload(
          buildMapAssetUploadRequest({
            sessionId: input.sessionId,
            tableId: input.tableId,
            expectedRevision: catalog.revision,
            assetId,
            altText,
            contentBase64: await blobToBase64(file),
          }),
          undefined,
          input.bearerToken,
        );
        const nextCatalog: MapAssetCatalog = {
          ...catalog,
          revision: response.revision,
          assets: [...catalog.assets, response.asset].sort((left, right) =>
            left.reference.asset_id < right.reference.asset_id ? -1 : 1,
          ),
        };
        setCatalog(nextCatalog);
        return response.asset;
      } catch (uploadError) {
        setError(assetErrorMessage(uploadError));
        if (
          uploadError instanceof VttApiError &&
          uploadError.code === "map_asset_stale_revision"
        ) {
          setRefreshKey((current) => current + 1);
        }
        throw uploadError;
      } finally {
        setUploading(false);
      }
    }, [catalog, input.bearerToken, input.participant, input.sessionId, input.tableId, uploading],
  );

  return {
    catalog,
    status,
    uploading,
    error,
    canUpload: status === "ready" && !uploading && input.participant?.role === "gm",
    uploadAsset,
    retry: () => setRefreshKey((current) => current + 1),
  };
}

export type VttMapAssetsController = ReturnType<typeof useVttMapAssets>;

export function useVttMapAssetUrl(
  reference: SceneMapAssetReference | null,
  bearerToken: string | null,
) {
  const referenceKey =
    reference === null
      ? null
      : `${reference.content_path}:${reference.media_type}:${reference.sha256}`;
  const isStatic = reference?.content_path.startsWith("/assets/maps/") ?? false;
  const [loaded, setLoaded] = useState<{
    key: string;
    url: string | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (reference === null || reference.content_path.startsWith("/assets/maps/")) return;
    const controller = new AbortController();
    let active = true;
    let objectUrl: string | null = null;
    const load = async () => {
      try {
        const blob = await fetchAuthenticatedMapAsset(
          reference,
          bearerToken,
          controller.signal,
        );
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setLoaded({ key: referenceKey!, url: objectUrl, error: null });
      } catch (loadError) {
        if (!active || isAbort(loadError)) return;
        setLoaded({
          key: referenceKey!,
          url: null,
          error: assetErrorMessage(loadError),
        });
      }
    };
    void load();
    return () => {
      active = false;
      controller.abort();
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl);
    };
  }, [bearerToken, reference, referenceKey]);

  if (reference === null) return { url: null, error: null, loading: false };
  if (isStatic) return { url: reference.content_path, error: null, loading: false };
  const current = loaded?.key === referenceKey ? loaded : null;
  return {
    url: current?.url ?? null,
    error: current?.error ?? null,
    loading: current === null,
  };
}
