import assert from "node:assert/strict";
import test from "node:test";
import { createElement, useState } from "react";
import TestRenderer, { act } from "react-test-renderer";

import {
  VttJournalPanel,
  type VttJournalController,
} from "../app/vtt-journal-panel";
import type { VttTableView } from "../app/vtt-access";
import type {
  JournalDocument,
  JournalFolder,
  JournalView,
} from "../app/vtt-journal";

const reactTestEnvironment: typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean } = globalThis;
reactTestEnvironment.IS_REACT_ACT_ENVIRONMENT = true;

const table: VttTableView = {
  schema_version: "vtt.table_view.v1",
  access_mode: "protected",
  table_id: "table-a",
  current_participant: {
    schema_version: "vtt.participant.v1",
    participant_id: "gm",
    display_name: "Game Master",
    role: "gm",
    owned_actor_ids: [],
  },
  participants: [
    {
      schema_version: "vtt.participant.v1",
      participant_id: "gm",
      display_name: "Game Master",
      role: "gm",
      owned_actor_ids: [],
    },
    {
      schema_version: "vtt.participant.v1",
      participant_id: "player",
      display_name: "Vela",
      role: "player",
      owned_actor_ids: ["vela_quill"],
    },
  ],
};

const loreFolder: JournalFolder = {
  schema_version: "vtt.journal_folder.v1",
  folder_id: "lore",
  parent_folder_id: null,
  name: "Lore",
};

const archiveFolder: JournalFolder = {
  schema_version: "vtt.journal_folder.v1",
  folder_id: "archive",
  parent_folder_id: null,
  name: "Archive",
};

const mapDocument: JournalDocument = {
  schema_version: "vtt.journal_document.v1",
  document_id: "vault-map",
  document_type: "handout",
  folder_id: "lore",
  title: "Vault Map",
  audience: ["all"],
  tags: ["map"],
  favorite: false,
  blocks: [{
    schema_version: "vtt.journal_block.v1",
    block_type: "paragraph",
    text: "Map text",
  }],
  map_pin: null,
};

const keyDocument: JournalDocument = {
  schema_version: "vtt.journal_document.v1",
  document_id: "vault-key",
  document_type: "handout",
  folder_id: "lore",
  title: "Vault Key",
  audience: ["participant:player", "role:gm"],
  tags: ["lore"],
  favorite: true,
  blocks: [
    { schema_version: "vtt.journal_block.v1", block_type: "heading", level: 2, text: "Northern seal" },
    { schema_version: "vtt.journal_block.v1", block_type: "paragraph", text: "Turn the glass key." },
    { schema_version: "vtt.journal_block.v1", block_type: "bullet_list", items: ["Listen", "Turn"] },
    { schema_version: "vtt.journal_block.v1", block_type: "document_link", document_id: "vault-map", label: "Open the map" },
  ],
  map_pin: {
    schema_version: "vtt.journal_map_pin.v1",
    scene_id: "echo-vault",
    position: { x_ft: 7.5, y_ft: 7.5, z_ft: 0 },
    color: "#5eead4",
  },
};

interface Observed {
  savedDocuments: JournalDocument[];
  deletedDocuments: string[];
  savedFolders: JournalFolder[];
  deletedFolders: string[];
}

function Harness({ observe }: { observe: (value: Observed) => void }) {
  const [documents, setDocuments] = useState([keyDocument, mapDocument]);
  const [folders, setFolders] = useState([archiveFolder, loreFolder]);
  const [query, setQuery] = useState("");
  const [savedDocuments, setSavedDocuments] = useState<JournalDocument[]>([]);
  const [deletedDocuments, setDeletedDocuments] = useState<string[]>([]);
  const [savedFolders, setSavedFolders] = useState<JournalFolder[]>([]);
  const [deletedFolders, setDeletedFolders] = useState<string[]>([]);

  const report = (next: Partial<Observed>) => observe({
    savedDocuments: next.savedDocuments ?? savedDocuments,
    deletedDocuments: next.deletedDocuments ?? deletedDocuments,
    savedFolders: next.savedFolders ?? savedFolders,
    deletedFolders: next.deletedFolders ?? deletedFolders,
  });
  const view: JournalView = {
    schema_version: "vtt.journal_view.v1",
    session_id: "session-a",
    table_id: "table-a",
    revision: 1,
    folders,
    documents,
  };
  const controller = {
    view,
    documents,
    folders,
    status: "live",
    error: null,
    query,
    operation: null,
    available: true,
    canMutate: true,
    setQuery,
    saveDocument: async (document: JournalDocument) => {
      const nextDocuments = [...documents.filter((item) => item.document_id !== document.document_id), document];
      const nextSaved = [...savedDocuments, document];
      setDocuments(nextDocuments);
      setSavedDocuments(nextSaved);
      report({ savedDocuments: nextSaved });
    },
    deleteDocument: async (documentId: string) => {
      const nextDeleted = [...deletedDocuments, documentId];
      setDocuments(documents.filter((document) => document.document_id !== documentId));
      setDeletedDocuments(nextDeleted);
      report({ deletedDocuments: nextDeleted });
    },
    saveFolder: async (folder: JournalFolder) => {
      const nextSaved = [...savedFolders, folder];
      setFolders([...folders.filter((item) => item.folder_id !== folder.folder_id), folder]);
      setSavedFolders(nextSaved);
      report({ savedFolders: nextSaved });
    },
    deleteFolder: async (folderId: string) => {
      const nextDeleted = [...deletedFolders, folderId];
      setFolders(folders.filter((folder) => folder.folder_id !== folderId));
      setDeletedFolders(nextDeleted);
      report({ deletedFolders: nextDeleted });
    },
    retry: () => undefined,
  } as unknown as VttJournalController;
  return createElement(VttJournalPanel, {
    sessionId: "session-a",
    bearerToken: "test-token",
    table,
    controller,
    activeSceneId: "echo-vault",
    activeSceneOriginFt: [2.5, 2.5, 0],
  });
}

function buttonByText(root: TestRenderer.ReactTestInstance, text: string) {
  return root.findAllByType("button").find((button) =>
    button.children.some((child) => typeof child === "string" && child.includes(text)),
  );
}

function formByHeading(root: TestRenderer.ReactTestInstance, heading: string) {
  return root.findAllByType("form").find((form) =>
    form.findAllByType("h3").some((node) => node.children.includes(heading)),
  );
}

function blockRow(root: TestRenderer.ReactTestInstance, kind: string) {
  return root.findAllByProps({ className: "journal-block-row" }).find((row) =>
    row.findAllByType("span").some((node) => node.children.includes(kind)),
  );
}

test("mounted journal controls create folders and structured pinned documents then update and delete", async () => {
  let observed: Observed = {
    savedDocuments: [],
    deletedDocuments: [],
    savedFolders: [],
    deletedFolders: [],
  };
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(createElement(Harness, {
      observe: (value: Observed) => { observed = value; },
    }));
  });
  const root = renderer.root;

  const internalLink = buttonByText(root, "Open the map");
  assert.ok(internalLink);
  await act(async () => internalLink.props.onClick());
  assert.ok(root.findAllByType("h3").some((heading) => heading.children.includes("Vault Map")));

  const keyButton = buttonByText(root, "Vault Key");
  assert.ok(keyButton);
  await act(async () => keyButton.props.onClick());
  const edit = buttonByText(root, "Edit document");
  assert.ok(edit);
  await act(async () => edit.props.onClick());
  const titleInput = root.findAllByType("input").find((input) => input.props.value === "Vault Key");
  assert.ok(titleInput);
  await act(async () => titleInput.props.onChange({ target: { value: "Vault Key Revised" } }));
  const editForm = formByHeading(root, "Edit document");
  assert.ok(editForm);
  await act(async () => editForm.props.onSubmit({ preventDefault: () => undefined }));
  assert.equal(observed.savedDocuments.at(-1)?.title, "Vault Key Revised");
  assert.deepEqual(observed.savedDocuments.at(-1)?.audience, ["participant:player", "role:gm"]);
  assert.deepEqual(observed.savedDocuments.at(-1)?.blocks.map((block) => block.block_type), [
    "heading", "paragraph", "bullet_list", "document_link",
  ]);
  assert.equal(observed.savedDocuments.at(-1)?.map_pin?.scene_id, "echo-vault");

  await act(async () => buttonByText(root, "Vault Key Revised")?.props.onClick());
  await act(async () => buttonByText(root, "Edit document")?.props.onClick());
  const explicitAudience = formByHeading(root, "Edit document")?.findAllByType("select").find((select) =>
    select.findAllByType("option").some((option) => option.props.value === JSON.stringify(["role:player"])),
  );
  assert.ok(explicitAudience);
  await act(async () => explicitAudience.props.onChange({ target: { value: JSON.stringify(["role:player"]) } }));
  await act(async () => formByHeading(root, "Edit document")?.props.onSubmit({ preventDefault: () => undefined }));
  assert.deepEqual(observed.savedDocuments.at(-1)?.audience, ["role:player"]);
  assert.deepEqual(observed.savedDocuments.at(-1)?.blocks, keyDocument.blocks);
  assert.deepEqual(observed.savedDocuments.at(-1)?.map_pin, keyDocument.map_pin);

  const editLoreFolder = root.findByProps({ "aria-label": "Edit folder Lore" });
  await act(async () => editLoreFolder.props.onClick());
  const editFolderForm = formByHeading(root, "Edit folder");
  assert.ok(editFolderForm);
  await act(async () => editFolderForm.findByType("input").props.onChange({ target: { value: "Lore Revised" } }));
  await act(async () => editFolderForm.findByType("select").props.onChange({ target: { value: "archive" } }));
  await act(async () => editFolderForm.props.onSubmit({ preventDefault: () => undefined }));
  assert.deepEqual(observed.savedFolders.at(-1), {
    ...loreFolder,
    name: "Lore Revised",
    parent_folder_id: "archive",
  });

  const loreButton = buttonByText(root, "Lore Revised");
  assert.ok(loreButton);
  await act(async () => loreButton.props.onClick());
  const newDocument = buttonByText(root, "New document");
  assert.ok(newDocument);
  await act(async () => newDocument.props.onClick());
  const newFormBeforeEditing = formByHeading(root, "New document");
  assert.ok(newFormBeforeEditing);
  const blankTitle = newFormBeforeEditing.findAllByType("input").find((input) => input.props.value === "" && input.props.maxLength === 160);
  assert.ok(blankTitle);
  await act(async () => blankTitle.props.onChange({ target: { value: "Resonator Clue" } }));
  const typeSelect = newFormBeforeEditing.findAllByType("select").find((select) =>
    select.findAllByType("option").some((option) => option.props.value === "note"),
  );
  const audienceSelect = newFormBeforeEditing.findAllByType("select").find((select) =>
    select.findAllByType("option").some((option) => option.props.value === JSON.stringify(["role:player"])),
  );
  assert.ok(typeSelect);
  assert.ok(audienceSelect);
  await act(async () => typeSelect.props.onChange({ target: { value: "note" } }));
  await act(async () => audienceSelect.props.onChange({ target: { value: JSON.stringify(["role:player"]) } }));
  const tagsInput = newFormBeforeEditing.findAllByType("input").find((input) => input.props.maxLength === 2_079);
  assert.ok(tagsInput);
  await act(async () => tagsInput.props.onChange({ target: { value: "music, clue" } }));
  const favoriteInput = newFormBeforeEditing.findAllByType("input").find((input) => input.props.type === "checkbox");
  assert.ok(favoriteInput);
  await act(async () => favoriteInput.props.onChange({ target: { checked: true } }));
  const paragraph = blockRow(root, "paragraph");
  assert.ok(paragraph);
  await act(async () => paragraph.findByType("textarea").props.onChange({ target: { value: "A low chord opens the door." } }));
  await act(async () => buttonByText(root, "Add heading")?.props.onClick());
  const heading = blockRow(root, "heading");
  assert.ok(heading);
  await act(async () => heading.findByType("input").props.onChange({ target: { value: "Resonator" } }));
  await act(async () => buttonByText(root, "Add bullets")?.props.onClick());
  const bullets = blockRow(root, "bullet list");
  assert.ok(bullets);
  await act(async () => bullets.findByType("textarea").props.onChange({ target: { value: "Listen\nAnswer" } }));
  await act(async () => buttonByText(root, "Add link")?.props.onClick());
  const link = blockRow(root, "document link");
  assert.ok(link);
  await act(async () => link.findByType("select").props.onChange({ target: { value: "vault-map" } }));
  await act(async () => link.findByType("input").props.onChange({ target: { value: "Study the vault map" } }));
  const pinLabel = root.findAllByType("label").find((label) => label.children.includes("Pin this document to a scene"));
  assert.ok(pinLabel);
  await act(async () => pinLabel.findByType("input").props.onChange({ target: { checked: true } }));
  const newForm = formByHeading(root, "New document");
  assert.ok(newForm);
  await act(async () => newForm.props.onSubmit({ preventDefault: () => undefined }));
  const created = observed.savedDocuments.at(-1);
  assert.equal(created?.title, "Resonator Clue");
  assert.equal(created?.document_type, "note");
  assert.equal(created?.folder_id, "lore");
  assert.deepEqual(created?.audience, ["role:player"]);
  assert.deepEqual(created?.tags, ["clue", "music"]);
  assert.equal(created?.favorite, true);
  assert.deepEqual(created?.blocks.map((block) => block.block_type), [
    "paragraph", "heading", "bullet_list", "document_link",
  ]);
  assert.deepEqual(created?.map_pin?.position, { x_ft: 2.5, y_ft: 2.5, z_ft: 0 });

  await act(async () => buttonByText(root, "New folder")?.props.onClick());
  const folderForm = formByHeading(root, "Folders");
  assert.ok(folderForm);
  const folderInput = folderForm.findByType("input");
  await act(async () => folderInput.props.onChange({ target: { value: "Clues" } }));
  await act(async () => folderForm.props.onSubmit({ preventDefault: () => undefined }));
  assert.equal(observed.savedFolders.at(-1)?.name, "Clues");

  const deleteFolder = root.findByProps({ "aria-label": "Delete folder Clues" });
  await act(async () => deleteFolder.props.onClick());
  const confirmFolder = root.findByProps({ "aria-label": "Confirm delete folder Clues" });
  await act(async () => confirmFolder.props.onClick());
  assert.equal(observed.deletedFolders.at(-1), observed.savedFolders.at(-1)?.folder_id);

  const createdButton = buttonByText(root, "Resonator Clue");
  assert.ok(createdButton);
  await act(async () => createdButton.props.onClick());
  const deleteDocument = buttonByText(root, "Delete document");
  assert.ok(deleteDocument);
  await act(async () => deleteDocument.props.onClick());
  const confirmDocument = buttonByText(root, "Confirm delete document");
  assert.ok(confirmDocument);
  await act(async () => confirmDocument.props.onClick());
  assert.equal(observed.deletedDocuments.at(-1), created?.document_id);

  await act(async () => renderer.unmount());
});
