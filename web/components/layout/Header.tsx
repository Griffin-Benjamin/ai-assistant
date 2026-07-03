"use client";

import { usePathname } from "next/navigation";
import { Settings } from "lucide-react";
import { Button } from "@/components/ui/Button";

const titleMap: Record<string, string> = {
  "/chat": "对话",
  "/knowledge": "知识库",
  "/tree": "知识树",
  "/personas": "人格",
  "/tasks": "任务",
};

export function Header() {
  const pathname = usePathname() || "";
  const title = titleMap[pathname] ?? "AI 学习助手";

  return (
    <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" aria-label="设置">
          <Settings className="w-4 h-4" />
        </Button>
      </div>
    </header>
  );
}
