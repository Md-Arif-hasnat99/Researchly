import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Menu, Search, Upload, LogOut } from 'lucide-react';
import { Button } from '../ui/Button';
import { useAuth } from '../../context/AuthContext';

interface HeaderProps {
  onOpenMobileMenu: () => void;
  onOpenUploadModal?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onOpenMobileMenu, onOpenUploadModal }) => {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const [term, setTerm] = useState('');

  const initials = user?.user_metadata?.full_name
    ? user.user_metadata.full_name
        .split(' ')
        .map((n: string) => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : user?.email?.slice(0, 2).toUpperCase() ?? '??';

  // Hand the query to the search page, which owns the request.
  const runSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = term.trim();
    if (!trimmed) return;
    navigate(`/search?q=${encodeURIComponent(trimmed)}`);
    setTerm('');
  };

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

        {/* Global Search Bar — submits to the hybrid search page */}
        <form onSubmit={runSearch} className="relative hidden sm:block w-72 md:w-96" role="search">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="search"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Search papers, concepts, authors..."
            aria-label="Search your paper library"
            className="w-full bg-background border border-border rounded-lg pl-9 pr-4 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors"
          />
        </form>
      </div>

      <div className="flex items-center gap-3">
        {onOpenUploadModal && (
          <Button variant="primary" size="sm" onClick={onOpenUploadModal}>
            <Upload className="w-4 h-4" />
            <span className="hidden sm:inline">Upload Paper</span>
          </Button>
        )}
        <div className="flex items-center gap-2 pl-2 border-l border-border">
          <div
            className="w-8 h-8 rounded-full bg-neutral-200 text-text-primary text-xs font-medium flex items-center justify-center"
            title={user?.email}
          >
            {initials}
          </div>
          <button
            type="button"
            onClick={() => void signOut()}
            className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-neutral-100 transition-colors"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
};
