import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';

/**
 * Renders an assistant answer as Markdown instead of literal text.
 *
 * The generation prompt asks the model for bullet points and structured
 * prose, and it answers with Markdown (``**bold**`` lead-ins, lists,
 * headings). Displayed raw, those markers showed up as literal asterisks,
 * so the answer looked like source code rather than prose.
 *
 * ``remark-breaks`` keeps the model's single newlines as line breaks
 * (react-markdown v10 dropped its built-in ``breaks`` option): without it,
 * a streamed answer that breaks a line mid-paragraph would silently reflow
 * into one long line. Raw HTML is not passed through — react-markdown
 * escapes it — so a chunk of text from an uploaded paper can never inject
 * markup into the chat.
 */
export const MarkdownContent: React.FC<{ children: string; className?: string }> = ({
  children,
  className = '',
}) => (
  <div className={`text-sm leading-relaxed break-words ${className}`}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      components={{
        p: ({ children: c }) => <p className="mb-2 last:mb-0">{c}</p>,
        a: ({ href, children: c }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="text-accent underline underline-offset-2 hover:text-accent-dark"
          >
            {c}
          </a>
        ),
        strong: ({ children: c }) => <strong className="font-semibold text-text-primary">{c}</strong>,
        em: ({ children: c }) => <em className="italic">{c}</em>,
        ul: ({ children: c }) => <ul className="list-disc pl-5 mb-2 space-y-1 last:mb-0">{c}</ul>,
        ol: ({ children: c }) => <ol className="list-decimal pl-5 mb-2 space-y-1 last:mb-0">{c}</ol>,
        li: ({ children: c }) => <li className="leading-relaxed">{c}</li>,
        h1: ({ children: c }) => <h3 className="text-base font-semibold text-text-primary mt-3 mb-1.5 first:mt-0">{c}</h3>,
        h2: ({ children: c }) => <h3 className="text-base font-semibold text-text-primary mt-3 mb-1.5 first:mt-0">{c}</h3>,
        h3: ({ children: c }) => <h4 className="text-sm font-semibold text-text-primary mt-2.5 mb-1 first:mt-0">{c}</h4>,
        h4: ({ children: c }) => <h4 className="text-sm font-semibold text-text-primary mt-2.5 mb-1 first:mt-0">{c}</h4>,
        hr: () => <hr className="border-border my-3" />,
        blockquote: ({ children: c }) => (
          <blockquote className="border-l-2 border-border pl-3 text-text-muted italic mb-2 last:mb-0">{c}</blockquote>
        ),
        // react-markdown v10 dropped the `inline` prop: a fenced block's
        // <code> carries a `language-*` class when a language is declared,
        // so that is what distinguishes it from inline code here.
        code: ({ className, children: c }) =>
          className?.includes('language-') ? (
            <code className={`font-mono text-xs ${className}`}>{c}</code>
          ) : (
            <code className="bg-neutral-100 border border-border rounded px-1 py-0.5 text-xs font-mono">{c}</code>
          ),
        pre: ({ children: c }) => (
          <pre className="bg-neutral-100 border border-border rounded-lg p-3 mb-2 overflow-x-auto last:mb-0 [&_code]:bg-transparent [&_code]:border-0 [&_code]:p-0">
            {c}
          </pre>
        ),
        table: ({ children: c }) => (
          <div className="overflow-x-auto mb-2 last:mb-0">
            <table className="w-full text-xs border-collapse border border-border">{c}</table>
          </div>
        ),
        thead: ({ children: c }) => <thead className="bg-neutral-50">{c}</thead>,
        th: ({ children: c }) => (
          <th className="border border-border px-2.5 py-1.5 text-left font-semibold text-text-primary">{c}</th>
        ),
        td: ({ children: c }) => <td className="border border-border px-2.5 py-1.5 text-text-primary">{c}</td>,
      }}
    >
      {children}
    </ReactMarkdown>
  </div>
);
