# VTT Journal and Local Content Rules

## Clean-room boundary and outcome

This specification is derived only from this repository's clean-room feature
audit and existing authority/privacy architecture. It does not use upstream
source, assets, schemas, names, or visual expression.

The supported job is: a Game Master can organize original campaign notes and
player handouts in a searchable folder tree, share only selected documents,
link documents together, pin a shared document to a scene, reconnect safely,
and recover the same state after restart. The browser never interprets stored
HTML. Local actor/rules records and whole-table package import/export remain
separate, explicitly versioned slices that build on this journal aggregate.

## Authority and projection

- The SQLite journal aggregate is authoritative for folders, documents,
  ordering metadata, links, pins, and revision.
- Only a Game Master may create, replace, move, or delete journal records.
- Authentication precedes request, query, and reconnect-cursor validation.
- A protected reader receives only documents allowed by the existing table
  audience selectors. Folder names and unpublished document identities are GM
  preparation data and are absent from player/spectator projections.
- GM projections contain the canonical folder tree and all documents. Other
  roles receive a flat, deterministic visible-document list plus only visible
  map pins. Their document audience field contains only the selector(s) that
  matched the current principal, so unrelated participant or actor selectors
  do not leak; an internal link to a hidden/missing document is omitted rather
  than exposing its target identity.
- A public-to-private replacement emits a projected tombstone to a recipient
  who saw the prior document. Newly private title/body/link/pin data never
  crosses HTTP or SSE projection.

## Strict bounded records

- At most 256 active folders and 2,000 active documents exist per table.
- Folder depth is at most 16. IDs are canonical nonempty text up to 128 code
  points; titles/names are 1–160 canonical plain-text code points.
- A document is `note` or `handout`, has 0–32 sorted unique tags, a favorite
  flag, an optional folder ID, and 1–256 structured blocks.
- Supported rich blocks are headings (levels 1–3), paragraphs, bullet lists,
  and internal document links. All content is inert Unicode plain text. C0/C1
  controls are rejected except line feed in paragraphs; no HTML, markdown
  execution, remote embeds, scriptable URL, style, or filter is stored.
- Total visible text per document is at most 50,000 code points. A bullet list
  has 1–64 nonempty items. An internal link has a label and document ID; the
  target must exist after the same command and cannot self-link.
- A map pin is optional and contains a scene ID, finite feet-space point on the
  scene plane, and canonical lower-case color. It must fit the currently
  enumerated target scene map before commit. Pin visibility is exactly the
  document audience.
- Parent folders and document folder references must exist. Folder graphs are
  acyclic, bounded in depth, and a nonempty folder cannot be deleted. A
  document linked by another active document cannot be deleted until the link
  is removed, preventing silent broken preparation state.

## Search, ordering, and mutation

- Canonical views order folders by `(parent_folder_id, name, id)` and documents
  by `(favorite descending, title, id)`, comparing every string by Unicode
  code points. Search remains normalized and case-insensitive independently of
  presentation ordering.
- Search is local and deterministic over the authorized projection only. A
  canonical query of 1–160 code points is Unicode-normalized and casefolded;
  every whitespace-delimited query token must occur in the title, tags, or
  visible block text. The server enforces a maximum of 200 returned documents.
- Commands are strict, versioned, optimistic-revision checked, and idempotent
  by canonical command content. Put and delete are one-record mutations. No
  wildcard clear, recursive delete, audience-wide edit, or database-row escape
  hatch exists.
- Malformed, stale, unauthorized, cyclic, broken-link, off-board, or
  over-capacity commands leave revision and current projection unchanged and
  return a stable identity-free error.

## Browser and accessibility

- The journal panel exposes a labeled search input, folder/document tree for
  GMs, visible handout/note list for other roles, native create/edit controls,
  explicit save/delete, and connection state with retry.
- Structured blocks render as React text elements; internal links are buttons
  that select an already projected document. No stored content reaches
  `dangerouslySetInnerHTML`.
- Visible map pins are focusable buttons on the board, use document titles as
  accessible names, and open the corresponding projected document. Keyboard
  users can reach every control, activate links/pins with Enter or Space, and
  receive polite save/search status. Focus styles are visible and all motion
  obeys the existing reduced-motion rule.

## Exact acceptance evidence

- Contract tests reject extra fields, executable content, over-budget text,
  unsorted tags, broken/self links, invalid pins, and cyclic/deep folders.
- Store tests cover restart, exact retry, command collision, stale revision,
  capacity, nonempty/broken-link delete, corruption, deterministic search, and
  unchanged state on every rejection.
- Protected API tests cover auth-before-validation, GM-only writes,
  participant-specific GET/search/SSE, public-to-private tombstones, current
  scene pin bounds, hidden target-link omission, reconnect, and stable errors.
- Browser tests cover strict decoding, fail-closed three-part identity,
  authorized search, inert block rendering, tree/list selection, link and map
  pin keyboard activation, record-scoped update/delete, loading/error states,
  focus, and reduced motion.
- Solo restart tests prove the same folder/document/link/pin projection and
  exact retry after closing and reopening the composed app.
