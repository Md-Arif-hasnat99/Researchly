import React from 'react';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Compass, Lightbulb, FileText } from 'lucide-react';

export const ResearchGaps: React.FC = () => {
  const gaps = [
    {
      id: 'g-1',
      title: 'Context Length vs. Attention Complexity Trade-off',
      category: 'Methodological Bottleneck',
      paper: 'Attention Is All You Need',
      page: 6,
      description:
        'Standard full self-attention scales quadratically O(n²) with sequence length, severely limiting direct context scaling to whole books or long scientific document collections.',
      recommendation:
        'Investigate sparse attention, linear attention approximations, or hierarchical chunk representations.',
    },
    {
      id: 'g-2',
      title: 'Retriever Freshness and Hallucination Fallbacks',
      category: 'Systemic Reliability',
      paper: 'Retrieval-Augmented Generation for NLP Tasks',
      page: 8,
      description:
        'When retrieved passages fail to contain relevant facts, generators frequently default to non-factual hallucination rather than explicitly emitting uncertainty tokens.',
      recommendation:
        'Implement calibrated confidence gating and negative-constraint prompts during decoding.',
    },
  ];

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
            Research Gaps & Future Directions
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            Systematic extraction of unresolved problems, dataset constraints, and open questions.
          </p>
        </div>
        <Button variant="primary" size="md">
          <Compass className="w-4 h-4" /> Extract New Gaps
        </Button>
      </div>

      {/* Gaps List */}
      <div className="space-y-4">
        {gaps.map((gap) => (
          <Card key={gap.id} className="space-y-4 p-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
              <div className="flex items-center gap-2">
                <Badge variant="warning">{gap.category}</Badge>
                <div className="flex items-center gap-1 text-xs text-text-muted">
                  <FileText className="w-3.5 h-3.5" />
                  <span>{gap.paper} · Page {gap.page}</span>
                </div>
              </div>
              <span className="text-xs font-mono text-text-muted">ID: {gap.id}</span>
            </div>

            <div>
              <h3 className="text-base font-semibold text-text-primary">{gap.title}</h3>
              <p className="text-sm text-text-secondary mt-2 leading-relaxed">
                {gap.description}
              </p>
            </div>

            <div className="bg-neutral-50 border border-border/80 rounded-lg p-3.5 flex items-start gap-3">
              <Lightbulb className="w-4 h-4 text-warm flex-shrink-0 mt-0.5" />
              <div className="text-xs text-text-secondary leading-relaxed">
                <span className="font-semibold text-text-primary">Suggested Research Direction: </span>
                {gap.recommendation}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};
