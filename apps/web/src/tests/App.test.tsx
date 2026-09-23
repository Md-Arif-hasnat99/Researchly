import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from '../App';

describe('Researchly Web Application', () => {
  it('renders application shell with brand title', () => {
    render(<App />);
    expect(screen.getAllByText('Researchly').length).toBeGreaterThan(0);
    expect(screen.getByText('Research Workspace')).toBeInTheDocument();
  });

  it('renders navigation links', () => {
    render(<App />);
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Papers')).toBeInTheDocument();
    expect(screen.getByText('Chat')).toBeInTheDocument();
    expect(screen.getByText('Compare')).toBeInTheDocument();
    expect(screen.getByText('Literature Review')).toBeInTheDocument();
    expect(screen.getByText('Research Gaps')).toBeInTheDocument();
  });
});
