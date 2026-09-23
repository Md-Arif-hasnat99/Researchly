import React from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Sparkles, Copy, FileDown } from 'lucide-react';

export const LiteratureReview: React.FC = () => {
  return (
    <div className="space-y-6 animate-fadeIn max-w-4xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
            Literature Review Generator
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            Synthesize academic literature into an editorial, publication-ready research narrative.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="md">
            <Copy className="w-4 h-4" /> Copy Markdown
          </Button>
          <Button variant="primary" size="md">
            <Sparkles className="w-4 h-4" /> Generate New
          </Button>
        </div>
      </div>

      {/* Generated Review Document */}
      <Card className="p-8 space-y-6 bg-surface border border-border shadow-xs">
        <div className="border-b border-border pb-4">
          <span className="text-xs uppercase tracking-wider font-semibold text-accent">
            Academic Synthesis
          </span>
          <h2 className="text-xl font-bold text-text-primary mt-1">
            Evolution of Attention Mechanisms and Dense Retrieval in Modern NLP
          </h2>
          <p className="text-xs text-text-muted mt-1">
            Synthesized across 3 primary sources · September 2026
          </p>
        </div>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
            1. Introduction & Background
          </h3>
          <p className="text-sm text-text-secondary leading-relaxed">
            The transition from recurrent architectures to pure self-attention marked a paradigm shift in sequence transduction models (Vaswani et al., 2017). By eliminating sequential recurrence in favor of multi-head self-attention, computational efficiency during training increased substantially, allowing scaling to unprecedented corpus sizes.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
            2. Methodological Trends
          </h3>
          <p className="text-sm text-text-secondary leading-relaxed">
            Subsequent advances integrated non-parametric external memory directly into transformer decoders (Lewis et al., 2020). Rather than relying solely on parametric weights for factual knowledge, retrieval-augmented architectures combine dense bi-encoders with seq2seq generation to achieve grounded inference.
          </p>
        </section>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
            3. Research Gaps & Identified Limitations
          </h3>
          <p className="text-sm text-text-secondary leading-relaxed">
            Despite remarkable empirical success, existing methods struggle with computational overhead for long sequences and retriever index synchronization under dynamic corpus updates.
          </p>
        </section>

        <div className="pt-4 border-t border-border flex items-center justify-between text-xs text-text-muted">
          <span>Formatted according to academic review guidelines</span>
          <Button variant="ghost" size="sm">
            <FileDown className="w-4 h-4" /> Export as PDF
          </Button>
        </div>
      </Card>
    </div>
  );
};
