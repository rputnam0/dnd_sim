"use client";

import { useId, useState, type FormEvent } from "react";

import { useVttChat, type ChatConnectionStatus } from "./use-vtt-chat";
import {
  chatAudienceChoices,
  type VttTableView,
} from "./vtt-access";
import { MAX_CHAT_TEXT_LENGTH } from "./vtt-chat";

function chatStatusLabel(status: ChatConnectionStatus, count: number): string {
  if (status === "loading") return "Loading messages…";
  if (status === "connecting") return "Connecting live chat…";
  if (status === "reconnecting") return "Chat reconnecting…";
  if (status === "unavailable") return "Chat unavailable";
  if (status === "error") return "Chat sync interrupted";
  return `${count} ${count === 1 ? "message" : "messages"} synced`;
}

function audienceLabel(audience: string[], table: VttTableView): string {
  if (audience.length === 1 && audience[0] === "all") return "Everyone";
  if (audience.length === 1 && audience[0] === "role:gm") {
    return "Game Masters";
  }
  if (audience.length === 1 && audience[0].startsWith("participant:")) {
    const participantId = audience[0].slice("participant:".length);
    const participant = table.participants.find(
      (candidate) => candidate.participant_id === participantId,
    );
    return participant ? `Direct · ${participant.display_name}` : "Private";
  }
  return "Restricted";
}

export function VttChatPanel({
  sessionId,
  bearerToken,
  table,
}: {
  sessionId: string;
  bearerToken: string | null;
  table: VttTableView;
}) {
  const chat = useVttChat({
    sessionId,
    bearerToken,
    participant: table.current_participant,
  });
  const [draft, setDraft] = useState("");
  const [audienceKey, setAudienceKey] = useState("public");
  const titleId = useId();
  const composerId = useId();
  const audienceId = useId();
  const counterId = useId();
  const audienceChoices = chatAudienceChoices(table);
  const selectedAudience =
    audienceChoices.find((choice) => choice.key === audienceKey) ??
    audienceChoices[0];
  const characterCount = Array.from(draft).length;
  const canSubmit =
    chat.canMutate &&
    draft.trim().length > 0 &&
    characterCount <= MAX_CHAT_TEXT_LENGTH;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    const submittedText = draft;
    try {
      await chat.postMessage(submittedText, selectedAudience.audience);
      setDraft((current) => (current === submittedText ? "" : current));
    } catch {
      // The hook keeps the exact draft and exposes actionable server guidance.
    }
  };

  return (
    <section className="panel chat-panel" aria-labelledby={titleId}>
      <div className="panel-heading chat-heading">
        <div>
          <p className="eyebrow">Shared table channel</p>
          <h2 id={titleId}>Plain-text chat</h2>
        </div>
        <span
          className={`chat-status chat-status-${chat.status}`}
          role="status"
          aria-live="polite"
        >
          <span aria-hidden="true" />
          {chatStatusLabel(chat.status, chat.messages.length)}
        </span>
      </div>

      <div
        className="chat-feed"
        role="log"
        aria-label="Table messages"
        aria-live="polite"
        aria-relevant="additions removals"
      >
        {chat.messages.length === 0 ? (
          <div className="chat-empty">
            <span aria-hidden="true">◇</span>
            <p>
              {chat.status === "unavailable"
                ? "This table has no chat service."
                : "No shared messages yet."}
            </p>
          </div>
        ) : (
          <ol className="chat-message-list">
            {chat.messages.map((message) => (
              <li className="chat-message" key={message.message_id}>
                <article>
                  <div className="chat-message-heading">
                    <div>
                      <h3>
                        {table.participants.find(
                          (participant) =>
                            participant.participant_id === message.author_id,
                        )?.display_name ?? message.author_id}
                      </h3>
                      <span className="chat-audience-label">
                        {audienceLabel(message.audience, table)}
                      </span>
                    </div>
                    {chat.canDeleteMessage(message.author_id) ? (
                      <button
                        className="chat-delete"
                        type="button"
                        disabled={!chat.canMutate}
                        onClick={() => {
                          void chat
                            .deleteMessage(message.message_id)
                            .catch(() => undefined);
                        }}
                        aria-label="Delete your message"
                      >
                        {chat.operation === "deleting" ? "Removing…" : "Delete"}
                      </button>
                    ) : null}
                  </div>
                  <p className="chat-message-text">{message.text}</p>
                </article>
              </li>
            ))}
          </ol>
        )}
      </div>

      {chat.error ? (
        <div
          className="chat-notice"
          role={chat.status === "unavailable" ? "status" : "alert"}
        >
          <p>{chat.error}</p>
          {chat.status === "error" || chat.status === "unavailable" ? (
            <button type="button" onClick={chat.retry}>
              Retry chat
            </button>
          ) : null}
        </div>
      ) : null}

      <form className="chat-composer" onSubmit={handleSubmit}>
        <div className="chat-composer-routing">
          <label htmlFor={composerId}>Message the table</label>
          <label htmlFor={audienceId}>
            Audience
            <select
              id={audienceId}
              value={selectedAudience.key}
              onChange={(event) => setAudienceKey(event.target.value)}
              disabled={!chat.canMutate}
            >
              {audienceChoices.map((choice) => (
                <option key={choice.key} value={choice.key}>
                  {choice.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <textarea
          id={composerId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={3}
          disabled={!chat.canMutate}
          aria-invalid={characterCount > MAX_CHAT_TEXT_LENGTH}
          aria-describedby={counterId}
          placeholder={
            table.current_participant.role === "spectator"
              ? "Spectators can read but cannot post"
              : chat.status === "unavailable"
              ? "Chat is not enabled"
              : "Write plain text…"
          }
        />
        <div className="chat-composer-footer">
          <span
            id={counterId}
            className={
              characterCount > MAX_CHAT_TEXT_LENGTH ? "is-over-limit" : undefined
            }
          >
            {characterCount} / {MAX_CHAT_TEXT_LENGTH}
          </span>
          <button
            className="button button-primary"
            type="submit"
            disabled={!canSubmit}
          >
            {chat.operation === "posting" ? "Sending…" : "Send message"}
          </button>
        </div>
      </form>
    </section>
  );
}
