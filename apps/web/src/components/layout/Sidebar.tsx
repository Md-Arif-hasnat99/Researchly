import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FileText,
  MessageSquare,
  GitCompare,
  BookOpen,
  Compass,
  Settings,
  HelpCircle,
  Sparkles,
} from 'lucide-react';

interface SidebarProps {
  onCloseMobile?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ onCloseMobile }) => {
  const mainNav = [
    { name: 'Overview', to: '/dashboard', icon: LayoutDashboard },
    { name: 'Papers', to: '/papers', icon: FileText },
    { name: 'Chat', to: '/chat', icon: MessageSquare },
    { name: 'Compare', to: '/compare', icon: GitCompare },
    { name: 'Literature Review', to: '/literature-review', icon: BookOpen },
    { name: 'Research Gaps', to: '/research-gaps', icon: Compass },
  ];

  const secondaryNav = [
    { name: 'Settings', to: '/settings', icon: Settings },
  ];

  return (
    <aside className="w-64 h-full bg-surface border-r border-border flex flex-col flex-shrink-0 select-none">
      {/* Brand */}
      <div className="h-16 px-6 flex items-center gap-2.5 border-b border-border/60">
        <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center text-white font-semibold text-sm shadow-sm">
          <Sparkles className="w-4 h-4" />
        </div>
        <div className="flex flex-col">
          <span className="font-semibold text-text-primary text-base tracking-tight leading-none">
            Researchly
          </span>
          <span className="text-xs text-text-muted mt-1 leading-none">AI Research Assistant</span>
        </div>
      </div>

      {/* Main Navigation */}
      <div className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
        <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
          Workspace
        </div>
        {mainNav.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.name}
              to={item.to}
              onClick={onCloseMobile}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-accent-soft text-accent font-medium'
                    : 'text-text-secondary hover:text-text-primary hover:bg-neutral-50'
                }`
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span>{item.name}</span>
            </NavLink>
          );
        })}
      </div>

      {/* Footer Navigation */}
      <div className="p-3 border-t border-border/60 space-y-1">
        {secondaryNav.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.name}
              to={item.to}
              onClick={onCloseMobile}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-accent-soft text-accent font-medium'
                    : 'text-text-secondary hover:text-text-primary hover:bg-neutral-50'
                }`
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              <span>{item.name}</span>
            </NavLink>
          );
        })}

        <a
          href="https://github.com/Md-Arif-hasnat99/Researchly"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-text-secondary hover:text-text-primary hover:bg-neutral-50 transition-colors"
        >
          <HelpCircle className="w-4 h-4 flex-shrink-0" />
          <span>Documentation</span>
        </a>
      </div>
    </aside>
  );
};
