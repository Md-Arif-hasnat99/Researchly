import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import {
  Scale,
  Download,
  Loader2,
  AlertCircle,
  Layers,
  FileText,
  X,
} from 'lucide-react';
import { listPapers, comparePapers } from '../lib/api';
import type { Paper } from '../types/paper';
import type { CompareResponse, CompareRow } from '../types/research';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Mirrors DEFAULT_ASPECTS in apps/api/app/schemas/research.py */
const DEFAULT_ASPECTS = [
  'Dataset',
  'Model',
  'Method',
  'Metrics',
  'Results',
  'Limitations',
];

const MAX_PAPERS = 6;
const MIN_PAPERS = 2;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a TSV export of the matrix for copy/paste into a spreadsheet. */
function toTsv(response: CompareResponse): string {
  const header = ['Aspect', ...response.papers.map((p) => p.paper_title)];
  const lines = [header, ...response.rows.map((r) => [r.aspect, ...rowCells(r, response)])];
  return lines.map((cells) => cells.map((c) => c.replace(/\t|\n/g, ' ')).join('\t')).join('\n');
}

/** Cell text aligned to the response's paper order, so columns never shift. */
function rowCells(row: CompareRow, response: CompareResponse): string[] {
  return response.papers.map((paper) => {
    const cell = row.cells.find((c) => c.paper_id === paper.paper_id);
    if (!cell || cell.not_reported) return 'Not reported';
    return cell.page_number ? `${cell.summary} (p.${cell.page_number})` : cell.summary;
  });
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
          : 'None of your papers have finished indexing. Comparison needs indexed papers.'}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Select {MIN_PAPERS}–{MAX_PAPERS} papers
        </span>
        <span
          className={`text-xs font-mono ${atLimit ? 'text-amber-600' : 'text-text-muted'}`}
        >
          {selected.length}/{MAX_PAPERS}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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
              data-testid={`compare-paper-${paper.id}`}
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
          and cannot be compared yet.
        </p>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Matrix
// ---------------------------------------------------------------------------

const ComparisonMatrix: React.FC<{ response: CompareResponse }> = ({ response }) => (
  <div className="space-y-6">
    {response.summary && (
      <Card className="p-5">
        <h2 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
          Cross-Paper Synthesis
        </h2>
        <p className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap">
          {response.summary}
        </p>
      </Card>
    )}

    <Card className="overflow-x-auto p-0">
      <table className="w-full text-left text-sm border-collapse">
        <thead>
          <tr className="border-b border-border bg-neutral-50/75">
            <th className="p-4 font-semibold text-text-muted text-xs uppercase tracking-wider w-1/5">
              Aspect
            </th>
            {response.papers.map((paper) => (
              <th
                key={paper.paper_id}
                className="p-4 font-semibold text-text-primary align-bottom min-w-48"
              >
                <div className="line-clamp-2">{paper.paper_title}</div>
                {paper.publication_year && (
                  <span className="text-xs font-mono font-normal text-text-muted">
                    {paper.publication_year}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {response.rows.map((row) => (
            <tr key={row.aspect} className="hover:bg-neutral-50/50 transition-colors">
              <td className="p-4 font-medium text-text-primary bg-neutral-50/25 align-top">
                {row.aspect}
              </td>
              {response.papers.map((paper) => {
                const cell = row.cells.find((c) => c.paper_id === paper.paper_id);
                if (!cell || cell.not_reported) {
                  return (
                    <td
                      key={paper.paper_id}
                      className="p-4 text-xs text-text-muted italic align-top"
                    >
                      Not reported
                    </td>
                  );
                }
                return (
                  <td
                    key={paper.paper_id}
                    className="p-4 text-text-secondary text-xs leading-relaxed align-top"
                  >
                    {cell.summary}
                    {cell.page_number && (
                      <span className="ml-1.5 text-[10px] font-mono text-accent whitespace-nowrap">
                        p.{cell.page_number}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>

    <p className="text-xs text-text-muted flex items-center gap-1.5">
      <FileText className="w-3.5 h-3.5" />
      {response.citations.length} source chunk{response.citations.length !== 1 ? 's' : ''} grounded
      this matrix. Every cell links back to a page in its paper.
    </p>
  </div>
);

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const Compare: React.FC = () => {
  const navigate = useNavigate();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [focus, setFocus] = useState('');
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [isLoadingPapers, setIsLoadingPapers] = useState(true);
  const [isComparing, setIsComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const readyCount = useMemo(() => papers.filter((p) => p.status === 'ready').length, [papers]);
  const canCompare = selected.length >= MIN_PAPERS && !isComparing;

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

  const handleCompare = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canCompare) return;
    try {
      setIsComparing(true);
      setError(null);
      const body: Parameters<typeof comparePapers>[0] = { paper_ids: selected };
      if (focus.trim()) body.focus = focus.trim();
      setResult(await comparePapers(body));
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : 'Comparison failed.');
    } finally {
      setIsComparing(false);
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-border pb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
            Multi-Paper Comparative Synthesis
          </h1>
          <p className="text-sm text-text-secondary mt-1">
            Evaluate datasets, methods, benchmarks, and limitations side-by-side.
          </p>
        </div>
        {result && (
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              size="md"
              onClick={() =>
                download('researchly-comparison.tsv', toTsv(result), 'text/tab-separated-values')
              }
              id="export-matrix-btn"
            >
              <Download className="w-4 h-4" />
              Export Matrix
            </Button>
            <Button
              variant="secondary"
              size="md"
              onClick={() => download('researchly-comparison.json', JSON.stringify(result, null, 2), 'application/json')}
            >
              JSON
            </Button>
          </div>
        )}
      </div>

      {/* Selector */}
      <Card className="p-5">
        <form onSubmit={handleCompare} className="space-y-5">
          {isLoadingPapers ? (
            <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
          ) : (
            <PaperPicker
              papers={papers}
              selected={selected}
              onToggle={togglePaper}
              disabled={isComparing}
            />
          )}

          <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-end">
            <div className="flex-1">
              <label
                htmlFor="compare-focus"
                className="block text-xs font-semibold text-text-muted uppercase tracking-wider mb-1.5"
              >
                Focus <span className="normal-case font-normal">(optional)</span>
              </label>
              <input
                id="compare-focus"
                type="text"
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
                placeholder="e.g. Compare their evaluation methodology"
                disabled={isComparing}
                className="w-full bg-surface border border-border rounded-lg px-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              size="md"
              disabled={!canCompare}
              id="run-comparison-btn"
            >
              {isComparing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Comparing…
                </>
              ) : (
                <>
                  <Scale className="w-4 h-4" />
                  Compare
                </>
              )}
            </Button>
          </div>

          {!isLoadingPapers && readyCount > 0 && selected.length < MIN_PAPERS && (
            <p className="text-xs text-text-muted flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5" />
              Select at least {MIN_PAPERS} papers to build a comparison matrix.
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
      {isComparing && (
        <div className="space-y-3">
          <div className="h-20 animate-pulse bg-neutral-100 rounded-xl" />
          <div className="h-64 animate-pulse bg-neutral-100 rounded-xl" />
        </div>
      )}

      {/* Result */}
      {!isComparing && result && <ComparisonMatrix response={result} />}

      {/* Empty state */}
      {!isLoadingPapers && !isComparing && !result && !error && readyCount < MIN_PAPERS && (
        <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center">
            {readyCount === 0 ? (
              <FileText className="w-8 h-8 text-accent" />
            ) : (
              <Layers className="w-8 h-8 text-accent" />
            )}
          </div>
          <div>
            <h3 className="text-base font-semibold text-text-primary">
              {readyCount === 0 ? 'No indexed papers' : 'Pick at least two papers'}
            </h3>
            <p className="text-sm text-text-muted mt-1 max-w-sm">
              {readyCount === 0
                ? 'Comparison needs at least two papers that have finished indexing.'
                : 'Select two or more papers above to generate a side-by-side matrix.'}
            </p>
          </div>
          {readyCount === 0 && (
            <Button variant="secondary" size="md" onClick={() => navigate('/papers')}>
              Go to Research Library
            </Button>
          )}
        </div>
      )}

      {!result && !isComparing && readyCount >= MIN_PAPERS && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
          <Badge variant="default">{DEFAULT_ASPECTS.length} comparison aspects</Badge>
          <span>Dataset · Model · Method · Metrics · Results · Limitations</span>
        </div>
      )}
    </div>
  );
};
