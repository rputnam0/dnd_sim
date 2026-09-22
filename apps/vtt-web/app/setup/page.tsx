import type { Metadata } from "next";
import { VttInstallationGate } from "../vtt-installation-gate";
import "../vtt-installation.css";

export const metadata: Metadata = {
  title: "World Administration",
  robots: { index: false, follow: false },
};

export default function InstallationPage() {
  return <VttInstallationGate />;
}
