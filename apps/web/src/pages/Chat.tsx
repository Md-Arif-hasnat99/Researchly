import React, { useState } from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Send, FileText, ExternalLink, Bookmark } from 'lucide-react';

export const Chat: React.FC = () => {
  const [input, setInput] = useState('');

  const messages = [
    {
      id: 'm-1',
      role: 'user' as const,
      content: 'What loss functions were evaluated in the Transformer paper for sequence transduction?',
      timestamp: '10:42 AM',
    },
    {
      id: 'm-2',
      role: 'assistant' as const,
      content:
        'The Transformer architecture utilized standard cross-entropy loss with label smoothing (smoothing parameter ε = 0.1) during training. The authors found that label smoothing hurts perplexity as the model learns to be more unsure, but improves accuracy and BLEU score.',
      timestamp: '10:42 AM',
      citations: [
        {
          id: 'c-1',
          paperTitle: 'Attention Is All You Need',
          page: 7,
          snippet: 'During training, we employed label smoothing of value εls = 0.1 (Szegedy et al., 2016).',
        },
      ],
    },
  ];

  return (
    <div className="h-[calc(100vh-8.5rem)] flex flex-col lg:flex-row gap-6">
      {/* Chat Transcript Panel */}
      <div className="flex-1 flex flex-col bg-surface border border-border rounded-xl overflow-hidden shadow-xs">
        {/* Chat Header */}
        <div className="px-5 py-3 border-b border-border flex items-center justify-between bg-neutral-50/50">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Research Assistant</h2>
            <p className="text-xs text-text-muted">Grounded against 2 indexed papers</p>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-text-secondary bg-surface border border-border px-2.5 py-1 rounded-md">
            <Bookmark className="w-3.5 h-3.5 text-accent" />
            <span>Attention Is All You Need + 1 other</span>
          </div>
        </div>

        {/* Message Stream */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}
            >
              <div
                className={`max-w-2xl rounded-xl p-4 text-sm leading-relaxed ${
                  m.role === 'user'
                    ? 'bg-accent text-white'
                    : 'bg-background border border-border text-text-primary'
                }`}
              >
                {m.content}
              </div>

              {/* Citations section if assistant */}
              {m.citations && m.citations.length > 0 && (
                <div className="mt-2.5 space-y-1.5 max-w-2xl w-full">
                  <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">
                    Source Evidence
                  </div>
                  {m.citations.map((c) => (
                    <div
                      key={c.id}
                      className="bg-neutral-50 border border-border rounded-lg p-2.5 text-xs text-text-secondary flex items-start justify-between gap-3 hover:border-accent/40 transition-colors"
                    >
                      <div>
                        <div className="font-medium text-text-primary flex items-center gap-1.5">
                          <FileText className="w-3.5 h-3.5 text-accent" />
                          <span>{c.paperTitle} · Page {c.page}</span>
                        </div>
                        <p className="italic text-text-muted mt-1 text-[11px]">"{c.snippet}"</p>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-text-muted flex-shrink-0 mt-0.5 hover:text-accent cursor-pointer" />
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Query Input */}
        <div className="p-4 border-t border-border bg-surface">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setInput('');
            }}
            className="flex items-center gap-2"
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your indexed papers..."
              className="flex-1 bg-background border border-border rounded-lg px-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
            />
            <Button type="submit" variant="primary" size="md">
              <Send className="w-4 h-4" />
            </Button>
          </form>
        </div>
      </div>

      {/* Source Inspector Panel (Desktop) */}
      <div className="hidden lg:flex w-80 flex-col bg-surface border border-border rounded-xl p-4 overflow-y-auto">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
          Referenced Papers
        </h3>
        <div className="space-y-3">
          <Card className="p-3 text-xs">
            <h4 className="font-semibold text-text-primary">Attention Is All You Need</h4>
            <p className="text-text-muted mt-1">Vaswani et al. (2017)</p>
            <div className="mt-2 text-[11px] text-accent font-medium">Page 7 active snippet</div>
          </Card>
        </div>
      </div>
    </div>
  );
};
