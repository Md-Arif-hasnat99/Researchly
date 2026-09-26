import React, { useCallback, useEffect, useState } from 'react';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { FileText, MessageSquare, CheckCircle, ArrowRight, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';
import { listPapers, listConversations } from '../lib/api';
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

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

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

export const Dashboard: React.FC = () => {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [conversations, setConversations] = useState<{ total: number }>({ total: 0 });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [papersRes, convRes] = await Promise.all([
        listPapers(),
        listConversations(),
      ]);
      setPapers(papersRes.papers);
      setConversations({ total: convRes.total });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);

  const readyCount = papers.filter((p) => p.status === 'ready').length;
  const recentPapers = papers.slice(0, 3);

  return (
    <div className="space-y-8 animate-fadeIn">
      {/* Editorial Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-text-primary">
            Research Workspace
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            Grounded synthesis, page-level evidence, and multi-paper comparative analysis.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/papers">
            <Button variant="primary" size="md">
              <Upload className="w-4 h-4" />
              Upload Research Paper
            </Button>
          </Link>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="flex items-center gap-2 text-rose-600 text-sm bg-rose-50 border border-rose-200 rounded-xl p-4">
          <span>{error}</span>
          <Button variant="ghost" size="sm" onClick={fetchData}>Retry</Button>
        </div>
      )}

      {/* Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { title: 'Papers Indexed', count: isLoading ? '...' : String(papers.length), icon: FileText, change: `${papers.length > 0 ? 'Loaded from library' : 'No papers yet'}` },
          { title: 'Chat Sessions', count: isLoading ? '...' : String(conversations.total), icon: MessageSquare, change: `${conversations.total > 0 ? 'Active conversations' : 'Start a new chat'}` },
          { title: 'Ready for Synthesis', count: isLoading ? '...' : String(readyCount), icon: CheckCircle, change: `${papers.length > 0 ? `${Math.round((readyCount / Math.max(papers.length, 1)) * 100)}% processed` : '—'}` },
        ].map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.title} className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-text-muted uppercase tracking-wider">{stat.title}</p>
                <p className="text-2xl font-semibold text-text-primary mt-1">{stat.count}</p>
                <p className="text-xs text-text-secondary mt-0.5">{stat.change}</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-neutral-50 border border-border/80 flex items-center justify-center text-text-secondary">
                <Icon className="w-5 h-5" />
              </div>
            </Card>
          );
        })}
      </div>

      {/* Recent Papers Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text-primary">Recent Papers</h2>
          <Link to="/papers" className="text-xs font-medium text-accent hover:text-accent-dark inline-flex items-center gap-1 transition-colors">
            View all library <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <PaperSkeleton key={i} />)}
          </div>
        ) : recentPapers.length === 0 ? (
          <div className="text-center py-12 text-sm text-text-muted">
            No papers yet. <Link to="/papers" className="text-accent hover:underline">Upload your first paper.</Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {recentPapers.map((paper) => (
              <Card key={paper.id} interactive className="flex flex-col justify-between h-44">
                <div>
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span className="text-xs font-mono text-text-muted">PDF</span>
                    <Badge variant={paper.status === 'ready' ? 'success' : paper.status === 'failed' ? 'error' : 'warning'}>{statusLabel(paper.status)}</Badge>
                  </div>
                  <h3 className="text-sm font-semibold text-text-primary line-clamp-2 leading-snug">{paper.title}</h3>
                  <p className="text-xs text-text-secondary mt-1.5 line-clamp-1">{paper.authors.join(', ')}</p>
                </div>
                <div className="flex items-center justify-between pt-3 border-t border-border/50 text-xs text-text-muted">
                  <span>{paper.publication_year} · {paper.total_pages} pages</span>
                  <span>{formatDate(paper.created_at)}</span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Quick Launch Actions */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
        <Link to="/chat" className="group">
          <Card interactive className="h-full border-dashed hover:border-solid hover:border-accent">
            <h4 className="text-sm font-medium text-text-primary group-hover:text-accent transition-colors">Ask Grounded Questions</h4>
            <p className="text-xs text-text-secondary mt-1">Query single or multiple papers with exact citation page tracking.</p>
          </Card>
        </Link>
        <Link to="/compare" className="group">
          <Card interactive className="h-full border-dashed hover:border-solid hover:border-accent">
            <h4 className="text-sm font-medium text-text-primary group-hover:text-accent transition-colors">Compare Methodologies</h4>
            <p className="text-xs text-text-secondary mt-1">Synthesize structured comparison tables across models, datasets, and metrics.</p>
          </Card>
        </Link>
        <Link to="/research-gaps" className="group">
          <Card interactive className="h-full border-dashed hover:border-solid hover:border-accent">
            <h4 className="text-sm font-medium text-text-primary group-hover:text-accent transition-colors">Detect Research Gaps</h4>
            <p className="text-xs text-text-secondary mt-1">Extract unresolved challenges, limitations, and future work opportunities.</p>
          </Card>
        </Link>
      </div>
    </div>
  );
};
