import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MarkdownContent } from '../components/chat/MarkdownContent';

describe('MarkdownContent', () => {
  it('renders emphasis instead of literal asterisks', () => {
    render(
      <MarkdownContent>
        **Propensity Score Matching (PSM):** Researchers created a balanced sample.
      </MarkdownContent>,
    );

    const strong = screen.getByText('Propensity Score Matching (PSM):');
    expect(strong.tagName).toBe('STRONG');
    // The raw markers must not survive into the output.
    expect(document.body.textContent).not.toContain('**');
  });

  it('renders bullet and numbered lists as lists', () => {
    const { container } = render(
      <MarkdownContent>{'Methods:\n- Pairing subjects\n- Class splits\n\n1. First\n2. Second'}</MarkdownContent>,
    );

    expect(container.querySelectorAll('ul').length).toBe(1);
    expect(container.querySelectorAll('ol').length).toBe(1);
    expect(container.querySelectorAll('li').length).toBe(4);
  });

  it('keeps [N] citation markers as literal text, not links', () => {
    const { container } = render(<MarkdownContent>Balanced via PSM [1], paired [2], [3].</MarkdownContent>);

    expect(container.textContent).toContain('[1]');
    expect(container.textContent).toContain('[2], [3]');
    expect(container.querySelector('a')).toBeNull();
  });

  it('turns a single newline into a line break so streamed lines survive', () => {
    const { container } = render(<MarkdownContent>{'line one\nline two'}</MarkdownContent>);

    expect(container.querySelector('br')).not.toBeNull();
  });

  it('renders markdown links safely', () => {
    render(<MarkdownContent>See [the paper](https://example.org/paper)</MarkdownContent>);

    const link = screen.getByText('the paper');
    expect(link.tagName).toBe('A');
    expect(link).toHaveAttribute('href', 'https://example.org/paper');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('escapes raw HTML from paper text instead of injecting it', () => {
    const { container } = render(
      <MarkdownContent>{'before <img src=x onerror="alert(1)"> after'}</MarkdownContent>,
    );

    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('[onerror]')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it('renders a fenced code block as a block, not inline', () => {
    const { container } = render(<MarkdownContent>{"```python\nprint('hi')\n```"}</MarkdownContent>);

    expect(container.querySelector('pre')).not.toBeNull();
    expect(container.querySelector('pre code')).not.toBeNull();
  });
});
