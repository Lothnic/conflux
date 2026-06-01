import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Conflux - AI Urban Planning Assistant",
  description:
    "Investigate civic issues on a geospatial operations map and generate evidence-backed urban planning recommendations.",
  openGraph: {
    title: "Conflux",
    description: "AI urban planning assistant for civic issue analysis and recommendations.",
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
