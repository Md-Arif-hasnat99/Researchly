import React from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Download, Plus } from 'lucide-react';

export const Compare: React.FC = () => {
  const comparisonData = [
    {
      aspect: 'Core Architecture',
      paperA: 'Stacked Self-Attention + Feed Forward (No Recurrence)',
      paperB: 'Dense Retriever + Sequence-to-Sequence Generator',
      paperC: 'Deep Residual Network with Skip Connections',
    },
    {
      aspect: 'Key Datasets',
      paperA: 'WMT 2014 English-to-German & English-to-French',
      paperB: 'Natural Questions, CuratedTREC, TriviaQA',
      paperC: 'ImageNet 1000-class, COCO Object Detection',
    },
    {
      aspect: 'Primary Evaluation Metric',
      paperA: 'BLEU score (28.4 on EN-DE)',
      paperB: 'Exact Match (EM) and F1 on Open-Domain QA',
      paperC: 'Top-1 / Top-5 Error Rate (3.57% top-5)',
    },
    {
      aspect: 'Stated Limitations',
      paperA: 'Quadratic computational complexity with sequence length',
      paperB: 'Retrieval index freshness and latency overhead',
      paperC: 'High GPU memory footprint during initial residual training',
    },
  ];

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
            Multi-Paper Comparative Synthesis
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            Evaluate architectures, methodologies, benchmarks, and limitations side-by-side.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="md">
            <Plus className="w-4 h-4" /> Add Paper
          </Button>
          <Button variant="primary" size="md">
            <Download className="w-4 h-4" /> Export Matrix
          </Button>
        </div>
      </div>

      {/* Comparison Matrix Table */}
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-left text-sm border-collapse">
          <thead>
            <tr className="border-b border-border bg-neutral-50/75">
              <th className="p-4 font-semibold text-text-muted text-xs uppercase tracking-wider w-1/4">
                Aspect
              </th>
              <th className="p-4 font-semibold text-text-primary w-1/4">
                Attention Is All You Need (2017)
              </th>
              <th className="p-4 font-semibold text-text-primary w-1/4">
                RAG for NLP Tasks (2020)
              </th>
              <th className="p-4 font-semibold text-text-primary w-1/4">
                Deep Residual Learning (2016)
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {comparisonData.map((row) => (
              <tr key={row.aspect} className="hover:bg-neutral-50/50 transition-colors">
                <td className="p-4 font-medium text-text-primary bg-neutral-50/25">
                  {row.aspect}
                </td>
                <td className="p-4 text-text-secondary text-xs leading-relaxed">
                  {row.paperA}
                </td>
                <td className="p-4 text-text-secondary text-xs leading-relaxed">
                  {row.paperB}
                </td>
                <td className="p-4 text-text-secondary text-xs leading-relaxed">
                  {row.paperC}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};
