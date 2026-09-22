# VTT Sound and Player-View Rules

Status: local clean-room implementation contract

Date: 2026-08-12

This specification closes the stable sound-player and synchronized player-view
jobs identified by the local clean-room gap audit. It is based only on the
repository's independent feature evidence. It does not copy reference source,
schemas, identifiers, assets, algorithms, or visual expression.

## Authority and identity

- One append-only SQLite presentation aggregate is authoritative for a table's
  owned audio tracks, playlists, playback state, and shared camera state.
- Every command carries an exact table ID, command ID, and expected revision.
  Exact canonical retries replay their original receipt; reused IDs with
  different content conflict. Rejected commands do not advance revision.
- Protected authentication happens before request-body or cursor validation.
  Only a GM may upload audio or mutate playlists, playback, and camera state.
- Reads and reconnectable signals bind to the authenticated session and table.
  Signals contain only sequence and revision, so recipients rehydrate their
  exact current projection instead of applying secret-bearing deltas.

## Safe audio

- Audio enters only as an authenticated bounded first-party upload. Remote URLs,
  redirects, embedded markup, and executable media types are not supported.
- The first slice accepts complete MP3, Ogg, and WAV files up to 12 MiB. The
  server checks canonical base64, MIME-signature agreement, whole-file framing
  where the format exposes it, SHA-256 identity, and immutable private serving
  with `nosniff`.
- Track names and playlist names are inert bounded text. IDs are URL-safe.
  Playlists contain 1-128 unique existing track IDs in explicit order.
- Playback is `stopped`, `playing`, or `paused`; it identifies one existing
  track, an optional playlist, a nonnegative position, a loop flag, audience
  selectors, and the server epoch time at which playback began. Stop clears all
  track and audience data. Pause freezes the server-derived position.
- Audience selectors use the existing table vocabulary: `all`, `role:<role>`,
  `participant:<id>`, and `actor:<id>`. A player sees only playback addressed to
  them and only the referenced track metadata/content. The GM sees the full
  library. Hidden track IDs, playlist membership, and playback facts are absent.
- Volume and mute are per-browser preferences in the range 0-100. They are never
  sent to the server or exposed to another participant.
- Browser autoplay rejection is an expected state. The client remains paused,
  exposes a keyboard-native **Enable sound** control, and retries only after that
  user gesture. It never loops permission prompts or claims playback succeeded.

## Shared camera and player view

- The GM may publish an enabled camera for only the currently active scene. It
  contains a finite in-bounds center in canonical feet, a zoom from 1-4, and a
  monotonic presentation epoch. Disabling clears scene and geometry.
- Camera commands are presentation-only: they never move tokens, change engine
  state, or affect movement calibration. A scene activation makes an older
  camera unavailable until the GM publishes a camera for the new scene.
- Players and spectators may locally opt into **Follow GM view**. The preference
  is local and defaults off. When enabled, only an exact session/table/active-
  scene projection may transform the map. Missing, stale, loading, or malformed
  state immediately restores the neutral map transform.
- The GM gets a keyboard-operable camera editor using numeric center/zoom
  controls, **Share view**, and **Stop sharing**. Player view includes a clearly
  labeled follow toggle and live status. Camera motion is disabled under
  `prefers-reduced-motion`.

## Bounds and durability

- At most 256 tracks and 64 playlists may exist per table. Track bytes, records,
  commands, receipts, and presentation events survive restart in one portable
  database. Events are monotonically ordered and reconnect from either `after`
  or `Last-Event-ID`.
- Durable rows are strictly decoded on every read and replay. Command semantics,
  row identity, receipt identity, event identity, and revision must agree;
  corruption fails closed without returning stored content.
- Content fetch returns the same generic 404 for missing and unauthorized audio.
  Stable errors never contain participant, actor, hidden track, or credential
  identities.

## Acceptance fixtures

- Contracts reject malformed signatures, canonical-base64 violations, oversized
  content, control characters, invalid selectors, playlist references, camera
  bounds, extra fields, and inconsistent stopped/playing state.
- Store tests cover upload, playlist CRUD, play/pause/stop, camera share/disable,
  stale revision, exact retry, divergent retry, restart, command tampering,
  record ceilings, and unchanged revision after every rejection.
- Protected API tests cover auth-before-validation, GM-only mutation, player and
  spectator projections, private-content 404, server-clock timing, active-scene
  camera validation, sanitized reconnectable SSE, and restart.
- Browser tests strictly decode all payloads, prove identity changes fail closed,
  prove local volume never enters requests, recover from autoplay rejection by
  an explicit user gesture, and apply a shared camera only for the exact active
  scene. A mounted workflow drives GM upload/playlist/play/pause/stop/camera and
  player volume/follow controls with keyboard-native elements.
