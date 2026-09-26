import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import {
  BookOpen,
  Copy,
  Check,
  Download,
  Loader2,
  AlertCircle,
  FileText,
  X,
  AlertTriangle,
} from 'lucide-react';
import { listPapers, generateLiteratureReview } from '../lib/api';
import type { Paper } from '../types/paper';
import type { LiteratureReviewResponse, ReviewSection } from '../types/research';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Mirrors DEFAULT_REVIEW_SECTIONS in apps/api/app/schemas/research.py */
const REVIEW_SECTIONS = [
  'Introduction',
  'Existing Approaches',
  'Methodological Trends',
  'Dataset Trends',
  'Results',
  'Limitations',
  'Research Gaps',
];

const MIN_PAPERS = 2;
const MAX_PAPERS = 10;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Render the review as Markdown for copy/export. */
function toMarkdown(review: LiteratureReviewResponse): string {
  const lines: string[] = [`# ${review.title}`, ''];
  review.sections.forEach((section, index) => {
    lines.push(`## ${index + 1}. ${section.heading}`);
    lines.push('');
    if (section.insufficient_context) {
      lines.push(
        '_Not enough retrieved context to write this section. Add relevant papers or narrow the focus._'
      );
    } else {
      lines.push(section.content);
      section.citations.forEach((citation) => {
        const where = citation.page_number ? ` (p.${citation.page_number})` : '';
        lines.push(`> Source: ${citation.paper_title}${where}`);
      });
    }
    lines.push('');
  });
  if (review.references.length > 0) {
    lines.push('## References');
    lines.push('');
    review.references.forEach((paper, index) => {
      const year = paper.publication_year ? ` (${paper.publication_year})` : '';
      lines.push(`${index + 1}. ${paper.paper_title}${year}`);
    });
    lines.push('');
  }
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
          : 'None of your papers have finished indexing. A review needs indexed papers.'}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Select {MIN_PAPERS}–{MAX_PAPERS} papers
        </span>
        <span className={`text-xs font-mono ${atLimit ? 'text-amber-600' : 'text-text-muted'}`}>
          {selected.length}/{MAX_PAPERS}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-64 overflow-y-auto">
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
              data-testid={`review-paper-${paper.id}`}
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
          and cannot be used yet.
        </p>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Generated document
// ---------------------------------------------------------------------------

const SectionBlock: React.FC<{ section: ReviewSection; index: number }> = ({
  section,
  index,
}) => (
  <section className="space-y-2" data-testid={`review-section-${index}`}>
    <h3 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
      {index + 1}. {section.heading}
    </h3>
    {section.insufficient_context ? (
      <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
        <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <span>
          Not enough retrieved context to write this section. Add papers covering this topic, or
          narrow the focus, then regenerate.
        </span>
      </div>
    ) : (
      <>
        <p className="text-sm text-text-secondary leading-relaxed whitespace-pre-wrap">
          {section.content}
        </p>
        {section.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-0.5">
            {section.citations.map((citation) => (
              <Badge key={`${citation.paper_id}-${citation.chunk_id ?? 'n'}`} variant="default">
                <FileText className="w-3 h-3 mr-1" />
                {citation.paper_title}
                {citation.page_number ? ` · p.${citation.page_number}` : ''}
              </Badge>
            ))}
          </div>
        )}
      </>
    )}
  </section>
);

const ReviewDocument: React.FC<{ review: LiteratureReviewResponse }> = ({ review }) => {
  const grounded = review.sections.filter((s) => !s.insufficient_context).length;

  return (
    <Card className="p-8 space-y-6 bg-surface border border-border shadow-xs">
      <div className="border-b border-border pb-4">
        <span className="text-xs uppercase tracking-wider font-semibold text-accent">
          Academic Synthesis
        </span>
        <h2 className="text-xl font-bold text-text-primary mt-1">{review.title}</h2>
        <p className="text-xs text-text-muted mt-1">
          Synthesized across {review.papers.length} source paper
          {review.papers.length !== 1 ? 's' : ''} · {grounded} of {review.sections.length} sections
          grounded
        </p>
      </div>

      {/* FR-12: generated synthesis must stay distinguishable from paper findings */}
      <div className="flex items-start gap-2 text-xs text-text-muted bg-neutral-50 border border-border rounded-lg p-3">
        <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
        <span>
          AI-generated synthesis. Section content is an interpretation across the selected papers,
          not a direct quotation or finding of any single paper. Verify against the cited pages
          before relying on it.
        </span>
      </div>

      {review.sections.map((section, index) => (
        <SectionBlock key={section.heading} section={section} index={index} />
      ))}

      {review.references.length > 0 && (
        <div className="pt-4 border-t border-border space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
            References
          </h3>
          <ol className="space-y-1 list-decimal list-inside">
            {review.references.map((paper) => (
              <li key={paper.paper_id} className="text-xs text-text-secondary">
                {paper.paper_title}
                {paper.publication_year ? ` (${paper.publication_year})` : ''}
              </li>
            ))}
          </ol>
        </div>
      )}
    </Card>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const LiteratureReview: React.FC = () => {
  const navigate = useNavigate();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [focus, setFocus] = useState('');
  const [review, setReview] = useState<LiteratureReviewResponse | null>(null);
  const [isLoadingPapers, setIsLoadingPapers] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const readyCount = useMemo(() => papers.filter((p) => p.status === 'ready').length, [papers]);
  const canGenerate = selected.length >= MIN_PAPERS && !isGenerating;

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
    setReview(null);
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canGenerate) return;
    try {
      setIsGenerating(true);
      setError(null);
      const body: Parameters<typeof generateLiteratureReview>[0] = { paper_ids: selected };
      if (title.trim()) body.title = title.trim();
      if (focus.trim()) body.focus = focus.trim();
      setReview(await generateLiteratureReview(body));
      setCopied(false);
    } catch (err) {
      setReview(null);
      setError(err instanceof Error ? err.message : 'Literature review generation failed.');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCopy = async () => {
    if (!review) return;
    try {
      await navigator.clipboard.writeText(toMarkdown(review));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Could not copy to clipboard.');
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn max-w-4xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
            Literature Review Generator
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            Synthesize your papers into a structured, source-traceable research narrative.
          </p>
        </div>
        {review && (
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="md" onClick={handleCopy} id="copy-markdown-btn">
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              {copied ? 'Copied' : 'Copy Markdown'}
            </Button>
            <Button
              variant="secondary"
              size="md"
              onClick={() =>
                download(
                  'researchly-literature-review.md',
                  toMarkdown(review),
                  'text/markdown'
                )
              }
              id="export-markdown-btn"
            >
              <Download className="w-4 h-4" />
              Export
            </Button>
          </div>
        )}
      </div>

      {/* Configuration */}
      <Card className="p-5">
        <form onSubmit={handleGenerate} className="space-y-5">
          {isLoadingPapers ? (
            <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
          ) : (
            <PaperPicker
              papers={papers}
              selected={selected}
              onToggle={togglePaper}
              disabled={isGenerating}
            />
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="review-title"
                className="block text-xs font-semibold text-text-muted uppercase tracking-wider mb-1.5"
              >
                Title <span className="normal-case font-normal">(optional)</span>
              </label>
              <input
                id="review-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Generated if left blank"
                disabled={isGenerating}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
              />
            </div>
            <div>
              <label
                htmlFor="review-focus"
                className="block text-xs font-semibold text-text-muted uppercase tracking-wider mb-1.5"
              >
                Focus <span className="normal-case font-normal">(optional)</span>
              </label>
              <input
                id="review-focus"
                type="text"
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
                placeholder="e.g. Evaluation methodology"
                disabled={isGenerating}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
              />
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
            <p className="text-xs text-text-muted">
              {REVIEW_SECTIONS.length} sections: {REVIEW_SECTIONS.slice(0, 3).join(', ')}, and more.
            </p>
            <Button
              type="submit"
              variant="primary"
              size="md"
              disabled={!canGenerate}
              id="generate-review-btn"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Generating…
                </>
              ) : (
                <>
                  <BookOpen className="w-4 h-4" />
                  {review ? 'Regenerate' : 'Generate Review'}
                </>
              )}
            </Button>
          </div>

          {!isLoadingPapers && readyCount > 0 && selected.length < MIN_PAPERS && (
            <p className="text-xs text-text-muted">
              Select at least {MIN_PAPERS} papers to generate a review.
            </p>
          )}
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
      {isGenerating && (
        <div className="space-y-3">
          <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
          <div className="h-72 animate-pulse bg-neutral-100 rounded-xl" />
        </div>
      )}

      {/* Result */}
      {!isGenerating && review && <ReviewDocument review={review} />}

      {/* Empty state */}
      {!isLoadingPapers && !isGenerating && !review && !error && readyCount < MIN_PAPERS && (
        <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center">
            {readyCount === 0 ? (
              <FileText className="w-8 h-8 text-accent" />
            ) : (
              <BookOpen className="w-8 h-8 text-accent" />
            )}
          </div>
          <div>
            <h3 className="text-base font-semibold text-text-primary">
              {readyCount === 0 ? 'No indexed papers' : 'Pick at least two papers'}
            </h3>
            <p className="text-sm text-text-muted mt-1 max-w-sm">
              {readyCount === 0
                ? 'A literature review needs at least two papers that have finished indexing.'
                : 'Select two or more papers above, then generate a structured synthesis.'}
            </p>
          </div>
          {readyCount === 0 && (
            <Button variant="secondary" size="md" onClick={() => navigate('/papers')}>
              Go to Research Library
            </Button>
          )}
        </div>
      )}
    </div>
  );
};
