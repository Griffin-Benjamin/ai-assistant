import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 学习助手",
  description: "个人学习智能体 - 对话学习、知识沉淀、风格化回复",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        {children}
      </body>
    </html>
  );
}
