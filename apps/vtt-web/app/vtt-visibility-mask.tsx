"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { VisibilityConnectionStatus } from "./use-vtt-visibility";
import {
  type VisibilityProjection,
  type VisibilityProjectionSources,
  visibilityProjectionMatchesSources,
} from "./vtt-visibility";

export function paintVisibilityMask(
  context: Pick<CanvasRenderingContext2D, "clearRect" | "fillRect" | "fillStyle">,
  projection: VisibilityProjection,
): void {
  const width = projection.mask_width;
  const height = projection.mask_height;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#020707";
  context.fillRect(0, 0, width, height);
  for (const run of projection.visible_runs) {
    let cursor = run.start;
    let remaining = run.length;
    while (remaining > 0) {
      const row = Math.floor(cursor / width);
      const column = cursor % width;
      const length = Math.min(remaining, width - column);
      context.clearRect(column, row, length, 1);
      cursor += length;
      remaining -= length;
    }
  }
}

export function VttVisibilityMask({
  projection,
  sources,
  status,
  error,
}: {
  projection: VisibilityProjection | null;
  sources: VisibilityProjectionSources;
  status: VisibilityConnectionStatus;
  error: string | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [paintedKey, setPaintedKey] = useState<string | null>(null);
  const projectionKey = useMemo(
    () => projection
      ? `${projection.scene_id}:${projection.scene_revision}:${projection.token_revision}:${projection.visibility_revision}:${projection.encounter_revision}`
      : null,
    [projection],
  );
  useEffect(() => {
    if (projection === null || canvasRef.current === null || projectionKey === null) return;
    const context = canvasRef.current.getContext("2d");
    if (context === null) return;
    let nextPaintedKey: string | null = null;
    try {
      paintVisibilityMask(context, projection);
      nextPaintedKey = projectionKey;
    } catch {}
    const frame = window.requestAnimationFrame(() => setPaintedKey(nextPaintedKey));
    return () => window.cancelAnimationFrame(frame);
  }, [projection, projectionKey]);
  const ready = visibilityProjectionMatchesSources(projection, sources) &&
    status === "live" &&
    paintedKey === projectionKey;
  return (
    <div
      className={`visibility-mask ${ready ? "is-ready" : "is-fail-closed"}`}
      aria-hidden={ready ? "true" : undefined}
      role={ready ? undefined : status === "error" ? "alert" : "status"}
      aria-live={ready ? undefined : "polite"}
    >
      {projection ? (
        <canvas
          ref={canvasRef}
          width={projection.mask_width}
          height={projection.mask_height}
          data-visibility-revision={projection.visibility_revision}
        />
      ) : null}
      {!ready ? (
        <span>{error ?? (status === "loading" ? "Loading private view…" : "Private view remains obscured while visibility reconnects.")}</span>
      ) : null}
    </div>
  );
}
