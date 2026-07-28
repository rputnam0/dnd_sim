# Authoritative VTT Roll Journal Plan

Status: base attack RNG boundary integrated; committed turn-state routing remains

## Decision

The VTT must not roll again, reconstruct dice from HP deltas, or present an
aggregate as if it were a captured roll. Structured cards will ship only after
the rules engine owns a deterministic roll journal and projects its committed
facts through the interactive driver.

Today the engine briefly exposes final attack totals through timing events, but
does not retain those events. Damage helpers return only totals and discard die
faces, while several save rolls remain local variables. The interactive turn
event therefore contains no authoritative dice facts to render.

## Required engine record

The engine-owned record must be versioned and cover, as applicable:

- the turn token, source actor, target actor, action, and roll purpose;
- every generated die face in generation order;
- advantage/disadvantage candidates and the kept result;
- rerolled or replaced faces without losing the original values;
- dice expression, flat modifiers, total, and comparison threshold;
- critical, hit/miss, save success/failure, raw damage, and applied damage;
- a deterministic per-turn sequence and actor-based visibility intent.

The exact public schema is deferred until the engine result types retain all of
those facts. Participant selectors belong to the VTT projection layer rather
than the rules kernel.

## Implementation sequence

- [x] Introduce structured d20 and damage-result types without changing RNG call
      order or existing numerical outcomes.
- [ ] Route attacks, damage packets, saving throws, checks, rerolls, and damage
      floors through those result types.
      The base `rules_2014.attack_roll` boundary now accepts an opt-in bound
      engine recorder and retains its exact normal/advantage/disadvantage draws.
      The full action path is not bound yet because Lucky, inspiration, reaction,
      and timing hooks can replace that base result before it becomes final.
- [ ] Add a complete roll journal to combat turn state and its strict codec;
      reject partial or incompatible snapshots.
      The immutable `dnd_sim.roll_journal.RollJournal` and strict canonical codec
      are implemented; embedding that journal in combat turn state is still
      required.
- [ ] Prove preview and commit produce byte-identical roll records from identical
      state and RNG, and rejected declarations leave the journal unchanged.
- [ ] Project only the new journal delta as versioned `EventDraft` records from
      the interactive turn and encounter drivers.
- [ ] Map actor visibility intent to participant audiences at the VTT boundary.
- [ ] Render strict, accessible roll cards and reconnect them from the durable
      event log.

## Foundation checkpoint (2026-07-27)

- [x] Model d20 candidates, kept faces, rerolls/replacements, thresholds, and
      hit/miss or success/failure outcomes as immutable engine facts.
- [x] Model saving throws and staged damage totals, including signed floor,
      resistance, vulnerability, immunity, and other adjustments.
- [x] Assign deterministic record IDs and contiguous per-turn sequence numbers
      without reading from an RNG.
- [x] Encode complete journals as byte-stable canonical JSON and reject missing,
      incompatible, extra, duplicate-key, forged-ID, or out-of-order payloads.
- [x] Keep audience metadata actor-based (`public`, `gm_only`, or sorted actor
      IDs) so participant mapping remains outside the rules kernel.
- [ ] Populate the journal from actual attack, damage, save, check, reroll, and
      damage-floor resolution paths.
- [x] Add a non-invasive recorder at the real base attack RNG boundary and prove
      across fixed seeds that enabling it preserves the result, draw count, and
      post-roll RNG state.
- [x] Resume an engine recorder from the strict journal codec and append at the
      next deterministic sequence without changing the decoded history.
- [ ] Bind and finalize attack records after all attack-roll timing hooks; base
      boundary records must not be projected as final VTT cards before this step.
- [ ] Capture damage faces at `roll_damage`, carry them through damage packets,
      and finalize raw/applied damage only after bundle resolution.

## Acceptance tests

- No additional RNG draw occurs when journaling is enabled.
- Fixed-seed batch results remain unchanged.
- Advantage, disadvantage, critical damage, rerolls, saves, resistance, and
  applied damage retain enough facts to explain the final result.
- Preview cards exactly match the later commit cards without advancing revision.
- Restart and exact command retry do not duplicate a card.
- A private or blind outcome is absent from unauthorized HTTP responses, event
  streams, reconnect history, and browser state.
