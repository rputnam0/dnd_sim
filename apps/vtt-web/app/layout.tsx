import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Echo Vault · Solo Table",
    template: "%s · Solo Table",
  },
  description:
    "A focused virtual tabletop for deterministic D&D combat in the original Echo Vault encounter.",
  applicationName: "Echo Vault Solo Table",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  openGraph: {
    title: "Echo Vault · Solo Table",
    description:
      "Preview, verify, and commit deterministic turns on an original 8×6 tactical grid.",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Echo Vault · Solo Table",
    description: "An arcane instrument panel for deterministic tactical play.",
  },
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#071514",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        {children}
      </body>
    </html>
  );
}
