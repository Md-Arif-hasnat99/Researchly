import React from 'react';
import { Menu, Search, Upload } from 'lucide-react';
import { Button } from '../ui/Button';

interface HeaderProps {
  onOpenMobileMenu: () => void;
  onOpenUploadModal?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onOpenMobileMenu, onOpenUploadModal }) => {
  return (
    <header className="h-16 bg-surface border-b border-border flex items-center justify-between px-4 sm:px-6 z-10 flex-shrink-0">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onOpenMobileMenu}
          className="lg:hidden p-2 rounded-lg text-text-secondary hover:text-text-primary hover:bg-neutral-100"
          aria-label="Open navigation menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Global Search Bar */}
        <div className="relative hidden sm:block w-72 md:w-96">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="search"
            placeholder="Search papers, concepts, authors..."
            className="w-full bg-background border border-border rounded-lg pl-9 pr-4 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        {onOpenUploadModal && (
          <Button variant="primary" size="sm" onClick={onOpenUploadModal}>
            <Upload className="w-4 h-4" />
            <span className="hidden sm:inline">Upload Paper</span>
          </Button>
        )}
        <div className="flex items-center gap-2 pl-2 border-l border-border">
          <div className="w-8 h-8 rounded-full bg-neutral-200 text-text-primary text-xs font-medium flex items-center justify-center">
            AR
          </div>
        </div>
      </div>
    </header>
  );
};
