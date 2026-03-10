# Section 1. Product Definition and Scope Guardrails

## 1.1 Purpose

This section defines the product’s identity, target experience, core promises, and scope boundaries. It is the governing section for the rest of the specification package.

All downstream design, content, tooling, and architecture decisions **must** conform to this section. If a later section conflicts with Section 1, Section 1 takes precedence unless it is explicitly revised.

This section is intentionally product-facing. It defines what the system is for, what it should feel like, what it must protect, and what it is not trying to be in its first prove-out.

---

## 1.2 Product Statement

The product is a **creator-authored, desktop-first, painterly isometric digital D&D platform** in which an **AI DM** runs the session, preserves the feel of tabletop play, supports meaningful player deviation, and maintains persistent world consequences, while a deterministic rules engine remains authoritative for tactical combat and other hard-mechanical systems.

The product is designed to let creators build authored adventures that other players can experience as if they were being run by a live tabletop DM. The authored adventure provides structure, canon, and major beats. The AI DM provides narration, roleplay, adjudication support, and flexible response to unexpected player choices.

The product is not defined as a pure CRPG, a pure VTT, or a pure AI story toy. It is a hybrid of:

* **authored campaign structure**
* **tactical 5e-style simulation**
* **AI-mediated flexibility**
* **persistent consequence and world state**

---

## 1.3 Product Thesis

The central thesis of the product is:

> A digital D&D experience becomes more compelling when authored campaign structure and tactical rules reliability are combined with an AI DM that can react to players the way a real tabletop DM would.

This thesis depends on four simultaneous truths:

1. **The adventure has real structure.**
   Players are not dropped into a vague sandbox. There are authored rails, explicit locations, major beats, and meaningful intended content.

2. **The player can still go off-rail.**
   The AI DM is not merely decorative. It must be able to respond when players ask unexpected questions, pursue side ideas, or intentionally leave the main path.

3. **The world remembers what happened.**
   Player deviation, including AI-generated side content and consequences, must persist in save state and affect future play.

4. **The rules remain trustworthy.**
   Tactical play, especially combat, must feel fair, grounded, and legible. The AI DM cannot be allowed to improvise away core mechanical trust.

---

## 1.4 North Star and v1 Shape

### 1.4.1 Long-term north star

The long-term vision is a persistent digital D&D world in which:

* creators author worlds, campaigns, rails, and notes
* players can deviate heavily or completely from the expected path
* the AI DM can introduce side NPCs, side plots, optional detours, encounters, maps, and narrative forks
* those deviations become part of persistent world state
* the experience feels closer to a real tabletop campaign than to a fixed branching CRPG

In practical terms, the long-term north star is an **open-ended, persistent, AI-DM-driven digital tabletop world**.

### 1.4.2 Buildable first product shape

The first product shape must be narrower and provable.

The initial proving target is:

* a **creator-authored one-shot**
* average session length around **2 hours**
* total module length around **4–6 hours**
* a **tactical CRPG core**
* a strong authored story path
* an AI DM that narrates, answers questions, plays NPCs, and supports limited but meaningful derailment
* save/resume with persistent consequences

The product must prove the core fantasy in a one-shot before it attempts to become a fully open, persistent world platform.

This is a scope guardrail, not a permanent product limitation.

---

## 1.5 Core Experience Pillars

The product must be designed around the following pillars.

### 1.5.1 Authored adventure first

The product must feel like a real authored adventure, not a blank improvisation surface.

This means:

* main story structure must be intentional
* major beats, locations, and key NPCs must be creator-authored
* the player should feel that the world has purpose and direction
* the AI DM should supplement authored intent, not replace it

### 1.5.2 Tabletop DM feel

The AI DM must evoke the feeling of a real tabletop DM.

This means:

* it can speak in-fiction
* it can narrate scenes
* it can answer player questions
* it can roleplay NPCs
* it can react to player intent rather than only expose menu trees
* it should feel like a guide, referee, and performer rather than a generic chatbot

### 1.5.3 Trustworthy tactical play

The combat and hard-rules layer must feel dependable.

This means:

* the engine is authoritative for combat and tactical legality
* outcomes should be dice-grounded and explainable
* fairness and player trust matter more than AI surprise
* the AI DM may frame and present rules outcomes, but it may not freely invent them

### 1.5.4 Real deviation with consequence

The product must allow players to deviate from the expected path in ways that matter.

This means:

* players may pursue side ideas, alternate approaches, or off-path actions
* the system should prefer resolution over denial
* divergence should create persistent world consequences
* deviation must not immediately collapse the authored experience

### 1.5.5 Creator-controlled flexibility

The creator must remain the primary authorial force.

This means:

* creators define rails, canon, and intended tone
* creators define what the AI DM may and may not improvise
* the system must support non-technical creators
* creator control must be explicit, not implicit or accidental

---

## 1.6 Primary Users and Supported Modes

### 1.6.1 Primary initial user

The first implementation target is the **solo creator-developer**.

This is the correct starting user because the product depends on authored content, AI behavior tuning, and rapid playtest loops. The system must be shaped first for someone creating and validating content.

### 1.6.2 Player modes

The ship target should support both:

* **solo play**
* **multiplayer party play**

Both are important to the product identity.

### 1.6.3 Party control model

The intended party model is:

* in multiplayer, each player normally controls **one character**
* in solo play, one player may control the **full party**

This should feel natural and not like a fallback mode.

### 1.6.4 Creator participation

The broader vision includes creator-authored adventures that others can play, and may later include creator participation in those sessions. However, the product must not require a live human GM to function. The AI DM is the baseline runtime host.

---

## 1.7 AI DM Contract

The AI DM is one of the defining systems of the product. It must be treated as a governed runtime role, not as a freeform text generator.

### 1.7.1 AI DM responsibilities

The AI DM may perform all of the following, subject to creator controls and engine authority:

* narrate scenes
* roleplay NPCs
* answer world and story questions
* explain or contextualize game state
* interpret player freeform input
* call for non-combat checks
* improvise side characters, side scenes, and side story elements
* generate optional detours when player action leads there
* supplement authored dialogue and authored content
* preserve tone and module voice

### 1.7.2 AI DM voice and presentation

The AI DM should default to a **tabletop DM-style voice**, not a generic assistant voice.

It should:

* stay in character for the module and world
* follow creator-defined tone and style
* support adjustable presets where appropriate
* perform narration at major curated moments rather than constantly flooding the player with prose

### 1.7.3 Authority boundaries

The AI DM is **not** the final authority on combat or tactical legality.

The engine is authoritative for:

* combat
* movement legality
* turn economy
* target legality
* explicit hard-mechanical outcomes already represented in the rules engine

The AI DM may be authoritative for:

* presentation
* narration
* non-combat adjudication framing
* check requests outside strict combat systems
* flexible response to unsupported actions
* creator-approved improvisation

### 1.7.4 Canon preservation

The AI DM must preserve creator-authored canon when that canon is designated as protected.

The AI DM may:

* elaborate on canon
* supplement canon
* bridge between canon points
* invent side content adjacent to canon

The AI DM must not casually overwrite creator-protected canon.

### 1.7.5 Off-rail handling

When a player attempts an action that is not literally authored, the system should prefer the following order:

1. translate the action into a supported gameplay action
2. offer the closest valid action or interpretation
3. resolve it through a probabilistic check with narrative framing
4. create a new persistent world-state branch if the product can support it

Hard denial should be rare. It is acceptable only when required by coherence, creator restrictions, or system limitations.

### 1.7.6 Explainability

AI-mediated outcomes should be explainable.

The product should retain logs, rationale, or resolution traces sufficient for:

* player trust
* creator debugging
* internal QA
* future replay/audit tools

The AI DM may be flexible, but it must not feel arbitrary.

---

## 1.8 Rails, Freedom, and World State

### 1.8.1 Authored rails are real

The main campaign should have explicit authored structure.

This includes:

* major plot beats
* major locations
* key NPCs
* intended encounter and scene progression
* protected canon facts
* major branching endpoints where applicable

The product should not pretend there are no rails. Rails are part of the design.

### 1.8.2 Player freedom is also real

Players must be allowed to:

* ask open questions
* pursue alternate approaches
* create social and narrative divergence
* change outcomes through choice
* leave the intended path
* attempt actions the creator did not explicitly script

The product should behave more like a real tabletop session than like a locked branching menu tree.

### 1.8.3 Deviation model

The intended model is:

* authored structure provides the spine
* player initiative may create forks, detours, and side consequences
* the AI DM should help sustain those branches
* the world state should remember them

This means the product must support **forked persistent world state**, not only branch labels.

### 1.8.4 Detour rule

Optional detours should generally arise because the **player leads there**, not because the system constantly interrupts the mainline with unrelated procedural noise.

This is a key quality guardrail.

### 1.8.5 Persistent generated content

If the AI DM introduces material content such as:

* side NPCs
* side quests
* generated maps
* optional encounters
* narrative forks
* new facts that affect future play

that content should become part of save state when relevant.

Generated content is not disposable flavor if it changes the campaign.

---

## 1.9 Interaction Model

### 1.9.1 Options-first, freeform-second

The primary player interaction model should be **structured options**.

Freeform input should also be supported, but it should sit beneath or alongside the structured interface rather than replace it.

This is required for:

* clarity
* pacing
* accessibility
* tactical readability
* content quality control

### 1.9.2 Hidden translation layer

When a player types freeform input, the translation layer should usually be hidden.

The player should experience the game as responsive and natural, not as a visible intent parser.

### 1.9.3 Open conversation over authored structure

The product should support open-feeling conversation backed by authored dialogue and authored state where possible.

In practice, this means:

* creators can author dialogue structure and key outcomes
* the AI DM can smooth, expand, and bridge dialogue
* players can speak outside menu options
* the underlying authored structure still protects quality and canon

### 1.9.4 Text density

The product should avoid excessive prose.

Narration should be strong but controlled. The experience should feel like playing a game session, not reading a novel. Optional voice model integration may later support the presentation layer, but voice is not part of the core product identity.

---

## 1.10 Rules and Resolution Philosophy

### 1.10.1 Baseline rules stance

The starting point is **5e fidelity** in feel and core logic, especially in combat.

The goal is not loose fantasy combat. The goal is recognizably D&D-like tactical play.

### 1.10.2 Combat vs non-combat resolution

Combat should be comparatively strict and engine-grounded.

Social and exploration resolution may be looser, provided they remain:

* dice-grounded where appropriate
* consistent with creator policy
* understandable to players
* explainable after the fact

### 1.10.3 Non-combat adjudication

Outside strict combat, the AI DM may call for checks using a baked-in decision guide.

That guide should account for:

* action type
* difficulty
* context
* creator-defined policy
* world state
* character capability

The AI DM should feel like a real DM calling for a check, not a random generator inventing outcomes.

### 1.10.4 Trust over surprise

When fairness and surprise conflict, the product should prefer **fairness and trust**.

The product must not create the feeling that the AI is making things up just to be interesting.

---

## 1.11 Tone, Look, and Feel

### 1.11.1 Tone

The default tonal target is **classic high fantasy**.

Modules may vary in tone, but the base product should assume a coherent fantasy adventure tone rather than irony, parody, or genre chaos.

### 1.11.2 Visual identity

The target visual identity is:

* **painterly isometric** for tactical/exploration play
* **pixel-art or low-animation narrative scenes** for story presentation where appropriate

This identity should feel deliberate, stylized, and readable.

### 1.11.3 Presentation priorities

Presentation should prioritize:

1. tactical clarity
2. atmosphere
3. expressive range

The product should sit at the crossover point between:

* a board-game-readable tactics space
* a living fantasy place

### 1.11.4 Narration cadence

Major narration moments should be curated by the creator.

The AI DM should not constantly over-narrate. It should enhance key beats, not smother moment-to-moment play.

---

## 1.12 Creator Promise

The product is creator-authored at its core. Creator tooling is not an optional add-on; it is central to the product.

The creator promise is:

* a non-technical creator should be able to build meaningful adventure content
* creators should be able to author campaigns, scenes, encounters, rails, notes, and AI-DM behavior
* creators should be able to define improvisation boundaries
* creators should be able to decide what content may be generated at build time, session start, or live play
* creators should be able to build both precise authored content and controlled procedural templates

The creator experience should prioritize **precision over speed**. Fast creation matters, but not at the expense of authorial control and output quality.

---

## 1.13 Scope Guardrails

This section intentionally constrains the first product shape.

### 1.13.1 What the product is not

The product is not, in its initial form:

* a blank-board VTT
* a pure AI improvisation toy
* a totally unbounded open-world sandbox from day one
* a novel-like text adventure with light tactics attached
* a system where the AI casually overrides rules or canon

### 1.13.2 What v1 must prove

The first prove-out must show that:

* a creator-authored one-shot can be built and played
* the AI DM can make it feel like tabletop
* off-rail actions can be handled without obvious collapse
* tactical combat remains trustworthy
* save state can preserve meaningful consequences

### 1.13.3 Generated content quality rule

Authored mainline content must carry the highest quality bar.

Generated secondary content may be more variable, provided it is:

* coherent
* useful
* stateful when relevant
* subordinate to the main authored experience

### 1.13.4 Inference model rule

Local model inference is strategically important and compatible with the product vision. However, the first playable version must not depend on local GPU inference as a hard gate. The product should be architected to support both local and hosted model execution.

### 1.13.5 Safety and moderation note

User-input moderation and public-facing safety policy are not part of the core product-shape decision in this section. Those requirements must be specified separately before public release.

---

## 1.14 Success Criteria

Section 1 is satisfied when the product can credibly deliver the following experience:

* a player can enter a one-shot and feel like they are playing D&D with a real DM
* the AI DM feels like a DM, not a chatbot
* the authored adventure feels intentional and coherent
* the player can deviate from the expected path and still be meaningfully handled
* the world remembers those deviations
* the tactical game remains readable, fair, and trustworthy
* the player finishes a session wanting to know what happens next
* the creator feels they can shape both the authored content and the AI runtime behavior

A successful product should make players say:
**“That was fun. What happens next?”**

A successful creator experience should make creators exchange:
**practical tips on how to get the most out of the system**, not workarounds for a broken toolchain.

---

## 1.15 Final Definition

For the purposes of this specification package, the product shall be defined as:

> A creator-authored, painterly isometric digital D&D platform where an AI DM runs the session, preserves the spirit of tabletop play, supports meaningful player deviation, and keeps world consequences persistent, while the tactical rules engine remains authoritative for combat and other hard-mechanical systems.

That is the governing definition for all subsequent sections.
