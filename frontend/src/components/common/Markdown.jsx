import React, { useMemo } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { cn } from '../../utils/cn';

/**
 * LLM text arrives as Markdown. Rendered, sanitised, and styled as part of
 * the note: headings read as field labels, bold as ink, lists as ruled items.
 */
const STYLES =
  '[&_h1]:field-label [&_h2]:field-label [&_h3]:field-label [&_h4]:field-label ' +
  '[&_h1]:text-[var(--ink)] [&_h2]:text-[var(--ink)] [&_h3]:text-[var(--ink)] [&_h4]:text-[var(--ink)] ' +
  '[&_h1]:mt-4 [&_h2]:mt-4 [&_h3]:mt-4 [&_h4]:mt-3 [&_h1]:mb-1 [&_h2]:mb-1 [&_h3]:mb-1 [&_h4]:mb-1 ' +
  '[&>*:first-child]:mt-0 [&_p]:my-1.5 [&_strong]:text-[var(--ink)] [&_strong]:font-semibold ' +
  '[&_ul]:list-disc [&_ol]:list-decimal [&_ul]:pl-5 [&_ol]:pl-5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-1 ' +
  '[&_a]:text-[var(--stamp)] [&_a]:underline ' +
  '[&_table]:w-full [&_td]:border [&_td]:border-[var(--rule)] [&_td]:px-1.5 [&_th]:border [&_th]:border-[var(--rule)] [&_th]:px-1.5';

const Markdown = ({ children, className }) => {
  const html = useMemo(() => DOMPurify.sanitize(marked.parse(children || '')), [children]);
  return <div className={cn(STYLES, className)} dangerouslySetInnerHTML={{ __html: html }} />;
};

export default Markdown;
