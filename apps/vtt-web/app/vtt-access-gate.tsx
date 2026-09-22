"use client";

import { useId, useState, type FormEvent } from "react";

import { normalizeVttBearerToken } from "./vtt-transport";

export function VttAccessGate({
  error,
  pending,
  onConnect,
}: {
  error: string | null;
  pending: boolean;
  onConnect: (bearerToken: string) => Promise<void>;
}) {
  const [credential, setCredential] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const credentialId = useId();

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const bearerToken = normalizeVttBearerToken(credential);
      if (bearerToken === null) throw new Error("Enter a table credential.");
      setValidationError(null);
      await onConnect(bearerToken);
      setCredential("");
    } catch (submitError) {
      setValidationError(
        submitError instanceof Error
          ? submitError.message
          : "The table credential could not be used.",
      );
    }
  };

  return (
    <main className="state-screen access-screen">
      <form className="state-card access-card" onSubmit={submit}>
        <span className="access-glyph" aria-hidden="true">⌁</span>
        <p className="eyebrow">Protected table</p>
        <h1>Join a private table</h1>
        <p>
          Enter the private credential supplied by your Game Master. It is kept
          only in this page&apos;s memory and is never placed in a URL.
        </p>
        <label htmlFor={credentialId}>Table credential</label>
        <input
          id={credentialId}
          type="password"
          value={credential}
          onChange={(event) => setCredential(event.target.value)}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          disabled={pending}
          aria-invalid={Boolean(validationError || error)}
          autoFocus
        />
        {validationError || error ? (
          <p className="access-error" role="alert">
            {validationError ?? error}
          </p>
        ) : null}
        <button
          className="button button-primary"
          type="submit"
          disabled={pending || credential.length === 0}
        >
          {pending ? "Joining table…" : "Join table"}
        </button>
      </form>
    </main>
  );
}
