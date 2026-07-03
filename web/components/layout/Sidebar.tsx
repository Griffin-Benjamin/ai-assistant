"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageSquare,
  BookOpen,
  Network,
  UserCircle,
  ListChecks,
} from "lucide-react";
import clsx from "clsx";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

const navItems: NavItem[] = [
  { label: "对话", href: "/chat", icon: MessageSquare },
  { label: "知识库", href: "/knowledge", icon: BookOpen },
  { label: "知识树", href: "/tree", icon: Network },
  { label: "人格", href: "/personas", icon: UserCircle },
  { label: "任务", href: "/tasks", icon: ListChecks },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-56 flex-col border-r border-gray-200 bg-white">
      <div className="px-4 py-5 border-b border-gray-200">
        <h1 className="text-lg font-semibold text-gray-900">AI 学习助手</h1>
        <p className="text-xs text-gray-500 mt-0.5">个人学习智能体</p>
      </div>

      <nav className="flex-1 px-2 py-3 space-y-1">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href || pathname?.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors",
                isActive
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-700 hover:bg-gray-100 hover:text-gray-900"
              )}
            >
              <Icon className="w-4 h-4" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-3 border-t border-gray-200 text-xs text-gray-400">
        v0.1.0
      </div>
    </aside>
  );
}
