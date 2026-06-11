'use client';

import ReactMarkdown from 'react-markdown';

/**
 * Renders the AI match analysis (markdown) with compact, theme-aware styling.
 *
 * `react-markdown` does NOT render raw HTML by default (no `rehype-raw`), so LLM output
 * can't inject markup — only the markdown subset (headings, bold, lists, links) is shown.
 * Element styling is applied via the `components` map (no Tailwind typography plugin).
 */
export function AnalysisMarkdown({ content }: { content: string }) {
  return (
    <div className="text-sm leading-relaxed text-foreground/90">
      <ReactMarkdown
        components={{
          h1: ({ node, ...p }) => <h3 className="mb-1 mt-3 text-sm font-bold text-foreground" {...p} />,
          h2: ({ node, ...p }) => <h4 className="mb-1 mt-3 text-sm font-semibold text-foreground" {...p} />,
          h3: ({ node, ...p }) => <h4 className="mb-1 mt-3 text-sm font-semibold text-foreground" {...p} />,
          h4: ({ node, ...p }) => <h5 className="mb-1 mt-2 text-sm font-semibold text-foreground" {...p} />,
          p: ({ node, ...p }) => <p className="mb-2" {...p} />,
          ul: ({ node, ...p }) => <ul className="mb-2 ml-5 list-disc space-y-1" {...p} />,
          ol: ({ node, ...p }) => <ol className="mb-2 ml-5 list-decimal space-y-1" {...p} />,
          li: ({ node, ...p }) => <li className="marker:text-muted-foreground" {...p} />,
          strong: ({ node, ...p }) => <strong className="font-semibold text-foreground" {...p} />,
          em: ({ node, ...p }) => <em className="italic" {...p} />,
          a: ({ node, ...p }) => <a className="text-primary underline" target="_blank" rel="noopener noreferrer" {...p} />,
          hr: () => <hr className="my-3 border-border" />,
          blockquote: ({ node, ...p }) => <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground" {...p} />,
          code: ({ node, ...p }) => <code className="rounded bg-muted px-1 py-0.5 text-xs" {...p} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
