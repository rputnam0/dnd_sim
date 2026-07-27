"use client";

import { useId, useState, type FormEvent } from "react";

import { useVttChat, type ChatConnectionStatus } from "./use-vtt-chat";
import { MAX_CHAT_TEXT_LENGTH } from "./vtt-chat";

function chatStatusLabel(status: ChatConnectionStatus, count: number): string {
  if (status === "loading") return "Loading messages…";
  if (status === "connecting") return "Connecting live chat…";
  if (status === "reconnecting") return "Chat reconnecting…";
  if (status === "unavailable") return "Chat unavailable";
  if (status === "error") return "Chat sync interrupted";
  return `${count} ${count === 1 ? "message" : "messages"} synced`;
}

export function VttChatPanel({ sessionId }: { sessionId: string }) {
  const chat = useVttChat(sessionId);
  const [draft, setDraft] = useState("");
  const titleId = useId();
  const composerId = useId();
  const counterId = useId();
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
      await chat.postMessage(submittedText);
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
                    <h3>{message.author_id}</h3>
                    {message.author_id === "local" ? (
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
        <label htmlFor={composerId}>Message the table</label>
        <textarea
          id={composerId}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={3}
          disabled={!chat.available}
          aria-invalid={characterCount > MAX_CHAT_TEXT_LENGTH}
          aria-describedby={counterId}
          placeholder={
            chat.status === "unavailable"
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
