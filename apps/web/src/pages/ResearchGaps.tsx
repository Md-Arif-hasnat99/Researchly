import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import {
  Compass,
  Lightbulb,
  FileText,
  Quote,
  Loader2,
  AlertCircle,
  X,
  Layers,
  Sparkles,
} from 'lucide-react';
import { listPapers, identifyResearchGaps } from '../lib/api';
import type { Paper } from '../types/paper';
import {
  GAP_CATEGORIES,
  type GapCategory,
  type GapResponse,
  type ResearchGap,
} from '../types/research';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MIN_PAPERS = 1;
const MAX_PAPERS = 10;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function categoryVariant(category: GapCategory) {
  switch (category) {
    case 'Limitation':
      return 'warning' as const;
    case 'Unresolved Problem':
      return 'error' as const;
    case 'Future Work':
      return 'outline' as const;
    case 'Dataset Limitation':
      return 'default' as const;
    case 'Methodological Gap':
      return 'success' as const;
    default:
      return 'default' as const;
  }
}

function toMarkdown(response: GapResponse): string {
  const lines: string[] = ['# Research Gaps & Future Directions', ''];
  if (response.summary) {
    lines.push(response.summary, '');
  }
  response.clusters.forEach((cluster) => {
    lines.push(`## ${cluster.category}`, '');
    cluster.gaps.forEach((gap) => {
      lines.push(`### ${gap.title}`);
      lines.push('');
      lines.push(gap.description);
      if (gap.evidence) {
        lines.push('', `> **Evidence from the papers:** ${gap.evidence}`);
      }
      if (gap.suggested_direction) {
        lines.push('', `**Suggested research direction (AI):** ${gap.suggested_direction}`);
      }
      const sources = gap.citations
        .map((c) => `${c.paper_title}${c.page_number ? ` (p.${c.page_number})` : ''}`)
        .join('; ');
      if (sources) lines.push('', `Sources: ${sources}`);
      lines.push('');
    });
  });
  lines.push(
    '_AI-generated observations derived from the selected papers. Verify against the cited sources._'
  );
  return lines.join('\n');
}

function download(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Paper picker
// ---------------------------------------------------------------------------

interface PaperPickerProps {
  papers: Paper[];
  selected: string[];
  onToggle: (id: string) => void;
  disabled?: boolean;
}

const PaperPicker: React.FC<PaperPickerProps> = ({ papers, selected, onToggle, disabled }) => {
  const ready = papers.filter((p) => p.status === 'ready');
  const unavailable = papers.filter((p) => p.status !== 'ready');
  const atLimit = selected.length >= MAX_PAPERS;

  if (ready.length === 0) {
    return (
      <div className="text-sm text-text-muted bg-neutral-50 border border-border rounded-xl p-4">
        {papers.length === 0
          ? 'No papers in your library yet.'
          : 'None of your papers have finished indexing. Gap analysis needs indexed papers.'}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Select up to {MAX_PAPERS} papers
        </span>
        <span className={`text-xs font-mono ${atLimit ? 'text-amber-600' : 'text-text-muted'}`}>
          {selected.length}/{MAX_PAPERS}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-56 overflow-y-auto">
        {ready.map((paper) => {
          const isSelected = selected.includes(paper.id);
          const blocked = atLimit && !isSelected;
          return (
            <button
              key={paper.id}
              type="button"
              onClick={() => onToggle(paper.id)}
              disabled={disabled || blocked}
              aria-pressed={isSelected}
              data-testid={`gap-paper-${paper.id}`}
              className={`
                flex items-start gap-3 p-3 rounded-xl border text-left transition-colors
                ${isSelected
                  ? 'border-accent bg-accent/5'
                  : 'border-border hover:border-accent/40 bg-surface'}
                ${blocked ? 'opacity-40 cursor-not-allowed' : ''}
              `}
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-text-primary truncate">{paper.title}</p>
                <p className="text-xs text-text-muted mt-0.5">
                  {paper.publication_year ? `${paper.publication_year} · ` : ''}
                  {paper.total_pages ? `${paper.total_pages} pages` : 'PDF'}
                </p>
              </div>
              {isSelected && <X className="w-4 h-4 text-accent flex-shrink-0 mt-0.5" />}
            </button>
          );
        })}
      </div>

      {unavailable.length > 0 && (
        <p className="text-xs text-text-muted">
          {unavailable.length} paper{unavailable.length !== 1 ? 's are' : ' is'} still processing
          and cannot be analysed yet.
        </p>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Gap card
// ---------------------------------------------------------------------------

const GapCard: React.FC<{ gap: ResearchGap }> = ({ gap }) => (
  <Card className="space-y-4 p-6" data-testid={`gap-card-${gap.title}`}>
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant={categoryVariant(gap.category)}>{gap.category}</Badge>
        {gap.recurrence > 1 && (
          <Badge variant="error" data-testid={`recurrence-${gap.title}`}>
            Raised in {gap.recurrence} papers
          </Badge>
        )}
      </div>
      <span className="text-xs text-text-muted flex items-center gap-1.5">
        <Sparkles className="w-3.5 h-3.5" />
        AI observation
      </span>
    </div>

    <div>
      <h3 className="text-base font-semibold text-text-primary">{gap.title}</h3>
      <p className="text-sm text-text-secondary mt-2 leading-relaxed">{gap.description}</p>
    </div>

    {gap.evidence && (
      <div className="bg-neutral-50 border border-border/80 rounded-lg p-3.5 flex items-start gap-3">
        <Quote className="w-4 h-4 text-accent flex-shrink-0 mt-0.5" />
        <div className="text-xs text-text-secondary leading-relaxed">
          <span className="font-semibold text-text-primary">From the papers: </span>
          {gap.evidence}
        </div>
      </div>
    )}

    {gap.suggested_direction && (
      <div className="bg-neutral-50 border border-border/80 rounded-lg p-3.5 flex items-start gap-3">
        <Lightbulb className="w-4 h-4 text-warm flex-shrink-0 mt-0.5" />
        <div className="text-xs text-text-secondary leading-relaxed">
          <span className="font-semibold text-text-primary">
            Suggested research direction (AI):{' '}
          </span>
          {gap.suggested_direction}
        </div>
      </div>
    )}

    {gap.citations.length > 0 && (
      <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-border/40">
        <FileText className="w-3.5 h-3.5 text-text-muted" />
        {gap.citations.map((citation) => (
          <span
            key={`${citation.paper_id}-${citation.chunk_id ?? 'n'}`}
            className="text-[11px] text-text-muted font-mono"
          >
            {citation.paper_title}
            {citation.page_number ? ` · p.${citation.page_number}` : ''}
          </span>
        ))}
      </div>
    )}
  </Card>
);

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const ResearchGaps: React.FC = () => {
  const navigate = useNavigate();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [categories, setCategories] = useState<GapCategory[]>([]);
  const [focus, setFocus] = useState('');
  const [result, setResult] = useState<GapResponse | null>(null);
  const [isLoadingPapers, setIsLoadingPapers] = useState(true);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const readyCount = useMemo(() => papers.filter((p) => p.status === 'ready').length, [papers]);
  const canAnalyze = selected.length >= MIN_PAPERS && !isAnalyzing;
  const totalGaps = result?.clusters.reduce((sum, c) => sum + c.gaps.length, 0) ?? 0;

  const fetchPapers = useCallback(async () => {
    try {
      setIsLoadingPapers(true);
      setError(null);
      const res = await listPapers();
      setPapers(res.papers);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load papers.');
    } finally {
      setIsLoadingPapers(false);
    }
  }, []);

  useEffect(() => {
    void fetchPapers();
  }, [fetchPapers]);

  const togglePaper = (id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((p) => p !== id);
      if (prev.length >= MAX_PAPERS) return prev;
      return [...prev, id];
    });
    setResult(null);
  };

  const toggleCategory = (category: GapCategory) => {
    setCategories((prev) =>
      prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category]
    );
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canAnalyze) return;
    try {
      setIsAnalyzing(true);
      setError(null);
      const body: Parameters<typeof identifyResearchGaps>[0] = { paper_ids: selected };
      if (categories.length > 0) body.categories = categories;
      if (focus.trim()) body.focus = focus.trim();
      setResult(await identifyResearchGaps(body));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : 'Gap analysis failed.');
    } finally {
      setIsAnalyzing(false);
    }
  };

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
        {result && (
          <Button
            variant="secondary"
            size="md"
            onClick={() =>
              download('researchly-research-gaps.md', toMarkdown(result), 'text/markdown')
            }
            id="export-gaps-btn"
          >
            <FileText className="w-4 h-4" />
            Export
          </Button>
        )}
      </div>

      {/* Configuration */}
      <Card className="p-5">
        <form onSubmit={handleAnalyze} className="space-y-5">
          {isLoadingPapers ? (
            <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
          ) : (
            <PaperPicker
              papers={papers}
              selected={selected}
              onToggle={togglePaper}
              disabled={isAnalyzing}
            />
          )}

          <div className="space-y-2">
            <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
              Gap types <span className="normal-case font-normal">(all if none selected)</span>
            </span>
            <div className="flex flex-wrap gap-2">
              {GAP_CATEGORIES.map((category) => {
                const active = categories.includes(category);
                return (
                  <button
                    key={category}
                    type="button"
                    onClick={() => toggleCategory(category)}
                    disabled={isAnalyzing}
                    aria-pressed={active}
                    data-testid={`gap-category-${category}`}
                    className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                      active
                        ? 'border-accent bg-accent/10 text-accent'
                        : 'border-border text-text-muted hover:border-accent/40 hover:text-text-secondary'
                    }`}
                  >
                    {category}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-end justify-between">
            <div className="flex-1">
              <label
                htmlFor="gaps-focus"
                className="block text-xs font-semibold text-text-muted uppercase tracking-wider mb-1.5"
              >
                Focus <span className="normal-case font-normal">(optional)</span>
              </label>
              <input
                id="gaps-focus"
                type="text"
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
                placeholder="e.g. Evaluation and reproducibility"
                disabled={isAnalyzing}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              size="md"
              disabled={!canAnalyze}
              id="analyze-gaps-btn"
            >
              {isAnalyzing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Analysing…
                </>
              ) : (
                <>
                  <Compass className="w-4 h-4" />
                  {result ? 'Re-analyse' : 'Extract Gaps'}
                </>
              )}
            </Button>
          </div>
        </form>
      </Card>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 text-rose-600 text-sm bg-rose-50 border border-rose-200 rounded-xl p-4">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{error}</span>
          <Button variant="ghost" size="sm" onClick={fetchPapers} className="ml-auto">
            Retry
          </Button>
        </div>
      )}

      {/* Loading */}
      {isAnalyzing && (
        <div className="space-y-3">
          <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
          <div className="h-40 animate-pulse bg-neutral-100 rounded-xl" />
          <div className="h-40 animate-pulse bg-neutral-100 rounded-xl" />
        </div>
      )}

      {/* Results */}
      {!isAnalyzing && result && (
        <div className="space-y-6">
          {/* FR-13: gaps must be labelled as AI-generated observations */}
          <div className="flex items-start gap-2 text-xs text-text-muted bg-neutral-50 border border-border rounded-lg p-3">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>
              These gaps are AI-generated observations inferred from the selected papers, not
              claims the authors made. Each one lists the sources it was derived from — verify
              against those pages before relying on it.
            </span>
          </div>

          {result.summary && (
            <Card className="p-5">
              <h2 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                Overview
              </h2>
              <p className="text-sm text-text-primary leading-relaxed">{result.summary}</p>
              <p className="text-xs text-text-muted mt-3">
                {totalGaps} gap{totalGaps !== 1 ? 's' : ''} across{' '}
                {result.clusters.length} categor{result.clusters.length !== 1 ? 'ies' : 'y'} ·{' '}
                {result.papers.length} paper{result.papers.length !== 1 ? 's' : ''} analysed
              </p>
            </Card>
          )}

          {result.clusters.map((cluster) => (
            <div key={cluster.category} className="space-y-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-muted flex items-center gap-2">
                <Layers className="w-4 h-4" />
                {cluster.category}
                <span className="text-xs font-mono font-normal">
                  ({cluster.gaps.length})
                </span>
              </h2>
              {cluster.gaps.map((gap) => (
                <GapCard key={gap.title} gap={gap} />
              ))}
            </div>
          ))}

          {totalGaps === 0 && (
            <Card className="py-12 text-center">
              <Compass className="w-8 h-8 text-text-muted mx-auto mb-3 opacity-40" />
              <h3 className="text-sm font-semibold text-text-primary">No gaps identified</h3>
              <p className="text-xs text-text-muted mt-1 max-w-sm mx-auto">
                The retrieved context did not contain enough acknowledged limitations or open
                questions to report a gap. Try adding more papers or setting a focus.
              </p>
            </Card>
          )}
        </div>
      )}

      {/* Empty state */}
      {!isLoadingPapers && !isAnalyzing && !result && !error && readyCount < MIN_PAPERS && (
        <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center">
            <FileText className="w-8 h-8 text-accent" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-text-primary">No indexed papers</h3>
            <p className="text-sm text-text-muted mt-1 max-w-sm">
              Gap analysis needs at least one paper that has finished indexing.
            </p>
          </div>
          <Button variant="secondary" size="md" onClick={() => navigate('/papers')}>
            Go to Research Library
          </Button>
        </div>
      )}

      {!isAnalyzing && !result && readyCount >= MIN_PAPERS && selected.length === 0 && (
        <p className="text-xs text-text-muted text-center">
          Select one or more papers to begin analysis.
        </p>
      )}
    </div>
  );
};
