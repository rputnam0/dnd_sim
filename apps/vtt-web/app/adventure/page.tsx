import type { Metadata } from "next";
import AdventurePlay from "../adventure-play";
import "../adventure.css";

export const metadata: Metadata = { title: "The Lantern Below", description: "Lead three companions through an original tabletop adventure beneath the harbor." };

export default function AdventurePage() { return <AdventurePlay />; }
