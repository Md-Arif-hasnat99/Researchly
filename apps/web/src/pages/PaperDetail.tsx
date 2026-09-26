import React from 'react';
import { useParams, Link } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { FileText, Calendar, Hash, ArrowLeft } from 'lucide-react';
import { getPaper } from '../lib/api';
import type { Paper, PaperStatus } from '../types/paper';

function statusLabel(status: PaperStatus): string {
  switch (status) {
    case 'ready': return 'Ready';
    case 'processing': return 'Processing';
    case 'uploaded': return 'Queued';
    case 'failed': return 'Failed';
    default: return status;
  }
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

export const PaperDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [paper, setPaper] = React.useState<Paper | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    async function fetchPaper() {
      if (!id) return;
      try {
        setIsLoading(true);
        setError(null);
        const data = await getPaper(id);
        setPaper(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load paper.');
      } finally {
        setIsLoading(false);
      }
    }
    void fetchPaper();
  }, [id]);

  if (isLoading) {
    return (
      <div className="space-y-8 animate-fadeIn">
        <div className="flex items-center gap-4">
          <div className="h-8 w-8 bg-neutral-100 rounded animate-pulse" />
          <div className="h-6 w-48 bg-neutral-100 rounded animate-pulse" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="border border-border rounded-xl p-5 animate-pulse">
              <div className="h-3 bg-neutral-100 rounded w-20 mb-3" />
              <div className="h-8 bg-neutral-100 rounded w-3/4 mb-2" />
              <div className="h-4 bg-neutral-100 rounded w-1/2" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error || !paper) {
    return (
      <div className="space-y-8 animate-fadeIn">
        <Link to="/papers" className="inline-flex items-center gap-2 text-sm text-accent hover:text-accent-dark">
          <ArrowLeft className="w-4 h-4" /> Back to Papers
        </Link>
        <Card className="p-8 text-center">
          <FileText className="w-12 h-12 text-text-muted mx-auto mb-4 opacity-30" />
          <h2 className="text-xl font-semibold text-text-primary mb-2">Paper Not Found</h2>
          <p className="text-sm text-text-secondary mb-4">{error || 'The requested paper could not be loaded.'}</p>
          <Link to="/papers">
            <Button variant="primary" size="md">Back to Papers</Button>
          </Link>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Back & Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div className="flex items-center gap-4">
          <Link to="/papers" className="p-2 rounded-lg hover:bg-neutral-100 transition-colors" aria-label="Back to papers">
            <ArrowLeft className="w-5 h-5 text-text-muted" />
          </Link>
          <div>
            <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-text-primary">{paper.title}</h1>
            <p className="text-sm text-text-secondary mt-1">{paper.authors.join(', ')}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={paper.status === 'ready' ? 'success' : paper.status === 'failed' ? 'error' : 'warning'}>{statusLabel(paper.status)}</Badge>
        </div>
      </div>

      {/* Details Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <div className="flex items-center gap-3">
            <Calendar className="w-5 h-5 text-accent" />
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider">Published</p>
              <p className="text-sm font-semibold text-text-primary">{paper.publication_year ?? '—'}</p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <FileText className="w-5 h-5 text-accent" />
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider">Pages</p>
              <p className="text-sm font-semibold text-text-primary">{paper.total_pages ?? '—'}</p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <Hash className="w-5 h-5 text-accent" />
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider">Size</p>
              <p className="text-sm font-semibold text-text-primary">{formatBytes(paper.file_size)}</p>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <FileText className="w-5 h-5 text-accent" />
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider">Uploaded</p>
              <p className="text-sm font-semibold text-text-primary">{formatDate(paper.created_at)}</p>
            </div>
          </div>
        </Card>
      </div>

      {/* Abstract */}
      {paper.abstract && (
        <Card>
          <h3 className="text-sm font-semibold text-text-primary mb-2">Abstract</h3>
          <p className="text-sm text-text-secondary leading-relaxed">{paper.abstract}</p>
        </Card>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        <Link to="/chat" className="group">
          <Button variant="primary" size="md">
            Ask Questions About This Paper
          </Button>
        </Link>
        <Link to="/compare" className="group">
          <Button variant="secondary" size="md">Compare with Other Papers</Button>
        </Link>
      </div>
    </div>
  );
};