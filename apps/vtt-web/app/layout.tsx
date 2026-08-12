import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

function requestOrigin(requestHeaders: Headers): URL {
  const forwardedHost = requestHeaders.get("x-forwarded-host")?.split(",")[0]?.trim();
  const host = forwardedHost || requestHeaders.get("host") || "127.0.0.1:3000";
  const forwardedProtocol = requestHeaders
    .get("x-forwarded-proto")
    ?.split(",")[0]
    ?.trim();
  const protocol =
    forwardedProtocol === "http" || forwardedProtocol === "https"
      ? forwardedProtocol
      : host.startsWith("127.0.0.1") || host.startsWith("localhost")
        ? "http"
        : "https";
  try {
    return new URL(`${protocol}://${host}`);
  } catch {
    return new URL("http://127.0.0.1:3000");
  }
}

export async function generateMetadata(): Promise<Metadata> {
  const metadataBase = requestOrigin(await headers());
  const description =
    "An authoritative virtual tabletop for deterministic tactical play, shared scenes, chat, annotations, and live participant presence.";
  return {
    metadataBase,
    title: {
      default: "Echo Vault · Authoritative VTT",
      template: "%s · Echo Vault",
    },
    description,
    applicationName: "Echo Vault Authoritative VTT",
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
    },
    openGraph: {
      title: "Echo Vault · Authoritative Virtual Tabletop",
      description,
      type: "website",
      images: [
        {
          url: new URL("/og.png", metadataBase).toString(),
          width: 1_731,
          height: 909,
          alt: "Echo Vault authoritative virtual tabletop tactical map",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: "Echo Vault · Authoritative Virtual Tabletop",
      description,
      images: [new URL("/og.png", metadataBase).toString()],
    },
  };
}

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
