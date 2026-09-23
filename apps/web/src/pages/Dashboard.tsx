import React from 'react';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { FileText, MessageSquare, CheckCircle, ArrowRight, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';

export const Dashboard: React.FC = () => {
  const stats = [
    { title: 'Papers Indexed', count: '12', icon: FileText, change: '+2 this week' },
    { title: 'Chat Sessions', count: '28', icon: MessageSquare, change: '14 today' },
    { title: 'Ready for Synthesis', count: '12', icon: CheckCircle, change: '100% processed' },
  ];

  const recentPapers = [
    {
      id: 'p-1',
      title: 'Attention Is All You Need',
      authors: 'Vaswani, Shazeer, Parmar, et al.',
      year: 2017,
      pages: 15,
      status: 'ready' as const,
      uploadedAt: '2 hours ago',
    },
    {
      id: 'p-2',
      title: 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks',
      authors: 'Lewis, Perez, Piktus, et al.',
      year: 2020,
      pages: 19,
      status: 'ready' as const,
      uploadedAt: 'Yesterday',
    },
    {
      id: 'p-3',
      title: 'BERT: Pre-training of Deep Bidirectional Transformers',
      authors: 'Devlin, Chang, Lee, Toutanova',
      year: 2018,
      pages: 16,
      status: 'ready' as const,
      uploadedAt: '3 days ago',
    },
  ];

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

      {/* Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.title} className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-text-muted uppercase tracking-wider">
                  {stat.title}
                </p>
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
          <Link
            to="/papers"
            className="text-xs font-medium text-accent hover:text-accent-dark inline-flex items-center gap-1 transition-colors"
          >
            View all library <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {recentPapers.map((paper) => (
            <Card key={paper.id} interactive className="flex flex-col justify-between h-44">
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-xs font-mono text-text-muted">PDF</span>
                  <Badge variant="success">Ready</Badge>
                </div>
                <h3 className="text-sm font-semibold text-text-primary line-clamp-2 leading-snug">
                  {paper.title}
                </h3>
                <p className="text-xs text-text-secondary mt-1.5 line-clamp-1">{paper.authors}</p>
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-border/50 text-xs text-text-muted">
                <span>{paper.year} · {paper.pages} pages</span>
                <span>{paper.uploadedAt}</span>
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* Quick Launch Actions */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
        <Link to="/chat" className="group">
          <Card interactive className="h-full border-dashed hover:border-solid hover:border-accent">
            <h4 className="text-sm font-medium text-text-primary group-hover:text-accent transition-colors">
              Ask Grounded Questions
            </h4>
            <p className="text-xs text-text-secondary mt-1">
              Query single or multiple papers with exact citation page tracking.
            </p>
          </Card>
        </Link>
        <Link to="/compare" className="group">
          <Card interactive className="h-full border-dashed hover:border-solid hover:border-accent">
            <h4 className="text-sm font-medium text-text-primary group-hover:text-accent transition-colors">
              Compare Methodologies
            </h4>
            <p className="text-xs text-text-secondary mt-1">
              Synthesize structured comparison tables across models, datasets, and metrics.
            </p>
          </Card>
        </Link>
        <Link to="/research-gaps" className="group">
          <Card interactive className="h-full border-dashed hover:border-solid hover:border-accent">
            <h4 className="text-sm font-medium text-text-primary group-hover:text-accent transition-colors">
              Detect Research Gaps
            </h4>
            <p className="text-xs text-text-secondary mt-1">
              Extract unresolved challenges, limitations, and future work opportunities.
            </p>
          </Card>
        </Link>
      </div>
    </div>
  );
};
