import type { Metadata } from "next";

import { EchoVaultTable } from "./echo-vault-table";

export const metadata: Metadata = {
  title: "Echo Vault",
  description:
    "A deterministic solo tactical table for the original Echo Vault encounter.",
};

export default function Home() {
  return <EchoVaultTable />;
}
