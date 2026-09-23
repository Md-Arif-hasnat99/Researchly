import React, { useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Upload, Search, Trash2, Eye, Filter } from 'lucide-react';

export const Papers: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('');

  const papers = [
    {
      id: '1',
      title: 'Attention Is All You Need',
      authors: 'A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, et al.',
      year: 2017,
      pages: 15,
      status: 'ready' as const,
      size: '2.1 MB',
      createdAt: '2026-09-20',
    },
    {
      id: '2',
      title: 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks',
      authors: 'P. Lewis, E. Perez, A. Piktus, F. Petroni, et al.',
      year: 2020,
      pages: 19,
      status: 'ready' as const,
      size: '3.4 MB',
      createdAt: '2026-09-21',
    },
    {
      id: '3',
      title: 'Deep Residual Learning for Image Recognition',
      authors: 'K. He, X. Zhang, S. Ren, J. Sun',
      year: 2016,
      pages: 28,
      status: 'processing' as const,
      size: '4.8 MB',
      createdAt: '2026-09-23',
    },
  ];

  const filteredPapers = papers.filter((p) =>
    p.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    p.authors.toLowerCase().includes(searchQuery.toLowerCase())
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
            Manage your indexed scientific publications and extraction pipelines.
          </p>
        </div>
        <Button variant="primary" size="md">
          <Upload className="w-4 h-4" />
          Upload PDF
        </Button>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by title or author..."
            className="w-full bg-surface border border-border rounded-lg pl-9 pr-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="md">
            <Filter className="w-4 h-4" />
            Filter
          </Button>
        </div>
      </div>

      {/* Papers Table / Cards */}
      <div className="space-y-3">
        {filteredPapers.map((paper) => (
          <Card key={paper.id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 hover:border-accent/40 transition-colors">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <Badge variant={paper.status === 'ready' ? 'success' : 'warning'}>
                  {paper.status === 'ready' ? 'Ready' : 'Processing'}
                </Badge>
                <span className="text-xs text-text-muted font-mono">{paper.year}</span>
                <span className="text-xs text-text-muted">· {paper.pages} pages</span>
                <span className="text-xs text-text-muted">· {paper.size}</span>
              </div>
              <h3 className="text-base font-semibold text-text-primary truncate">
                {paper.title}
              </h3>
              <p className="text-xs text-text-secondary mt-0.5 truncate">{paper.authors}</p>
            </div>

            <div className="flex items-center gap-2 self-end sm:self-center">
              <Button variant="ghost" size="sm" aria-label="View paper">
                <Eye className="w-4 h-4" />
              </Button>
              <Button variant="ghost" size="sm" aria-label="Delete paper" className="hover:text-red-600">
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};
