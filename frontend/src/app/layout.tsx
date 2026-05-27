import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Conflux - Urban Intelligence Dashboard",
  description:
    "Transform citizen complaints from social media and public portals into structured, geospatially-aware infrastructure proposals.",
  openGraph: {
    title: "Conflux",
    description: "Civic-tech AI platform turning citizen feedback into urban intelligence.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
