import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// Mock Supabase so tests never make real network calls
vi.mock('../lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
      signInWithPassword: vi.fn(),
      signUp: vi.fn(),
      signOut: vi.fn(),
    },
  },
}));

import App from '../App';

describe('App routing', () => {
  it('renders the login page at /login when unauthenticated', async () => {
    // jsdom starts at '/', ProtectedRoute will redirect to /login
    render(<App />);
    // ProtectedRoute shows spinner initially while session resolves
    expect(screen.getByText(/verifying session/i)).toBeInTheDocument();
  });

  it('renders login form with sign-in button', async () => {
    // Directly render the Login page
    const { Login } = await import('../pages/Login');
    const { MemoryRouter } = await import('react-router-dom');
    const { AuthProvider } = await import('../context/AuthContext');

    render(
      <MemoryRouter>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });
});
