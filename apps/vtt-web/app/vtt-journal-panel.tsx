"use client";

import {
  useId,
  useMemo,
  useState,
  type FormEvent,
} from "react";

import type { VttTableView } from "./vtt-access";
import { useVttJournal } from "./use-vtt-journal";
import {
  parseJournalDocument,
  type JournalBlock,
  type JournalDocument,
  type JournalFolder,
} from "./vtt-journal";

function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left, (character) => character.codePointAt(0) as number);
  const b = Array.from(right, (character) => character.codePointAt(0) as number);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

export function JournalDocumentContent({
  document,
  onOpenDocument,
}: {
  document: JournalDocument;
  onOpenDocument: (documentId: string) => void;
}) {
  return (
    <div className="journal-document-content">
      {document.blocks.map((block, index) => {
        const key = `${document.document_id}:${index}`;
        if (block.block_type === "paragraph") return <p key={key}>{block.text}</p>;
        if (block.block_type === "heading") {
          if (block.level === 1) return <h3 key={key}>{block.text}</h3>;
          if (block.level === 2) return <h4 key={key}>{block.text}</h4>;
          return <h5 key={key}>{block.text}</h5>;
        }
        if (block.block_type === "bullet_list") {
          return (
            <ul key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}:${itemIndex}`}>{item}</li>
              ))}
            </ul>
          );
        }
        return (
          <button
            type="button"
            className="journal-internal-link"
            onClick={() => onOpenDocument(block.document_id)}
            key={key}
          >
            {block.label}
          </button>
        );
      })}
    </div>
  );
}

export type VttJournalController = ReturnType<typeof useVttJournal>;

function paragraphBlock(): JournalBlock {
  return {
    schema_version: "vtt.journal_block.v1",
    block_type: "paragraph",
    text: "",
  };
}

function copyBlocks(blocks: JournalBlock[]): JournalBlock[] {
  return blocks.map((block) => {
    if (block.block_type === "bullet_list") return { ...block, items: [...block.items] };
    return { ...block };
  });
}

function descendantFolderIds(folders: JournalFolder[], parentId: string): Set<string> {
  const result = new Set([parentId]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const folder of folders) {
      if (
        folder.parent_folder_id !== null
        && result.has(folder.parent_folder_id)
        && !result.has(folder.folder_id)
      ) {
        result.add(folder.folder_id);
        changed = true;
      }
    }
  }
  return result;
}

function FolderTree({
  folders,
  parentId,
  selectedFolderId,
  canMutate,
  pendingDeleteFolderId,
  onSelect,
  onEdit,
  onRequestDelete,
  onConfirmDelete,
}: {
  folders: JournalFolder[];
  parentId: string | null;
  selectedFolderId: string | null;
  canMutate: boolean;
  pendingDeleteFolderId: string | null;
  onSelect: (folderId: string) => void;
  onEdit: (folder: JournalFolder) => void;
  onRequestDelete: (folderId: string) => void;
  onConfirmDelete: (folderId: string) => void;
}) {
  const children = folders.filter((folder) => folder.parent_folder_id === parentId);
  if (children.length === 0) return null;
  return (
    <ul className="journal-folders">
      {children.map((folder) => (
        <li key={folder.folder_id}>
          <div className="journal-folder-row">
            <button
              type="button"
              aria-pressed={selectedFolderId === folder.folder_id}
              onClick={() => onSelect(folder.folder_id)}
            >
              ▸ {folder.name}
            </button>
            <button
              type="button"
              disabled={!canMutate}
              aria-label={`Edit folder ${folder.name}`}
              onClick={() => onEdit(folder)}
            >
              Edit
            </button>
            <button
              type="button"
              disabled={!canMutate}
              aria-label={
                pendingDeleteFolderId === folder.folder_id
                  ? `Confirm delete folder ${folder.name}`
                  : `Delete folder ${folder.name}`
              }
              onClick={() => {
                if (pendingDeleteFolderId === folder.folder_id) onConfirmDelete(folder.folder_id);
                else onRequestDelete(folder.folder_id);
              }}
            >
              {pendingDeleteFolderId === folder.folder_id ? "Confirm" : "×"}
            </button>
          </div>
          <FolderTree
            folders={folders}
            parentId={folder.folder_id}
            selectedFolderId={selectedFolderId}
            canMutate={canMutate}
            pendingDeleteFolderId={pendingDeleteFolderId}
            onSelect={onSelect}
            onEdit={onEdit}
            onRequestDelete={onRequestDelete}
            onConfirmDelete={onConfirmDelete}
          />
        </li>
      ))}
    </ul>
  );
}

function updateBlock(
  blocks: JournalBlock[],
  index: number,
  replacement: JournalBlock,
): JournalBlock[] {
  return blocks.map((block, blockIndex) => blockIndex === index ? replacement : block);
}

export function VttJournalPanel({
  sessionId,
  bearerToken,
  table,
  controller,
  requestedDocumentId,
  activeSceneId,
  activeSceneOriginFt = [0, 0, 0],
  onDocumentSelect,
}: {
  sessionId: string;
  bearerToken: string | null;
  table: VttTableView;
  controller?: VttJournalController;
  requestedDocumentId?: string;
  activeSceneId?: string;
  activeSceneOriginFt?: [number, number, number];
  onDocumentSelect?: (documentId: string) => void;
}) {
  const ownedJournal = useVttJournal({
    sessionId: controller ? null : sessionId,
    tableId: controller ? null : table.table_id,
    bearerToken,
    participant: controller ? null : table.current_participant,
  });
  const journal = controller ?? ownedJournal;
  const [selectedId, setSelectedId] = useState("");
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [draftId, setDraftId] = useState("");
  const [documentType, setDocumentType] = useState<"note" | "handout">("handout");
  const [title, setTitle] = useState("");
  const [audienceSelectors, setAudienceSelectors] = useState<string[]>(["all"]);
  const [tags, setTags] = useState("");
  const [favorite, setFavorite] = useState(false);
  const [folderId, setFolderId] = useState("");
  const [blocks, setBlocks] = useState<JournalBlock[]>([paragraphBlock()]);
  const [pinEnabled, setPinEnabled] = useState(false);
  const [pinSceneId, setPinSceneId] = useState("");
  const [pinX, setPinX] = useState("0");
  const [pinY, setPinY] = useState("0");
  const [pinZ, setPinZ] = useState("0");
  const [pinColor, setPinColor] = useState("#5eead4");
  const [folderName, setFolderName] = useState("");
  const [folderParentId, setFolderParentId] = useState("");
  const [folderDraftId, setFolderDraftId] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [pendingDeleteFolderId, setPendingDeleteFolderId] = useState<string | null>(null);
  const titleId = useId();
  const queryId = useId();

  const selected = journal.documents.find((document) => document.document_id === requestedDocumentId)
    ?? journal.documents.find((document) => document.document_id === selectedId)
    ?? journal.documents[0]
    ?? null;
  const selectedFolderIds = selectedFolderId === null
    ? null
    : descendantFolderIds(journal.folders, selectedFolderId);
  const listedDocuments = selectedFolderIds === null
    ? journal.documents
    : journal.documents.filter(
      (document) => document.folder_id !== null && selectedFolderIds.has(document.folder_id),
    );
  const mapPins = useMemo(
    () => journal.documents.filter((document) => document.map_pin !== null),
    [journal.documents],
  );

  const openDocument = (documentId: string) => {
    setSelectedId(documentId);
    setPendingDeleteId(null);
    onDocumentSelect?.(documentId);
  };

  const beginNew = () => {
    setDraftId("");
    setDocumentType("handout");
    setTitle("");
    setAudienceSelectors(["all"]);
    setTags("");
    setFavorite(false);
    setFolderId(selectedFolderId ?? "");
    setBlocks([paragraphBlock()]);
    setPinEnabled(false);
    setPinSceneId(activeSceneId ?? "");
    setPinX(String(activeSceneOriginFt[0]));
    setPinY(String(activeSceneOriginFt[1]));
    setPinZ(String(activeSceneOriginFt[2]));
    setPinColor("#5eead4");
  };

  const beginEdit = (document: JournalDocument) => {
    setDraftId(document.document_id);
    setDocumentType(document.document_type);
    setTitle(document.title);
    setAudienceSelectors([...document.audience]);
    setTags(document.tags.join(", "));
    setFavorite(document.favorite);
    setFolderId(document.folder_id ?? "");
    setBlocks(copyBlocks(document.blocks));
    setPinEnabled(document.map_pin !== null);
    setPinSceneId(document.map_pin?.scene_id ?? activeSceneId ?? "");
    setPinX(String(document.map_pin?.position.x_ft ?? activeSceneOriginFt[0]));
    setPinY(String(document.map_pin?.position.y_ft ?? activeSceneOriginFt[1]));
    setPinZ(String(document.map_pin?.position.z_ft ?? activeSceneOriginFt[2]));
    setPinColor(document.map_pin?.color ?? "#5eead4");
  };

  const draft = useMemo(() => {
    try {
      const canonicalTags = tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean)
        .sort(compareCodePoints);
      if (pinEnabled && [pinX, pinY, pinZ].some((value) => value.trim() === "")) return null;
      return parseJournalDocument({
        schema_version: "vtt.journal_document.v1",
        document_id: draftId || "draft-document",
        document_type: documentType,
        folder_id: folderId || null,
        title,
        audience: audienceSelectors,
        tags: canonicalTags,
        favorite,
        blocks,
        map_pin: pinEnabled
          ? {
            schema_version: "vtt.journal_map_pin.v1",
            scene_id: pinSceneId,
            position: { x_ft: Number(pinX), y_ft: Number(pinY), z_ft: Number(pinZ) },
            color: pinColor,
          }
          : null,
      });
    } catch {
      return null;
    }
  }, [audienceSelectors, blocks, documentType, draftId, favorite, folderId, pinColor, pinEnabled, pinSceneId, pinX, pinY, pinZ, tags, title]);

  const save = (event: FormEvent) => {
    event.preventDefault();
    if (draft === null) return;
    const document = draftId ? draft : { ...draft, document_id: crypto.randomUUID() };
    void journal.saveDocument(document).then(() => {
      setSelectedId(document.document_id);
      setDraftId(document.document_id);
      onDocumentSelect?.(document.document_id);
    }).catch(() => undefined);
  };

  const createFolder = (event: FormEvent) => {
    event.preventDefault();
    const canonicalName = folderName.trim();
    if (!canonicalName) return;
    void journal.saveFolder({
      schema_version: "vtt.journal_folder.v1",
      folder_id: folderDraftId || crypto.randomUUID(),
      parent_folder_id: folderParentId || null,
      name: canonicalName,
    }).then(() => {
      setFolderName("");
      setFolderParentId("");
      setFolderDraftId("");
    }).catch(() => undefined);
  };

  const audienceChoices = useMemo(() => {
    const choices = [
      { label: "Everyone", selectors: ["all"] },
      { label: "All players", selectors: ["role:player"] },
      { label: "All spectators", selectors: ["role:spectator"] },
      ...table.participants.map((participant) => ({
        label: `Only ${participant.display_name}`,
        selectors: [`participant:${participant.participant_id}`],
      })),
    ];
    const current = JSON.stringify(audienceSelectors);
    if (!choices.some((choice) => JSON.stringify(choice.selectors) === current)) {
      choices.unshift({
        label: `Current sharing (${audienceSelectors.length} selectors)`,
        selectors: [...audienceSelectors],
      });
    }
    return choices;
  }, [audienceSelectors, table.participants]);

  const unavailableFolderParents = folderDraftId
    ? descendantFolderIds(journal.folders, folderDraftId)
    : new Set<string>();

  return (
    <section className="panel journal-panel" aria-labelledby={titleId}>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Campaign preparation</p>
          <h2 id={titleId}>Journal &amp; handouts</h2>
        </div>
        <span role="status" aria-live="polite">
          {journal.status === "live"
            ? `${journal.documents.length} visible documents`
            : journal.status === "loading" || journal.status === "connecting"
              ? "Loading journal…"
              : journal.status === "reconnecting"
                ? "Reconnecting journal…"
                : "Journal unavailable"}
        </span>
      </div>
      <label htmlFor={queryId}>Search visible journal</label>
      <input
        id={queryId}
        type="search"
        value={journal.query}
        maxLength={160}
        onChange={(event) => journal.setQuery(event.target.value)}
        placeholder="Title, tag, or text"
      />
      {journal.error ? (
        <div role="alert" className="journal-error">
          <p>{journal.error}</p>
          <button type="button" onClick={journal.retry}>Retry journal</button>
        </div>
      ) : null}
      <div className="journal-layout">
        <nav aria-label="Journal documents">
          {table.current_participant.role === "gm" ? (
            <>
              <button
                type="button"
                aria-pressed={selectedFolderId === null}
                onClick={() => setSelectedFolderId(null)}
              >
                All documents
              </button>
              <FolderTree
                folders={journal.folders}
                parentId={null}
                selectedFolderId={selectedFolderId}
                canMutate={journal.canMutate}
                pendingDeleteFolderId={pendingDeleteFolderId}
                onSelect={setSelectedFolderId}
                onEdit={(folder) => {
                  setFolderDraftId(folder.folder_id);
                  setFolderName(folder.name);
                  setFolderParentId(folder.parent_folder_id ?? "");
                }}
                onRequestDelete={setPendingDeleteFolderId}
                onConfirmDelete={(targetFolderId) => {
                  void journal.deleteFolder(targetFolderId).then(() => {
                    setPendingDeleteFolderId(null);
                    if (selectedFolderId === targetFolderId) setSelectedFolderId(null);
                  }).catch(() => undefined);
                }}
              />
            </>
          ) : null}
          <ul className="journal-document-list">
            {listedDocuments.map((document) => (
              <li key={document.document_id}>
                <button
                  type="button"
                  aria-pressed={selected?.document_id === document.document_id}
                  onClick={() => openDocument(document.document_id)}
                >
                  {document.favorite ? "★ " : ""}{document.title}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <article className="journal-reader" aria-live="polite">
          {selected ? (
            <>
              <header><span>{selected.document_type}</span><h3>{selected.title}</h3></header>
              <JournalDocumentContent document={selected} onOpenDocument={openDocument} />
              {table.current_participant.role === "gm" ? (
                <div className="journal-record-actions">
                  <button type="button" onClick={() => beginEdit(selected)}>Edit document</button>
                  <button
                    type="button"
                    disabled={!journal.canMutate}
                    onClick={() => {
                      if (pendingDeleteId === selected.document_id) {
                        void journal.deleteDocument(selected.document_id).then(() => {
                          setPendingDeleteId(null);
                          setSelectedId("");
                        }).catch(() => undefined);
                      } else {
                        setPendingDeleteId(selected.document_id);
                      }
                    }}
                  >
                    {pendingDeleteId === selected.document_id ? "Confirm delete document" : "Delete document"}
                  </button>
                </div>
              ) : null}
            </>
          ) : <p>No visible journal document matches this view.</p>}
        </article>
      </div>
      {mapPins.length > 0 ? (
        <p className="journal-pin-summary" role="status">
          {mapPins.length} visible map {mapPins.length === 1 ? "pin" : "pins"}
        </p>
      ) : null}
      {table.current_participant.role === "gm" ? (
        <>
          <form className="journal-folder-editor" onSubmit={createFolder}>
            <div className="journal-editor-heading">
              <h3>{folderDraftId ? "Edit folder" : "Folders"}</h3>
              {folderDraftId ? <button type="button" onClick={() => { setFolderDraftId(""); setFolderName(""); setFolderParentId(""); }}>New folder</button> : null}
            </div>
            <label>
              Folder name
              <input value={folderName} maxLength={160} onChange={(event) => setFolderName(event.target.value)} />
            </label>
            <label>
              Parent folder
              <select value={folderParentId} onChange={(event) => setFolderParentId(event.target.value)}>
                <option value="">Top level</option>
                {journal.folders.filter((folder) => !unavailableFolderParents.has(folder.folder_id)).map((folder) => <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>)}
              </select>
            </label>
            <button type="submit" disabled={!journal.canMutate || !folderName.trim()}>{folderDraftId ? "Save folder" : "Create folder"}</button>
          </form>
          <form className="journal-editor" onSubmit={save}>
            <div className="journal-editor-heading">
              <h3>{draftId ? "Edit document" : "New document"}</h3>
              <button type="button" onClick={beginNew}>New document</button>
            </div>
            <label>
              Title
              <input value={title} maxLength={160} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <div className="journal-editor-grid">
              <label>
                Type
                <select value={documentType} onChange={(event) => setDocumentType(event.target.value as "note" | "handout")}>
                  <option value="handout">Handout</option>
                  <option value="note">Note</option>
                </select>
              </label>
              <label>
                Audience
                <select value={JSON.stringify(audienceSelectors)} onChange={(event) => setAudienceSelectors(JSON.parse(event.target.value) as string[])}>
                  {audienceChoices.map((choice) => (
                    <option value={JSON.stringify(choice.selectors)} key={JSON.stringify(choice.selectors)}>{choice.label}</option>
                  ))}
                </select>
              </label>
              <label>
                Folder
                <select value={folderId} onChange={(event) => setFolderId(event.target.value)}>
                  <option value="">No folder</option>
                  {journal.folders.map((folder) => <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>)}
                </select>
              </label>
              <label>
                Tags, comma separated
                <input value={tags} maxLength={2_079} onChange={(event) => setTags(event.target.value)} />
              </label>
            </div>
            <label className="journal-check-row">
              <input type="checkbox" checked={favorite} onChange={(event) => setFavorite(event.target.checked)} />
              Favorite document
            </label>
            <fieldset className="journal-block-editor">
              <legend>Structured content blocks</legend>
              {blocks.map((block, index) => (
                <div className="journal-block-row" key={`${block.block_type}:${index}`}>
                  <span>{block.block_type.replace("_", " ")}</span>
                  {block.block_type === "paragraph" ? (
                    <label>
                      Paragraph text
                      <textarea
                        value={block.text}
                        rows={4}
                        maxLength={50_000}
                        onChange={(event) => setBlocks(updateBlock(blocks, index, { ...block, text: event.target.value }))}
                      />
                    </label>
                  ) : null}
                  {block.block_type === "heading" ? (
                    <div className="journal-editor-grid">
                      <label>
                        Heading level
                        <select value={block.level} onChange={(event) => setBlocks(updateBlock(blocks, index, { ...block, level: Number(event.target.value) as 1 | 2 | 3 }))}>
                          <option value={1}>1</option><option value={2}>2</option><option value={3}>3</option>
                        </select>
                      </label>
                      <label>
                        Heading text
                        <input value={block.text} maxLength={500} onChange={(event) => setBlocks(updateBlock(blocks, index, { ...block, text: event.target.value }))} />
                      </label>
                    </div>
                  ) : null}
                  {block.block_type === "bullet_list" ? (
                    <label>
                      Bullets, one per line
                      <textarea value={block.items.join("\n")} rows={4} onChange={(event) => setBlocks(updateBlock(blocks, index, { ...block, items: event.target.value.split("\n") }))} />
                    </label>
                  ) : null}
                  {block.block_type === "document_link" ? (
                    <div className="journal-editor-grid">
                      <label>
                        Linked document
                        <select value={block.document_id} onChange={(event) => setBlocks(updateBlock(blocks, index, { ...block, document_id: event.target.value }))}>
                          <option value="">Choose a projected document</option>
                          {journal.documents.filter((document) => document.document_id !== draftId).map((document) => (
                            <option value={document.document_id} key={document.document_id}>{document.title}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Link label
                        <input value={block.label} maxLength={500} onChange={(event) => setBlocks(updateBlock(blocks, index, { ...block, label: event.target.value }))} />
                      </label>
                    </div>
                  ) : null}
                  <button type="button" disabled={blocks.length === 1} onClick={() => setBlocks(blocks.filter((_item, blockIndex) => blockIndex !== index))}>Remove block</button>
                </div>
              ))}
              <div className="journal-block-actions">
                <button type="button" onClick={() => setBlocks([...blocks, { schema_version: "vtt.journal_block.v1", block_type: "heading", level: 2, text: "" }])}>Add heading</button>
                <button type="button" onClick={() => setBlocks([...blocks, paragraphBlock()])}>Add paragraph</button>
                <button type="button" onClick={() => setBlocks([...blocks, { schema_version: "vtt.journal_block.v1", block_type: "bullet_list", items: [""] }])}>Add bullets</button>
                <button type="button" onClick={() => setBlocks([...blocks, { schema_version: "vtt.journal_block.v1", block_type: "document_link", document_id: "", label: "" }])}>Add link</button>
              </div>
            </fieldset>
            <fieldset className="journal-pin-editor">
              <legend>Map pin</legend>
              <label className="journal-check-row">
                <input type="checkbox" checked={pinEnabled} disabled={!pinSceneId && !activeSceneId} onChange={(event) => setPinEnabled(event.target.checked)} />
                Pin this document to a scene
              </label>
              {pinEnabled ? (
                <div className="journal-editor-grid">
                  <label>Scene ID<input value={pinSceneId} readOnly /></label>
                  <label>X (ft)<input type="number" step="any" value={pinX} onChange={(event) => setPinX(event.target.value)} /></label>
                  <label>Y (ft)<input type="number" step="any" value={pinY} onChange={(event) => setPinY(event.target.value)} /></label>
                  <label>Z (ft)<input type="number" step="any" value={pinZ} onChange={(event) => setPinZ(event.target.value)} /></label>
                  <label>Pin color<input type="color" value={pinColor} onChange={(event) => setPinColor(event.target.value)} /></label>
                </div>
              ) : null}
            </fieldset>
            <button type="submit" disabled={!journal.canMutate || draft === null}>
              {journal.operation === "saving" ? "Saving…" : "Save document"}
            </button>
          </form>
        </>
      ) : null}
    </section>
  );
}
