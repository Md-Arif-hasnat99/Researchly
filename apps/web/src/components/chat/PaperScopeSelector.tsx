import React from 'react';
import { FileText, X, Layers } from 'lucide-react';
import type { Paper } from '../../types/paper';

interface PaperScopeSelectorProps {
  papers: Paper[];
  selected: string[];
  onToggle: (id: string) => void;
  disabled?: boolean;
}

/**
 * Optional paper scoping for a chat query.
 *
 * No selection means "search every indexed paper", which matches the
 * backend default. Selecting papers sends `paper_ids` so retrieval is
 * restricted to them.
 */
export const PaperScopeSelector: React.FC<PaperScopeSelectorProps> = ({
  papers,
  selected,
  onToggle,
  disabled,
}) => {
  const ready = papers.filter((p) => p.status === 'ready');
  const [open, setOpen] = React.useState(false);

  if (ready.length === 0) return null;

  const selectedPapers = ready.filter((p) => selected.includes(p.id));

  return (
    <div className="px-4 pb-3">
      {/* Selected chips */}
      {selectedPapers.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <Layers className="w-3.5 h-3.5 text-text-muted" />
          {selectedPapers.map((paper) => (
            <button
              key={paper.id}
              type="button"
              onClick={() => onToggle(paper.id)}
              disabled={disabled}
              aria-label={`Remove ${paper.title} from scope`}
              className="inline-flex items-center gap-1 bg-accent/10 text-accent border border-accent/30 rounded-full pl-2.5 pr-1.5 py-0.5 text-xs font-medium hover:bg-accent/20 transition-colors disabled:opacity-50"
            >
              <span className="max-w-40 truncate">{paper.title}</span>
              <X className="w-3 h-3" />
            </button>
          ))}
        </div>
      )}

      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-text-muted hover:text-accent transition-colors disabled:opacity-50"
          id="open-paper-scope-btn"
        >
          <FileText className="w-3.5 h-3.5" />
          {selectedPapers.length > 0
            ? 'Change paper scope'
            : 'Scope question to specific papers (optional)'}
        </button>
      ) : (
        <div className="bg-neutral-50 border border-border rounded-xl p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">
              Limit retrieval to
            </span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-xs text-text-muted hover:text-text-primary"
            >
              Done
            </button>
          </div>
          <div className="max-h-44 overflow-y-auto space-y-1">
            {ready.map((paper) => {
              const isSelected = selected.includes(paper.id);
              return (
                <label
                  key={paper.id}
                  className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-white cursor-pointer text-sm"
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={disabled}
                    onChange={() => onToggle(paper.id)}
                    className="accent-accent"
                    data-testid={`chat-scope-${paper.id}`}
                  />
                  <span className="text-text-primary truncate flex-1">{paper.title}</span>
                  {paper.publication_year && (
                    <span className="text-xs font-mono text-text-muted">
                      {paper.publication_year}
                    </span>
                  )}
                </label>
              );
            })}
          </div>
          <p className="text-[11px] text-text-muted">
            Leave all unchecked to search every indexed paper.
          </p>
        </div>
      )}
    </div>
  );
};
