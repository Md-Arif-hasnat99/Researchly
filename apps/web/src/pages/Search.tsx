import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import {
  Search as SearchIcon,
  Loader2,
  AlertCircle,
  FileText,
  Sparkles,
  Hash,
  Layers,
} from 'lucide-react';
import { searchPapers } from '../lib/api';
import type { SearchMode, SearchResponse, SearchResult } from '../types/search';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_QUERY = 2000;
const DEFAULT_TOP_K = 8;

/**
 * Mode help text. Each option says when to reach for it, because the
 * difference between them is the entire substance of FR-14 and a bare
 * dropdown gives the user nothing to choose on.
 */
const MODE_OPTIONS: Array<{ value: SearchMode; label: string; hint: string }> = [
  {
    value: 'hybrid',
    label: 'Hybrid',
    hint: 'Combines meaning and exact wording. Best default — catches "ImageNet" and "what makes this slow" alike.',
  },
  {
    value: 'vector',
    label: 'Semantic',
    hint: 'Meaning only. Good for conceptual questions where your wording differs from the paper’s.',
  },
  {
    value: 'keyword',
    label: 'Exact terms',
    hint: 'Literal text match. Best for model names, abbreviations, and dataset names. Works without an AI key.',
  },
];

const MODE_LABELS: Record<SearchMode, string> = {
  hybrid: 'Hybrid (meaning + exact terms)',
  vector: 'Semantic only',
  keyword: 'Exact terms only',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Highlight query terms that appear literally in the snippet. */
function highlightTerms(content: string, query: string) {
  const terms = query
    .toLowerCase()
    .split(/[^a-z0-9]+/i)
    .filter((t) => t.length > 1);
  if (terms.length === 0) return content;

  const escaped = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const group = escaped.join('|');
  // Split on a capturing group so matched terms arrive as their own array
  // elements. The tester is deliberately non-global: a /g regex carries
  // lastIndex state between .test() calls and would highlight every other
  // occurrence.
  const splitter = new RegExp(`(\\b(?:${group})\\b)`, 'gi');
  const isTerm = new RegExp(`^\\b(?:${group})\\b$`, 'i');

  return content.split(splitter).map((part, i) =>
    isTerm.test(part) ? (
      <mark key={i} className="bg-amber-100 text-text-primary rounded px-0.5">
        {part}
      </mark>
    ) : (
      part
    )
  );
}

function truncate(content: string, max = 320): string {
  if (content.length <= max) return content;
  return `${content.slice(0, max).trimEnd()}…`;
}

// ---------------------------------------------------------------------------
// Result card
// ---------------------------------------------------------------------------

interface ResultCardProps {
  result: SearchResult;
  query: string;
}

const ResultCard: React.FC<ResultCardProps> = ({ result, query }) => {
  const isKeywordOnly =
    result.matched_by.length === 1 && result.matched_by[0] === 'keyword';

  return (
    <Card className="p-4" data-testid={`search-result-${result.chunk_id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-primary truncate">
            {result.paper_title}
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Page {result.page_number}
            {result.section ? ` · ${result.section}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {/* Provenance: why did this chunk come back? */}
          {result.matched_by.includes('vector') && (
            <Badge variant="outline" data-testid="match-semantic">
              <Sparkles className="w-3 h-3 mr-1" />
              Meaning
            </Badge>
          )}
          {result.matched_by.includes('keyword') && (
            <Badge variant="warning" data-testid="match-keyword">
              <Hash className="w-3 h-3 mr-1" />
              Exact term
            </Badge>
          )}
        </div>
      </div>

      <p className="text-sm text-text-secondary leading-relaxed mt-3">
        {highlightTerms(truncate(result.content), query)}
      </p>

      <p className="text-xs text-text-muted mt-3">
        {/*
          Only a real cosine similarity is shown as a percentage. A
          keyword-only hit has no vector score, and the fusion score is a
          ranking artefact, so neither is presented as "% similar".
        */}
        {result.similarity_score !== null ? (
          <span title="Cosine similarity to the query embedding">
            {Math.round(result.similarity_score * 100)}% semantic match
          </span>
        ) : (
          <span data-testid="no-similarity-score">
            Exact text match — no vector similarity computed
          </span>
        )}
        {isKeywordOnly && ' · surfaced by keyword search only'}
      </p>
    </Card>
  );
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export const Search: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  const [query, setQuery] = useState(searchParams.get('q') ?? '');
  const [mode, setMode] = useState<SearchMode>('hybrid');
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  // The last query actually sent, so a submit that also rewrites the URL
  // is not then re-run by the URL effect below.
  const lastRun = useRef<string | null>(null);

  const runSearch = useCallback(async (searchQuery: string, searchMode: SearchMode) => {
    const trimmed = searchQuery.trim();
    if (!trimmed) return;
    lastRun.current = trimmed;
    setIsSearching(true);
    setError(null);
    try {
      setResult(
        await searchPapers({ query: trimmed, mode: searchMode, top_k: DEFAULT_TOP_K })
      );
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : 'Search failed.');
    } finally {
      setIsSearching(false);
    }
  }, []);

  // A query arriving from the header search box runs on arrival.
  // Deliberately keyed on the URL only: including `query` or `mode` would
  // re-fire a request on every keystroke of the local input.
  useEffect(() => {
    const fromUrl = searchParams.get('q');
    if (fromUrl && fromUrl !== lastRun.current) {
      setQuery(fromUrl);
      void runSearch(fromUrl, mode);
    }
  }, [searchParams, runSearch]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    // Keep the query shareable in the URL.
    setSearchParams({ q: trimmed }, { replace: true });
    void runSearch(trimmed, mode);
  };

  const activeMode = MODE_OPTIONS.find((m) => m.value === mode)!;
  // A hybrid request answered with mode=vector means keyword search was
  // unavailable; saying so beats silently showing thinner results.
  const degraded = result !== null && result.mode === 'vector' && mode === 'hybrid';

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="border-b border-border pb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Search</h1>
        <p className="text-sm text-text-secondary mt-1">
          Search across your indexed papers by meaning, by exact wording, or both.
        </p>
      </div>

      {/* Query + mode */}
      <Card className="p-5">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="search-input" className="sr-only">
              Search query
            </label>
            <div className="relative">
              <SearchIcon
                className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
              />
              <input
                id="search-input"
                data-testid="search-input"
                type="search"
                value={query}
                maxLength={MAX_QUERY}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. ImageNet, or what limits the authors' results"
                className="w-full bg-surface border border-border rounded-lg pl-9 pr-4 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent"
              />
            </div>
          </div>

          <div className="space-y-2">
            <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
              How to search
            </span>
            <div className="flex flex-wrap gap-2">
              {MODE_OPTIONS.map((option) => {
                const active = mode === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setMode(option.value)}
                    aria-pressed={active}
                    data-testid={`search-mode-${option.value}`}
                    className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                      active
                        ? 'border-accent bg-accent/10 text-accent'
                        : 'border-border text-text-muted hover:border-accent/40 hover:text-text-secondary'
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-text-muted" data-testid="mode-hint">
              {activeMode.hint}
            </p>
          </div>

          <Button
            type="submit"
            variant="primary"
            size="md"
            disabled={isSearching || !query.trim()}
            id="run-search-btn"
          >
            {isSearching ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Searching…
              </>
            ) : (
              <>
                <SearchIcon className="w-4 h-4" />
                Search
              </>
            )}
          </Button>
        </form>
      </Card>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2 text-rose-600 text-sm bg-rose-50 border border-rose-200 rounded-xl p-4">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Loading */}
      {isSearching && (
        <div className="space-y-3">
          <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
          <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
          <div className="h-24 animate-pulse bg-neutral-100 rounded-xl" />
        </div>
      )}

      {/* Results */}
      {!isSearching && result && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-text-muted flex items-center gap-2">
              <Layers className="w-4 h-4" />
              {result.total_results} result{result.total_results !== 1 ? 's' : ''}
            </h2>
            <span className="text-xs text-text-muted">{MODE_LABELS[result.mode]}</span>
          </div>

          {degraded && (
            <div
              className="flex items-start gap-2 text-xs text-text-muted bg-neutral-50 border border-border rounded-lg p-3"
              data-testid="degraded-notice"
            >
              <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>
                Keyword search is unavailable on this server, so these are semantic results
                only. Exact model and dataset names may be missed.
              </span>
            </div>
          )}

          {result.results.map((r) => (
            <ResultCard key={r.chunk_id} result={r} query={result.query} />
          ))}

          {result.total_results === 0 && (
            <Card className="py-12 text-center">
              <SearchIcon className="w-8 h-8 text-text-muted mx-auto mb-3 opacity-40" />
              <h3 className="text-sm font-semibold text-text-primary">No matches</h3>
              <p className="text-xs text-text-muted mt-1 max-w-sm mx-auto">
                Nothing in your indexed papers matched that query. Try fewer or broader
                terms, or switch to Semantic mode to search by meaning.
              </p>
            </Card>
          )}
        </div>
      )}

      {/* Empty state */}
      {!isSearching && !result && !error && (
        <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center">
            <FileText className="w-8 h-8 text-accent" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-text-primary">Search your library</h3>
            <p className="text-sm text-text-muted mt-1 max-w-sm">
              Search only works on papers that have finished indexing.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

export default Search;
