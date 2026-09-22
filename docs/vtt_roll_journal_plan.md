# Authoritative VTT Roll Journal Plan

Status: authoritative action facts and VTT cards integrated; auxiliary roll surfaces remain

## Decision

The VTT must not roll again, reconstruct dice from HP deltas, or present an
aggregate as if it were a captured roll. Structured cards will ship only after
the rules engine owns a deterministic roll journal and projects its committed
facts through the interactive driver.

The engine now binds its roll recorder during interactive turn resolution and
emits only finalized facts after built-in attack timing hooks and target
application. Attack rolls, generated attack damage packets, save actions,
contested grapple/shove checks, and healing effects retain enough provenance to
render authoritative cards. The same transition-local journal is attached to
preview or atomically persisted with a commit. Auxiliary engine rolls such as
initiative, concentration, death saves, and some bespoke feature checks are not
yet projected as VTT cards; they must remain absent rather than reconstructed.

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
- [x] Route attacks, generated damage packets, saving throws, contested checks,
      rerolls, and damage
      floors through those result types.
      The base `rules_2014.attack_roll` boundary now accepts an opt-in bound
      engine recorder and retains its exact normal/advantage/disadvantage draws.
      `rules_2014.roll_damage` likewise retains initial and empowered-reroll
      faces, critical expansion, the parsed flat modifier, damage-floor changes,
      and its authoritative returned raw total.
      Full action resolution now promotes only the post-hook result. Lucky
      alternatives retain every generated face and selected replacement link;
      Bardic Inspiration, Cutting Words, Guided Strike, War God's Blessing, and
      Shield retain signed total/threshold provenance without rewriting the
      base flat modifier. Per-packet damage correlates by stable source
      occurrence and is finalized only after the target resolution packet
      reports its post-hook raw and applied amounts.
- [x] Keep a complete strict journal for each interactive transition and persist
      its committed records atomically with the command receipt; reject partial
      or incompatible journal payloads.
      The immutable `dnd_sim.roll_journal.RollJournal` and strict canonical codec
      are implemented. Committed records live in the durable session event log,
      so the combat snapshot does not duplicate the same journal state.
- [x] Prove preview and commit produce byte-identical roll records from identical
      state and RNG, and rejected declarations leave the journal unchanged.
- [x] Project only the new journal delta as versioned `EventDraft` records from
      the interactive turn and encounter drivers.
- [x] Map actor visibility intent to participant audiences at the VTT boundary.
- [x] Render strict, accessible roll cards and reconnect them from the durable
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
- [x] Populate the journal from actual attack, generated attack damage, save,
      contested check, healing, reroll, and damage-floor resolution paths used
      by interactive actions.
- [x] Add a non-invasive recorder at the real base attack RNG boundary and prove
      across fixed seeds that enabling it preserves the result, draw count, and
      post-roll RNG state.
- [x] Resume an engine recorder from the strict journal codec and append at the
      next deterministic sequence without changing the decoded history.
- [x] Capture the real `roll_damage` RNG boundary, including generated face
      order, empowered-reroll links, critical dice expansion, expression and
      flat modifier, per-die floors, the minimum-zero clamp, and returned raw
      damage without changing RNG state or numerical results.
- [x] Represent a pre-application damage fact honestly with explicit
      `applied_damage: null`; raw damage is never copied into that field.
- [x] Bind and finalize attack records after all built-in attack-roll timing hooks; base
      boundary records must not be projected as final VTT cards before this step.
- [x] Carry captured damage faces through generated damage packets and finalize applied
      damage only after bundle resolution and target mitigation.
- [x] Preserve post-hook modifier dice and thresholds, including worse/tied
      Lucky alternatives, and encode Cutting Words damage as raw-stage packet
      adjustments instead of dropping amount-mismatched captures.
- [x] Reject browser cards whose replacement links, mode/kept face, d20/save
      comparison, or rolled/raw/applied equations are internally impossible.

## Acceptance tests

- No additional RNG draw occurs when journaling is enabled.
- Fixed-seed batch results remain unchanged.
- Advantage, disadvantage, critical damage, rerolls, saves, resistance, and
  applied damage retain enough facts to explain the final result.
- Preview cards exactly match the later commit cards without advancing revision.
- Restart and exact command retry do not duplicate a card.
- A private or blind outcome is absent from unauthorized HTTP responses, event
  streams, reconnect history, and browser state.
