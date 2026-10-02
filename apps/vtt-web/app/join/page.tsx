import type { Metadata } from "next";
import { VttJoinGate } from "../vtt-join-gate";
import "../vtt-installation.css";

export const metadata: Metadata = { title: "Join a world", robots: { index: false, follow: false } };
export default function JoinPage() { return <VttJoinGate />; }
