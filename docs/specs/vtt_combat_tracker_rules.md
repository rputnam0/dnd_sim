# Combat tracker rules

This specification is an independent product contract for the dnd_sim VTT. It
describes observable jobs and invariants without importing another VTT's code,
schemas, algorithms, identifiers, or visual expression.

## Stable job

A Game Master can correct the durable combat cursor, change initiative order,
or delay the current combatant without editing a snapshot or bypassing the
rules engine. Players receive the resulting public encounter projection but
cannot issue tracker commands.

Actor creation and removal are not tracker operations. They require the future
actor/content-library workflow so that a combatant is a fully validated engine
actor rather than browser-authored internal state.

## Authority and command contract

- Tracker mutations use the existing transactional engine session and event
  log. They are never a browser-only overlay.
- The command kind is `dnd.combat.control.v1`, with `mode=admin` and
  `actor_id=null`.
- Every payload has exactly one operation and a trimmed 1-256 code-point audit
  reason.
- Supported operations are:
  - `advance`: move to the next or previous initiative slot. Forward wrap
    increments the round and resets per-round actor flags; reverse wrap may not
    cross before round one.
  - `reorder`: provide every current actor ID exactly once. Before start, the
    first reordered actor becomes the opening cursor; during combat, the active
    actor is preserved and the durable cursor follows its new slot.
  - `delay`: move the active actor after a later actor in the current round and
    immediately prepare the actor now occupying the current slot.
  - `override`: select an existing active actor and an in-range round number,
    then prepare that turn.
- Cursor-changing operations require a started, nonterminal encounter. Reorder
  is also allowed before encounter start.
- Exact command replay returns the original receipt; same-ID different-content
  commands conflict at the engine-session boundary.

## Events and projection

- Each accepted operation emits one public audit event before any automatically
  prepared-turn event.
- Audit payloads contain the operation, reason, prior and resulting cursor, and
  the authoritative initiative order. They do not contain canonical actor
  internals, credentials, or private token metadata.
- Normal engine/token/visibility projection filtering still removes an event
  when it references an actor hidden from that participant.
- The current session projection remains the only source for round, active
  actor, initiative order, hit points, and action choices.

## Browser and accessibility

- The initiative panel is read-only for non-GMs.
- GM controls use native buttons/selects/inputs, expose a live error/status
  region, and disable while a mutation is pending.
- Next, previous, reorder, delay, and manual override all call the production
  command boundary and refresh the authoritative projection. No optimistic
  cursor is presented.
- Keyboard operation is available through native control semantics, visible
  focus styling, and descriptive labels.

## Hard gates

- Strict payload rejection occurs before mutation and preserves RNG/state.
- Previous at round one, next past the final configured round, delaying after
  an earlier/self actor, unknown/duplicate/missing reorder actors, and invalid
  override rounds all fail with stable nonleaking errors.
- Restart restores the exact corrected cursor and order.
- Protected API tests prove authentication before validation and GM-only
  mutation.
- Mounted browser tests drive every production tracker control and prove a
  player receives no mutation controls.
