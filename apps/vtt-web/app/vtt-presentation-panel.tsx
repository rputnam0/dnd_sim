"use client";

import { useEffect, useRef, useState } from "react";

import type { VttTableView } from "./vtt-access";
import { blobToBase64 } from "./vtt-presentation";
import {
  useSoundAssetUrl,
  type VttPresentationController,
} from "./use-vtt-presentation";

export async function attemptSharedAudioPlayback(
  audio: Pick<HTMLAudioElement, "play" | "pause">,
): Promise<boolean> {
  try {
    await audio.play();
    return true;
  } catch {
    audio.pause();
    return false;
  }
}

function localNumberPreference(key: string, fallback: number): number {
  try {
    const stored = Number(window.localStorage.getItem(key));
    return Number.isFinite(stored) && stored >= 0 && stored <= 100
      ? stored
      : fallback;
  } catch {
    return fallback;
  }
}

function localBooleanPreference(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function storePreference(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Local preferences remain optional when browser storage is unavailable.
  }
}

export function VttPresentationPanel({
  table,
  bearerToken,
  activeSceneId,
  controller,
}: {
  table: VttTableView;
  bearerToken: string | null;
  activeSceneId: string | null;
  controller: VttPresentationController;
}) {
  const [volume, setVolumeState] = useState(() =>
    localNumberPreference("echo-vault-sound-volume", 70),
  );
  const [muted, setMutedState] = useState(() =>
    localBooleanPreference("echo-vault-sound-muted"),
  );
  const [blocked, setBlocked] = useState(false);
  const [trackId, setTrackId] = useState("");
  const [trackName, setTrackName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [playlistId, setPlaylistId] = useState("ambience");
  const [playlistName, setPlaylistName] = useState("Ambience");
  const [selectedTrack, setSelectedTrack] = useState("");
  const [centerX, setCenterX] = useState("0");
  const [centerY, setCenterY] = useState("0");
  const [zoom, setZoom] = useState("1");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playback = controller.view?.playback ?? null;
  const track =
    controller.view?.tracks.find((item) => item.track_id === playback?.track_id) ??
    null;
  const sound = useSoundAssetUrl(track, bearerToken);

  useEffect(() => {
    const audio = audioRef.current;
    if (
      !audio ||
      sound.url === null ||
      playback === null ||
      playback.status === "stopped"
    ) {
      return;
    }
    if (audio.src !== sound.url) audio.src = sound.url;
    const elapsed =
      playback.status === "playing" &&
      playback.started_at_ms !== null &&
      controller.view
        ? Math.max(0, controller.view.server_epoch_ms - playback.started_at_ms)
        : 0;
    audio.currentTime = (playback.position_ms + elapsed) / 1_000;
    audio.loop = playback.loop;
    audio.volume = muted ? 0 : volume / 100;
    if (playback.status === "paused") {
      audio.pause();
      queueMicrotask(() => setBlocked(false));
      return;
    }
    void attemptSharedAudioPlayback(audio).then((playing) => setBlocked(!playing));
  }, [controller.view, muted, playback, sound.url, volume]);

  const setVolume = (value: number) => {
    setVolumeState(value);
    if (audioRef.current) audioRef.current.volume = value / 100;
    storePreference("echo-vault-sound-volume", String(value));
  };
  const setMuted = (value: boolean) => {
    setMutedState(value);
    if (audioRef.current) audioRef.current.volume = value ? 0 : volume / 100;
    storePreference("echo-vault-sound-muted", value ? "1" : "0");
  };
  const selectedTrackId = controller.view?.tracks.some(
    (item) => item.track_id === selectedTrack,
  )
    ? selectedTrack
    : (controller.view?.tracks[0]?.track_id ?? "");

  const statusText =
    controller.status === "live"
      ? playback?.status === "stopped"
        ? "Sound stopped."
        : `${track?.name ?? "Shared sound"}: ${playback?.status}.`
      : (controller.error ?? "Loading presentation state…");

  return (
    <section
      className="panel presentation-panel"
      aria-labelledby="presentation-title"
    >
      <p className="eyebrow">Sound &amp; player view</p>
      <h2 id="presentation-title">Shared presentation</h2>
      <p
        role={controller.status === "error" ? "alert" : "status"}
        aria-live="polite"
      >
        {statusText}
      </p>
      <audio
        ref={audioRef}
        preload="auto"
        aria-label={track ? `Shared sound: ${track.name}` : "Shared table sound"}
      />
      <label>
        Local volume
        <input
          type="range"
          min="0"
          max="100"
          value={volume}
          onChange={(event) => setVolume(Number(event.currentTarget.value))}
        />
        <span>{volume}%</span>
      </label>
      <label>
        <input
          type="checkbox"
          checked={muted}
          onChange={(event) => setMuted(event.currentTarget.checked)}
        />
        Mute locally
      </label>
      {blocked ? (
        <button
          type="button"
          onClick={() => {
            const audio = audioRef.current;
            if (audio) {
              void attemptSharedAudioPlayback(audio).then((playing) =>
                setBlocked(!playing),
              );
            }
          }}
        >
          Enable sound
        </button>
      ) : null}
      {sound.error ? <p role="alert">{sound.error}</p> : null}
      <label>
        <input
          type="checkbox"
          checked={controller.followCamera}
          onChange={(event) =>
            controller.setFollowCamera(event.currentTarget.checked)
          }
          disabled={controller.camera === null}
        />
        Follow GM view
      </label>
      <p aria-live="polite">
        {controller.camera
          ? `Shared view at ${controller.camera.center_x_ft}, ${controller.camera.center_y_ft} feet; ${controller.camera.zoom}×.`
          : "No camera is currently shared."}
      </p>

      {table.current_participant.role === "gm" ? (
        <div className="presentation-gm-controls">
          <h3>GM sound desk</h3>
          <label>
            Track ID
            <input
              value={trackId}
              onChange={(event) => setTrackId(event.currentTarget.value)}
            />
          </label>
          <label>
            Track name
            <input
              value={trackName}
              onChange={(event) => setTrackName(event.currentTarget.value)}
            />
          </label>
          <label>
            Audio file
            <input
              type="file"
              accept="audio/mpeg,audio/ogg,audio/wav"
              onChange={(event) => setFile(event.currentTarget.files?.[0] ?? null)}
            />
          </label>
          <button
            type="button"
            disabled={
              !controller.canManage || !file || !trackId || !trackName
            }
            onClick={() => {
              if (!file) return;
              void blobToBase64(file).then((content_base64) =>
                controller.mutate("upload_track", {
                  track_id: trackId,
                  name: trackName,
                  content_base64,
                }),
              );
            }}
          >
            Upload track
          </button>
          <label>
            Library track
            <select
              value={selectedTrackId}
              disabled={!controller.view?.tracks.length}
              onChange={(event) => setSelectedTrack(event.currentTarget.value)}
            >
              {controller.view?.tracks.length ? (
                controller.view.tracks.map((item) => (
                  <option key={item.track_id} value={item.track_id}>
                    {item.name}
                  </option>
                ))
              ) : (
                <option value="">No tracks</option>
              )}
            </select>
          </label>
          <label>
            Playlist ID
            <input
              value={playlistId}
              onChange={(event) => setPlaylistId(event.currentTarget.value)}
            />
          </label>
          <label>
            Playlist name
            <input
              value={playlistName}
              onChange={(event) => setPlaylistName(event.currentTarget.value)}
            />
          </label>
          <button
            type="button"
            disabled={
              !controller.canManage ||
              !selectedTrackId ||
              !playlistId ||
              !playlistName
            }
            onClick={() =>
              void controller.mutate("put_playlist", {
                playlist: {
                  schema_version: "vtt.sound_playlist.v1",
                  playlist_id: playlistId,
                  name: playlistName,
                  track_ids: [selectedTrackId],
                },
              })
            }
          >
            Save playlist
          </button>
          <button
            type="button"
            disabled={!controller.canManage || !selectedTrackId}
            onClick={() => {
              const playlist = controller.view?.playlists.find((item) =>
                item.track_ids.includes(selectedTrackId),
              );
              void controller.mutate("play", {
                track_id: selectedTrackId,
                playlist_id: playlist?.playlist_id ?? null,
                position_ms: 0,
                loop: true,
                audience: ["all"],
              });
            }}
          >
            Play for table
          </button>
          <button
            type="button"
            disabled={!controller.canManage || playback?.status !== "playing"}
            onClick={() => void controller.mutate("pause", {})}
          >
            Pause
          </button>
          <button
            type="button"
            disabled={!controller.canManage || playback?.status === "stopped"}
            onClick={() => void controller.mutate("stop", {})}
          >
            Stop
          </button>

          <h3>Shared camera</h3>
          <label>
            Center X (ft)
            <input
              type="number"
              value={centerX}
              onChange={(event) => setCenterX(event.currentTarget.value)}
            />
          </label>
          <label>
            Center Y (ft)
            <input
              type="number"
              value={centerY}
              onChange={(event) => setCenterY(event.currentTarget.value)}
            />
          </label>
          <label>
            Zoom
            <input
              type="number"
              min="1"
              max="4"
              step="0.25"
              value={zoom}
              onChange={(event) => setZoom(event.currentTarget.value)}
            />
          </label>
          <button
            type="button"
            disabled={!controller.canManage || activeSceneId === null}
            onClick={() => {
              if (activeSceneId) {
                void controller.mutate("share_camera", {
                  scene_id: activeSceneId,
                  center_x_ft: Number(centerX),
                  center_y_ft: Number(centerY),
                  zoom: Number(zoom),
                });
              }
            }}
          >
            Share view
          </button>
          <button
            type="button"
            disabled={!controller.canManage || controller.camera === null}
            onClick={() => void controller.mutate("disable_camera", {})}
          >
            Stop sharing
          </button>
        </div>
      ) : null}
    </section>
  );
}
