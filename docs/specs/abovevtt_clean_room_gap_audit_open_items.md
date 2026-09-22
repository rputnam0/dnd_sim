# AboveVTT Clean-Room Gap Audit — Open Items

## Blocking Items

No evidence blocker prevents beginning the first implementation slice. Stable
capability claims are supported by official documentation, current local behavior
is verified from primary code, and the clean-room boundary is explicit.

| item_id | blocker_type | severity | due_phase | description | missing_evidence_or_decision | owner | unblock_condition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OI-000 | no_go | low | spec | No current blocking item. | n/a | product and engineering | Keep the no-go gates passing for each slice. |

## Non-Blocking Follow-Ups

| item_id | impact | severity | due_phase | description | proposed_next_step |
| --- | --- | --- | --- | --- | --- |
| OI-101 | high | high | implementation | Choose the first-party upload, remote URL, and optional provider policy for map and audio assets. | Threat-model SSRF, redirects, content limits, MIME detection, retention, and ownership before enabling remote fetch. |
| OI-102 | high | high | implementation | Define when active scene metadata becomes the running encounter scene and what happens to actors during transitions. | Write command-level state-transition examples for activate, reload, archive, and linked-scene travel. |
| OI-103 | high | high | implementation | Hex boards require topology, distance, footprint, template, pathing, and engine-rule decisions beyond rendering. | Create a dedicated hex rules spec and deterministic geometry fixtures before exposing hex play. |
| OI-104 | high | medium | implementation | Maintain reviewer/implementer separation for the clean-room process. | Record that implementers used these abstract artifacts, and require review for any new upstream-derived requirement. |
| OI-105 | medium | medium | implementation | Accessibility and performance budgets are not yet quantified for large maps, fog, animated media, or weather. | Set reduced-motion, keyboard, contrast, payload, reconnect, and frame-time gates during each UI slice. |
| OI-106 | low | medium | implementation | Peer audio/video and screen sharing have high privacy and operational cost. | Keep behind an optional integration boundary until core tabletop parity is accepted. |
| OI-107 | medium | medium | implementation | Full campaign package import/export depends on stable asset, token, visibility, journal, and content domains. | Define a versioned manifest after those schemas settle, then add round-trip and migration fixtures. |
| OI-108 | medium | low | implementation | Repo-only beta features such as weather, portals, DM screen, and advanced mixer controls may change before stable release. | Re-check official stable documentation when each candidate enters planning. |
| OI-109 | high | medium | implementation | Content/library parity can create licensing and provenance risk. | Accept only owned, licensed, user-authored, or clearly redistributable content; store provenance with imports. |
| OI-110 | medium | medium | implementation | Manual combat controls can contradict the engine’s legal state machine. | Define explicit engine commands for supported overrides and reject operations that cannot preserve replay invariants. |
