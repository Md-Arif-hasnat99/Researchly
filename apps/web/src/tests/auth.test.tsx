import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

// -------------------------------------------------------------------
// Mock Supabase client so tests never make real network calls
// -------------------------------------------------------------------
vi.mock('../lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
      signInWithPassword: vi.fn().mockResolvedValue({ error: null }),
      signUp: vi.fn().mockResolvedValue({ error: null }),
      signOut: vi.fn().mockResolvedValue({}),
    },
  },
}));

import { AuthProvider } from '../context/AuthContext';
import { Login } from '../pages/Login';
import { Register } from '../pages/Register';
import { ProtectedRoute } from '../components/layout/ProtectedRoute';

// Helper to render inside AuthProvider + MemoryRouter
const renderWithAuth = (ui: React.ReactElement, initialPath = '/') =>
  render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>
  );

describe('Login Page', () => {
  it('renders email and password inputs', () => {
    renderWithAuth(<Login />);
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
  });

  it('renders sign in button', () => {
    renderWithAuth(<Login />);
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows link to register page', () => {
    renderWithAuth(<Login />);
    expect(screen.getByText(/create one free/i)).toBeInTheDocument();
  });
});

describe('Register Page', () => {
  it('renders all form fields', () => {
    renderWithAuth(<Register />);
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
  });

  it('renders create account button', () => {
    renderWithAuth(<Register />);
    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
  });

  it('shows link to login page', () => {
    renderWithAuth(<Register />);
    expect(screen.getByText(/sign in/i)).toBeInTheDocument();
  });
});

describe('ProtectedRoute', () => {
  it('shows loading spinner while session is being resolved', () => {
    renderWithAuth(
      <ProtectedRoute>
        <div>Protected Content</div>
      </ProtectedRoute>
    );
    // Initially isLoading = true so it shows the spinner text
    expect(screen.getByText(/verifying session/i)).toBeInTheDocument();
  });
});
