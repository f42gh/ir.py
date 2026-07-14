import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "EDINET 財務ダッシュボード",
    template: "%s | EDINET 財務ダッシュボード",
  },
  description: "EDINETの年次財務データを企業ごとに確認するダッシュボード",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
