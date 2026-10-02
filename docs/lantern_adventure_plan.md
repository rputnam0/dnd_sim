# ADV-01 — The Lantern Below

Status: in progress  
Owner: adventure-runtime  
Last updated: 2026-10-02  
Canonical source: `docs/program/README.md`

## Outcome

A complete original adventure designed for approximately 30 minutes of first-time
play in the existing browser tabletop. One local player controls three premade
companions. Authored dialogue, exploration, two possible combats, loot, a limited
rest, and a consequential ending share the existing deterministic rules engine
and one durable session. Play duration is a design target pending human playtests.

## Delivery checklist

- [ ] ADV-01a: implement versioned adventure content/state, available choices,
      dialogue branches, exploration interactions, loot, and a limited rest.
- [ ] ADV-01b: connect two encounters to the shared combat driver, automatically
      resolve enemy turns, and retain party health/resources between scenes.
- [ ] ADV-01c: expose a local durable adventure API with optimistic commands,
      atomic saves, exact retries, restart recovery, and an explicit new-run action.
- [ ] ADV-01d: build the adventure route with the existing tactical map, readable
      story/quest/party panels, combat controls, and responsive keyboard access.
- [ ] ADV-01e: prove peaceful and hostile routes, failed checks, defeat, repeated
      loot/rest rejection, mid-combat restart, retries, and browser interactions.
- [ ] ADV-01f: complete full checks, browser inspection, independent review,
      operating instructions, and a pull request.

Items remain unchecked until passing evidence is included in a PR. Implementation
notes below distinguish work present locally from accepted completion.

## Adventure beats

1. Lantern landing: meet the party, learn the failing beacon's stakes, enter.
2. Keeper's hall: speak with Keeper Orin. Listening and offering help opens a
   peaceful route; threats initiate the optional fight against two wardens.
3. Flooded archive: search for the keeper's account, discover/disarm a needle
   trap, open a locked supply chest, acquire healing supplies and a silver key.
4. Sheltered stair: one limited rest and final preparations.
5. Beacon chamber: fight the Hollow Lantern and its attendant, then choose
   whether to restore the town's beacon or release its bound spirit.
6. Return: an ending and journal reflect dialogue, loot, and the final decision.

Use a bounded original mechanic set. Player combat retains whole-turn commands
and automatic reactions for this slice. The player interface commits actions
without exposing the actual future random result in a preview.

## Shared wire contract

`GET /api/v1/adventure` returns `adventure.view.v1` with:

- `session_id`, `revision`, `versions` (existing `VTTVersionInfo`).
- `title`, `subtitle`, `phase` (`exploration`, `combat`, `complete`, `defeat`).
- `location`: `{id, name, description}`; `scene`: existing `SquareGridScene`.
- `party`: existing `ActorProjection[]`; `combat`: existing
  `EncounterProjection | null`.
- `choices`: `{id, label, description}[]`, the only currently legal narrative,
  travel, loot, item-use, rest, ending, and restart choices.
- `journal`: `{id, title, text}[]`; `inventory`:
  `{id, name, quantity, description}[]`.
- `objective`: string; `dialogue`: `{speaker, text} | null`;
  `ending`: `{title, text} | null`.

`POST /api/v1/adventure/commands` accepts the existing `VTTCommand` envelope.
`adventure.choose.v1` has exactly `{choice_id: string}`; combat accepts existing
`dnd.declare_turn.v1`. Only `commit` mode is accepted. Server chooses enemies,
rolls, rewards, and available choices. Returns the existing commit receipt; client
then reloads the view. Same command ID is retained for an uncertain retry. No
client-provided HP, rewards, story flags, or arbitrary state writes are accepted.

All adventure state lives in one `EngineSession` behind `VTTSessionService` and
`SQLiteSessionEventStore`. The adventure driver nests the encounter driver,
never a second session or RNG. Scenes are derived from the adventure location,
avoiding cross-store scene/campaign transactions. New run is an explicit choice
and requires a confirmation in the browser; it retains monotonic session history.

## Verification and handoff

Use `uv run` for Python and browser commands. Backend behavioral tests come first;
frontend contract and mounted interaction tests cover the public projection.
Run Black, the full Python suite, program-doc checks, browser typecheck/build/tests,
ESLint, and a real-browser route before PR review. Keep benchmark artifacts and
the original checkout untouched. Implementation worktree:
`codex/lantern-adventure`, based on `codex/level-five-encounter-benchmark`.

### Acceptance evidence — 2026-10-02

- Full Python suite: 2,149 passed; seven existing plotting deprecation warnings.
- Frontend suite: 189 passed; strict TypeScript checks, production build, and
  ESLint passed. Black and the program-documentation verifier passed.
- Behavioral tests cover both endings, peaceful/hostile keeper routes, failed
  checks, loot/rest limits, targeted healing/revival, defeat/restart, enemy
  pursuit, and bounded combat recaps. HTTP tests cover mid-combat SQLite reopen,
  changed startup seed, exact retries, failed-save rollback, stale commands,
  origin restrictions, and reserved metadata rejection.
- Real browser: peaceful keeper route, failed trap check, chest/loot, backend
  restart at the archive, limited rest, final encounter with movement/ranged
  attacks/healing, mid-combat reload, release ending, ending reload, and both
  cancel/confirm new-run paths. A fresh adventure is ready in the local preview.
- Responsive inspection: phone-width 390px layout has no horizontal overflow;
  desktop layout inspected. Browser error log was empty after the playthrough.
- Independent backend review found no blocking issues. The gateway now explains
  out-of-range targets without spending the turn. Radiant attacks have an actual
  damage-journal regression test.

The 30-minute duration remains a design target pending a human pacing playtest.
This slice intentionally retains automatic reactions and authored, bounded
content; it does not claim a general campaign engine or full rules parity.

### Review base

The starting checkpoint is `11c507c`, which includes the existing VTT and L5
encounter fixes. Because the L5 branch is not yet published, the adventure PR
uses a frozen `codex/lantern-adventure-base` comparison branch at that checkpoint.
This keeps unrelated work out of the adventure review and leaves the concurrent
L5 checkout unchanged. Retarget the PR when its upstream checkpoint is published.
