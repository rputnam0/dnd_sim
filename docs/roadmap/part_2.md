# Section 2. Current-State Audit and Stabilization

## 2.1 Purpose

This section defines how the current implementation is to be understood, what it already credibly provides, where it materially falls short of the product defined in Section 1, and what stabilization work must be completed before broader expansion.

Section 2 exists to prevent two failure modes:

1. treating the current repository as more complete than it is
2. beginning major platform expansion on top of an unstable or misleading foundation

This section is implementation-facing. It translates the product definition in Section 1 into an honest assessment of the current codebase and a stabilization mandate.

If the current implementation conflicts with Section 1, **Section 1 prevails**. The purpose of this section is to identify and close those gaps, not redefine the product around current limitations.

---

## 2.2 Scope of the Audit

This section evaluates the current codebase as the likely foundation for the first product shape described in Section 1.

The audit is concerned with four questions:

1. **What is already real and dependable?**
2. **What is partially implemented but not yet product-ready?**
3. **What is still absent or fundamentally misaligned with the product definition?**
4. **What must be stabilized before broader platform work should proceed?**

This section does **not** attempt to fully specify the future architecture of every subsystem. Those details belong in later sections. Its job is to establish the current truth and the minimum bar for moving forward safely.

---

## 2.3 Executive Assessment

### 2.3.1 Core conclusion

The current repository should be understood as:

> **a strong deterministic D&D-like simulation kernel with campaign and tooling primitives, but not yet a complete backend platform for the product defined in Section 1.**

This distinction is essential.

The current implementation is materially stronger than a toy combat simulator. It already contains meaningful rules execution, world-state handling, persistence, replay support, and a large automated test surface.

However, it is not yet the full product backend because it does not yet provide several of the defining capabilities required by Section 1, including:

* a governed AI DM runtime
* a true session/service backend for live play
* authored dialogue runtime
* safe creator-facing content boundaries
* module packaging and dependency/version contracts
* creator tooling suitable for non-technical authors
* a stable browser-facing runtime contract for play sessions

### 2.3.2 Practical interpretation

For planning purposes, the current repository should be treated as:

* **the candidate authoritative rules and simulation core**
* **a source of reusable campaign/runtime primitives**
* **a partial prototype of the future content/runtime stack**
* **not yet the complete v1 platform**

This means the next phase should not be “add lots of new product features directly onto the current codebase.”
The next phase should be “stabilize, clarify boundaries, and convert the current implementation into a trustworthy core that the product can safely grow around.”

---

## 2.4 Current Strengths

The current implementation has several real strengths that should be preserved and built upon.

### 2.4.1 Deterministic rules and combat foundation

The codebase already demonstrates a real authoritative simulation layer.

It includes meaningful support for:

* combat resolution
* turn structure
* action legality
* movement and positioning
* spells and effects
* concentration and conditions
* reactions and triggered behavior
* AI-facing tactical evaluation
* combat and simulation replay

This matters because Section 1 depends on **trustworthy tactical play**. The existing repo is already much closer to that requirement than most early game prototypes.

### 2.4.2 Campaign and world-state primitives

The current implementation includes more than isolated encounter logic.

It already has meaningful support for:

* world-state persistence
* flags and consequences
* faction state
* travel/time/light systems
* exploration-state handling
* encounter progression
* campaign save surfaces

These systems are not yet sufficient to satisfy the full long-term product vision, but they demonstrate that the project is already thinking in terms of ongoing campaign state rather than one-off skirmishes.

### 2.4.3 Replay, observability, and maintenance discipline

The project shows unusually strong engineering discipline for this stage.

There is already evidence of:

* replay infrastructure
* capability manifests and coverage reporting
* program tracking documents
* decomposition awareness
* regression harnesses
* a large automated test suite

That is strategically important. Section 1 requires explainability, trust, persistence, and future auditability. The current repo already contains seeds of those concerns.

### 2.4.4 Authoritative-kernel potential

Most importantly, the current repository is credible as the future **authoritative engine core**.

That is the highest-value asset in the current implementation.
It should be preserved.

---

## 2.5 What Is Only Partially Ready

Several parts of the current codebase are promising but not yet stable enough to be treated as finished platform foundations.

### 2.5.1 Exploration and non-combat interaction

The current implementation includes non-combat and exploration-related features, but they remain relatively narrow in scope compared with the product target.

There is evidence of support for interactions such as:

* traps
* locks
* containers
* searchable objects
* stealth/search/surprise-related flows

That is useful groundwork. However, it is still materially short of the broader authored-world interaction model required by Section 1 and later sections, including:

* richer scene interactions
* creator-authored world objects with controlled outcomes
* broader environmental trigger systems
* strong off-rail support outside combat
* dialogue-linked and quest-linked interactions

### 2.5.2 World consequence model

Persistent state primitives exist, but the system is not yet at the level required by Section 1’s long-term thesis.

In particular, the current implementation does not yet clearly demonstrate a generalized model for:

* persistent AI-generated side content
* forked narrative or world-state branches
* durable side NPCs and side quests introduced at runtime
* creator-governed canon protection with AI-mediated supplementation

This means the current repo has the beginnings of persistence, but not yet the full persistent-consequence model that the product vision depends on.

### 2.5.3 Content schema maturity

The current content/runtime model is still too loose in important places.

Some of the scenario surfaces remain closer to simulation fixtures than to a creator-facing, versioned content platform. In practical terms, this means:

* some structures are still too flexible or underspecified
* some content boundaries are not yet typed tightly enough
* schema surfaces are not yet clearly aligned to a future editor and validator workflow

This is acceptable in a research or internal-simulation phase. It is not yet acceptable for a stable creator platform.

### 2.5.4 First-party content readiness

The current repo contains useful sample content and scenarios, but it is not yet equivalent to a polished starter module proving the full product fantasy in the way Section 1 requires.

It is better understood as:

* development and regression content
* simulation fixtures
* internal proof material

not yet:

* a fully integrated one-shot experience proving authored structure, AI mediation, off-rail handling, and tactical trust together

---

## 2.6 What Is Currently Missing or Materially Misaligned

This section is critical. These are not minor follow-ups. These are major gaps between the current implementation and the product defined in Section 1.

### 2.6.1 No governed AI DM runtime

Section 1 defines the product around an AI DM role with explicit authority boundaries, creator control, canon protection, off-rail handling, and explainability.

The current repository does **not yet** provide that governed runtime role.

There may be adjacent tooling or dependencies, but the audited codebase does not yet constitute a real AI DM platform with:

* runtime role definition
* narration policy
* canon governance
* creator-controlled improvisation boundaries
* AI adjudication interfaces
* persistent AI-generated content integration
* explainability and audit surfaces specific to AI decisions

This is one of the largest gaps between the current repo and the product definition.

### 2.6.2 No true live session backend

Section 1 assumes a real digital product, including solo play, multiplayer party play, session continuity, and AI-hosted runtime behavior.

The current repo does not yet present a real live-service backend shape for that. It does not yet clearly provide:

* session gateway architecture
* browser-facing action APIs
* authoritative session rooms
* reconnect flows
* multiplayer synchronization contracts
* production-grade service boundaries between gateway, simulation, and persistence

The current codebase is therefore not yet a complete “backend” in the product sense. It is primarily a simulation and tooling codebase.

### 2.6.3 No authored dialogue runtime

Section 1 requires a product where authored story structure is primary and the AI DM supplements that structure.

That requires a real dialogue/runtime model. The current implementation does not yet appear to provide a first-class dialogue graph system with:

* authored nodes and outcomes
* protected canon beats
* AI smoothing and bridging
* structured/open conversation blending
* persistent downstream consequences

This is not a small missing feature. It is central to the authored-adventure identity of the product.

### 2.6.4 No creator-safe extensibility boundary

The current repository still allows extensibility patterns that are too open for the target product.

In particular, scenario-level or encounter-level Python extension hooks are fundamentally misaligned with the creator promise in Section 1.

The product requires:

* safe declarative authoring
* creator control without raw code injection
* explicit rules for what may be generated or improvised
* stable validation and versioning

A system that still relies on raw code hooks in authored content is not yet safe or appropriate for the intended creator platform.

### 2.6.5 No creator toolchain suitable for non-technical authors

Section 1 explicitly states that creator tooling is central and that non-technical creators should be able to produce meaningful content.

The current repository does not yet provide that toolchain. There is no evident complete system for:

* scene authoring
* dialogue authoring
* quest authoring
* AI-DM behavior tuning for creators
* content packaging/publishing flow
* validator-centered no-code content iteration

### 2.6.6 No stable product-facing module model

Section 1 implies a creator-authored platform with canon control, persistent content, and future reusability.

The current implementation does not yet appear to provide the fully formalized module system needed for that, including:

* module manifests
* engine compatibility declarations
* dependency versioning
* migration contracts
* stable packaging boundaries between engine, base content, authored modules, and save data

---

## 2.7 Current Quality and Reliability Problems

In addition to product-level gaps, the current snapshot contains concrete quality issues that must be fixed before expansion.

### 2.7.1 Test suite is not currently fully green

The audited snapshot collected a large number of tests and passed the overwhelming majority of them, which is a positive signal.

However, the suite is **not fully green**. There are current failures in areas including:

* capability report snapshot drift
* replay/golden-trace verification tooling
* replay CLI determinism tooling
* reporting generation
* sample scenario portability/content integrity

This means the current repo is promising, but not yet stable enough to serve as a clean baseline for aggressive expansion.

### 2.7.2 Environment and invocation inconsistency

There is evidence that some workflows behave differently depending on how they are invoked.

That is unacceptable for a foundational platform codebase.

A stable baseline requires that:

* documented commands work consistently
* subprocess-driven scripts work reliably
* local development and CI do not depend on hidden path assumptions
* core developer workflows do not vary silently by invocation style

### 2.7.3 Path portability problems

There is evidence of developer-machine path leakage in shipped or committed scenario/config content.

This is a hard reliability problem, not a cosmetic one.

If content, fixtures, or tools depend on local absolute paths, then:

* sample content is not truly portable
* regressions become misleading
* CI and downstream tooling become brittle
* the content model is not yet production-clean

### 2.7.4 Silent failure behavior in content loading

Some current loader behavior appears too forgiving in the wrong places.

A platform intended for creator-authored content must not silently ignore malformed or incompatible content in ways that later surface as confusing runtime failures.

This is especially important for:

* saved data
* content migrations
* scenario loading
* packaged content validation

Silent data skipping is acceptable only in very narrow, explicit compatibility shims. It must not be the default error model.

### 2.7.5 Reporting and tooling brittleness

Several failures occur in tooling and reporting rather than the core combat loop.

That is meaningful.
It suggests the simulation kernel may be stronger than some of the surrounding platform support surfaces.

This is good news in one sense, because it means the kernel may be sound.
It is bad news in another sense, because brittle tooling is exactly how teams lose trust in their foundations.

---

## 2.8 Architectural Risks

Even if all current test failures were fixed, there would still be larger structural risks that must be addressed.

### 2.8.1 Monolithic engine concentration

A large amount of core runtime behavior remains concentrated in a very large engine runtime module.

This is manageable for a narrow stage of development. It becomes a major liability once the team begins building:

* live backend services
* AI orchestration
* creator tooling
* more complex content schemas
* browser-facing runtime contracts

This concentration risk affects:

* maintainability
* onboarding
* regression isolation
* ownership clarity
* service extraction readiness

### 2.8.2 Unclear product boundaries inside the codebase

The current repo still blends several concerns that will eventually need stronger separation, including:

* authoritative rules execution
* scenario loading
* content authoring assumptions
* campaign persistence
* reporting and replay tooling
* prototype/runtime experimentation

That is acceptable during invention. It is not the right long-term structure for a shipping platform.

### 2.8.3 Simulation-first, product-second architecture

The current implementation appears to have grown from simulation and verification needs first.

That is a reasonable origin.
But it means the codebase is not yet fully shaped around:

* live product flows
* player-facing runtime contracts
* creator-facing authoring flows
* AI-hosted session behavior
* browser-service integration

This section explicitly recognizes that difference so later architecture can correct it.

---

## 2.9 Stabilization Mandate

The stabilization phase is not a feature-expansion phase.

Its purpose is to convert the current repository from an impressive and promising simulation codebase into a dependable **authoritative product core**.

Stabilization must accomplish five things:

1. make the current baseline truthful
2. make it portable
3. make it repeatable
4. make it safe to build on
5. make its boundaries explicit

This phase should be treated as mandatory.
No later section should assume a reliable foundation until Section 2 exit criteria are met.

---

## 2.10 Required Stabilization Workstreams

The stabilization phase should be organized into the following workstreams.

### 2.10.1 Baseline truthfulness and green main

The repository must reach a state where:

* the full supported test suite is green
* documentation accurately describes the repo’s status
* generated artifacts and snapshot expectations are current
* no workflow is described as passing if it is known to fail

The governing rule for this workstream is:

> **main must describe itself honestly**

### 2.10.2 Environment and portability hardening

The repository must stop depending on hidden local assumptions.

This includes:

* removal of developer-machine absolute paths
* consistent command invocation behavior
* reliable subprocess execution
* stable documented environment setup
* supported-version clarity for key dependencies

A clean checkout on a supported environment must behave like a first-class path, not an afterthought.

### 2.10.3 Content and data integrity hardening

All bundled and future content must load cleanly and fail explicitly when invalid.

This includes:

* fixing current scenario portability issues
* making content/schema incompatibilities explicit
* removing silent malformed-row handling where it obscures real breakage
* validating packaged sample content as real artifacts rather than informal fixtures
* ensuring saved and bundled data are migration-safe

### 2.10.4 Safe extension boundary enforcement

The current content/runtime model must be hardened so that creator-facing content does not rely on raw executable Python hooks.

This workstream must establish the principle that:

* creators author data
* the platform executes approved behavior
* arbitrary code injection is not a normal content path

If temporary internal-only escape hatches remain during development, they must be:

* clearly marked internal
* excluded from creator-facing promises
* isolated from the future public content model

### 2.10.5 Engine decomposition and contract definition

The engine core must become easier to reason about and extract into future service architecture.

This does not necessarily require immediate total refactoring, but it does require:

* clear subsystem boundaries
* documented ownership of core runtime domains
* extraction planning for oversized runtime modules
* typed contracts at the engine boundary
* reduction of accidental coupling between runtime and tooling layers

### 2.10.6 Replay, reporting, and observability reliability

The repo already contains strong seeds here. Stabilization must make them dependable.

This includes:

* fixing broken replay/golden-trace flows
* ensuring deterministic replay artifacts remain usable
* making reporting pipelines stable in supported environments
* preserving or improving traceability for debugging and trust

This workstream is important because later AI-DM explainability and session auditability will depend on it.

### 2.10.7 Persistence and migration safety

The product depends on meaningful persistent consequences.
That requires a much stronger persistence contract than an internal prototype can tolerate.

This workstream must ensure:

* save/state formats are explicit
* migrations are testable
* stale or invalid persisted data does not fail opaquely
* campaign/world-state persistence is trustworthy enough to build product UX around

### 2.10.8 Licensing and content provenance review

Before the codebase becomes a real product foundation, the project must have explicit understanding of:

* what rules/content data may be shipped
* what data is raw input versus distributable runtime content
* what licensing or rights assumptions still need cleanup
* what future content boundary the shipped product will rely on

This is not optional cleanup. It is a foundational product requirement.

---

## 2.11 Stabilization Non-Goals

To preserve focus, the stabilization phase must **not** be used as a pretext to build the rest of the product early.

The following are not stabilization goals:

* building the full AI DM runtime
* building the full browser client
* implementing full multiplayer services
* shipping the creator editor suite
* solving the entire authored dialogue system
* broadening supported content types for their own sake
* polishing presentation, art, or front-end feel
* expanding into the long-term open-world vision

Those belong in later sections.

Section 2 is about making the foundation trustworthy, not making the entire product exist immediately.

---

## 2.12 Go/No-Go Rule for Expansion

The project should **not** proceed into aggressive platform expansion until the stabilization mandate is substantially satisfied.

In practical terms, do not treat the current repo as the settled base for:

* AI DM orchestration
* browser session services
* creator toolchain development
* module marketplace or sharing workflows
* large-scale content authoring

until the repository has passed Section 2 exit criteria.

Otherwise, later work will accumulate on top of:

* inaccurate assumptions
* hidden environment dependencies
* unstable content boundaries
* unclear engine/service contracts

That would slow the project and increase rework.

---

## 2.13 Exit Criteria

Section 2 is complete when the following are true.

### 2.13.1 Reliability criteria

* the full supported suite is green
* key support tooling is green, including replay and reporting flows
* documented commands work as documented
* CI truthfully reflects the intended supported workflows

### 2.13.2 Portability criteria

* no shipped sample content depends on developer-local absolute paths
* clean-checkout usage works in a supported environment
* content loading behaves deterministically and explicitly

### 2.13.3 Boundary criteria

* creator-facing content paths do not depend on arbitrary Python execution
* the engine boundary is defined clearly enough for later service extraction
* current repo status is documented honestly as authoritative core versus not-yet-built product layers

### 2.13.4 Data criteria

* persistence formats are explicit
* migration behavior is test-covered
* malformed content and persisted state fail clearly enough for debugging

### 2.13.5 Program criteria

* the team can name, without ambiguity, which parts of the future product are already represented in the codebase and which are not
* later sections can build on a trustworthy baseline instead of reinterpretation

---

## 2.14 Final Interpretation of the Current Repository

For the purposes of this specification package, the current repository shall be treated as:

> **a partially stabilized authoritative simulation and campaign kernel that already contains significant value, but that still requires a formal stabilization phase before it can serve as the trusted foundation of the Section 1 product.**

It is not to be described as the full product backend yet.

It is to be preserved, hardened, bounded, and clarified so that later sections can safely specify:

* the authoritative engine core
* the session/service backend
* the content platform
* the adventure runtime
* the client contract
* the creator toolchain

without inheriting hidden instability.

---

## 2.15 Section 2 Summary

The current codebase is promising enough to justify continued investment.

It is not yet stable enough to justify unchecked expansion.

The correct next move is:

> **stabilize first, then expand with explicit boundaries.**

That is the governing conclusion of Section 2.
