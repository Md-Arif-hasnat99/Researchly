import React, { useCallback, useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { UploadModal } from '../components/papers/UploadModal';
import {
  Upload,
  Search,
  Trash2,
  Eye,
  FileText,
  Loader2,
  AlertCircle,
  BookOpen,
} from 'lucide-react';
import { listPapers, deletePaper } from '../lib/api';
import type { Paper, PaperStatus } from '../types/paper';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadgeVariant(status: PaperStatus) {
  switch (status) {
    case 'ready':
      return 'success';
    case 'processing':
    case 'uploaded':
      return 'warning';
    case 'failed':
      return 'error';
    default:
      return 'default';
  }
}

function statusLabel(status: PaperStatus): string {
  switch (status) {
    case 'ready':
      return 'Ready';
    case 'processing':
      return 'Processing';
    case 'uploaded':
      return 'Queued';
    case 'failed':
      return 'Failed';
    default:
      return status;
  }
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// ---------------------------------------------------------------------------
// Skeleton loader
// ---------------------------------------------------------------------------

const PaperSkeleton: React.FC = () => (
  <div className="border border-border rounded-xl p-4 animate-pulse flex gap-4 items-center">
    <div className="flex-1 space-y-2">
      <div className="h-3 bg-neutral-100 rounded w-24" />
      <div className="h-4 bg-neutral-100 rounded w-3/4" />
      <div className="h-3 bg-neutral-100 rounded w-1/2" />
    </div>
    <div className="flex gap-2">
      <div className="h-8 w-8 bg-neutral-100 rounded-lg" />
      <div className="h-8 w-8 bg-neutral-100 rounded-lg" />
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

const EmptyState: React.FC<{ onUpload: () => void }> = ({ onUpload }) => (
  <div className="flex flex-col items-center justify-center py-20 text-center gap-4">
    <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center">
      <BookOpen className="w-8 h-8 text-accent" />
    </div>
    <div>
      <h3 className="text-base font-semibold text-text-primary">No papers yet</h3>
      <p className="text-sm text-text-muted mt-1 max-w-xs">
        Upload your first research PDF to start building your indexed library.
      </p>
    </div>
    <Button variant="primary" size="md" onClick={onUpload} id="empty-upload-btn">
      <Upload className="w-4 h-4" />
      Upload PDF
    </Button>
  </div>
);

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const Papers: React.FC = () => {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [showUpload, setShowUpload] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Fetch papers on mount
  const fetchPapers = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const res = await listPapers();
      setPapers(res.papers);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load papers.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPapers();
  }, [fetchPapers]);

  // Handle successful upload
  const handleUploaded = (paper: Paper) => {
    setPapers((prev) => [paper, ...prev]);
  };

  // Delete with confirmation
  const handleDelete = async (paper: Paper) => {
    if (!window.confirm(`Delete "${paper.title}"? This cannot be undone.`)) return;
    setDeletingId(paper.id);
    try {
      await deletePaper(paper.id);
      setPapers((prev) => prev.filter((p) => p.id !== paper.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete paper.');
    } finally {
      setDeletingId(null);
    }
  };

  const filteredPapers = papers.filter(
    (p) =>
      p.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.authors.some((a) => a.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
            Research Library
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            {isLoading
              ? 'Loading your papers…'
              : `${papers.length} paper${papers.length !== 1 ? 's' : ''} indexed`}
          </p>
        </div>
        <Button
          variant="primary"
          size="md"
          onClick={() => setShowUpload(true)}
          id="upload-paper-btn"
        >
          <Upload className="w-4 h-4" />
          Upload PDF
        </Button>
      </div>

      {/* Search */}
      {!isLoading && papers.length > 0 && (
        <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by title or author…"
              className="w-full bg-surface border border-border rounded-lg pl-9 pr-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
              id="paper-search-input"
            />
          </div>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-2 text-rose-600 text-sm bg-rose-50 border border-rose-200 rounded-xl p-4">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
          <Button variant="ghost" size="sm" onClick={fetchPapers} className="ml-auto">
            Retry
          </Button>
        </div>
      )}

      {/* Loading skeletons */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <PaperSkeleton key={i} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && papers.length === 0 && (
        <EmptyState onUpload={() => setShowUpload(true)} />
      )}

      {/* Papers list */}
      {!isLoading && filteredPapers.length > 0 && (
        <div className="space-y-3">
          {filteredPapers.map((paper) => (
            <Card
              key={paper.id}
              className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 hover:border-accent/40 transition-colors"
            >
              <div className="flex gap-3 flex-1 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <FileText className="w-4 h-4 text-accent" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <Badge variant={statusBadgeVariant(paper.status)}>
                      {statusLabel(paper.status)}
                    </Badge>
                    {paper.publication_year && (
                      <span className="text-xs text-text-muted font-mono">
                        {paper.publication_year}
                      </span>
                    )}
                    {paper.total_pages && (
                      <span className="text-xs text-text-muted">· {paper.total_pages} pages</span>
                    )}
                    <span className="text-xs text-text-muted">· {formatBytes(paper.file_size)}</span>
                    <span className="text-xs text-text-muted">· {formatDate(paper.created_at)}</span>
                  </div>
                  <h3 className="text-base font-semibold text-text-primary truncate">
                    {paper.title}
                  </h3>
                  {paper.authors.length > 0 && (
                    <p className="text-xs text-text-secondary mt-0.5 truncate">
                      {paper.authors.join(', ')}
                    </p>
                  )}
                  {paper.status === 'failed' && paper.error_message && (
                    <p className="text-xs text-rose-600 mt-1">{paper.error_message}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 self-end sm:self-center flex-shrink-0">
                <Button variant="ghost" size="sm" aria-label="View paper details">
                  <Eye className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Delete paper"
                  className="hover:text-rose-600 hover:bg-rose-50"
                  onClick={() => handleDelete(paper)}
                  disabled={deletingId === paper.id}
                  id={`delete-paper-${paper.id}`}
                >
                  {deletingId === paper.id ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* No search results */}
      {!isLoading && papers.length > 0 && filteredPapers.length === 0 && (
        <div className="text-center py-12 text-sm text-text-muted">
          No papers match <span className="font-medium">"{searchQuery}"</span>
        </div>
      )}

      {/* Upload modal */}
      {showUpload && (
        <UploadModal onClose={() => setShowUpload(false)} onUploaded={handleUploaded} />
      )}
    </div>
  );
};
