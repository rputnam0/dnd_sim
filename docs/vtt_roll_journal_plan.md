# Authoritative VTT Roll Journal Plan

Status: prerequisite design for structured roll cards

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

- [ ] Introduce structured d20 and damage-result types without changing RNG call
      order or existing numerical outcomes.
- [ ] Route attacks, damage packets, saving throws, checks, rerolls, and damage
      floors through those result types.
- [ ] Add a complete roll journal to combat turn state and its strict codec;
      reject partial or incompatible snapshots.
- [ ] Prove preview and commit produce byte-identical roll records from identical
      state and RNG, and rejected declarations leave the journal unchanged.
- [ ] Project only the new journal delta as versioned `EventDraft` records from
      the interactive turn and encounter drivers.
- [ ] Map actor visibility intent to participant audiences at the VTT boundary.
- [ ] Render strict, accessible roll cards and reconnect them from the durable
      event log.

## Acceptance tests

- No additional RNG draw occurs when journaling is enabled.
- Fixed-seed batch results remain unchanged.
- Advantage, disadvantage, critical damage, rerolls, saves, resistance, and
  applied damage retain enough facts to explain the final result.
- Preview cards exactly match the later commit cards without advancing revision.
- Restart and exact command retry do not duplicate a card.
- A private or blind outcome is absent from unauthorized HTTP responses, event
  streams, reconnect history, and browser state.

