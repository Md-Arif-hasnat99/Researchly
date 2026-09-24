import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Sparkles, ArrowRight, AlertCircle, CheckCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const Register: React.FC = () => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { signUp } = useAuth();
  const navigate = useNavigate();

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setIsLoading(true);
    const { error } = await signUp(email, password, name);

    if (error) {
      setError(error.message ?? 'Registration failed. Please try again.');
      setIsLoading(false);
      return;
    }

    setSuccess(true);
    setIsLoading(false);

    // Auto-redirect after short delay if email confirmation is disabled (dev mode)
    setTimeout(() => navigate('/dashboard'), 2000);
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center p-4 bg-background">
      <div className="w-full max-w-md space-y-6">
        {/* Brand mark */}
        <div className="text-center space-y-2">
          <div className="w-10 h-10 rounded-xl bg-accent mx-auto flex items-center justify-center text-white shadow-sm">
            <Sparkles className="w-5 h-5" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-text-primary">
            Create your account
          </h1>
          <p className="text-sm text-text-secondary">
            Start building your grounded research knowledge base.
          </p>
        </div>

        <Card className="p-8 space-y-5 shadow-xs">
          {error && (
            <div className="flex items-start gap-2.5 bg-rose-50 border border-rose-200 rounded-lg px-3.5 py-3 text-rose-700 text-sm">
              <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div className="flex items-center gap-2.5 bg-emerald-50 border border-emerald-200 rounded-lg px-3.5 py-3 text-emerald-700 text-sm">
              <CheckCircle className="w-4 h-4 flex-shrink-0" />
              <span>Account created! Redirecting to your workspace…</span>
            </div>
          )}

          {!success && (
            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label
                  htmlFor="register-name"
                  className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1.5"
                >
                  Full Name
                </label>
                <input
                  id="register-name"
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Arif Hasnat"
                  className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-colors"
                />
              </div>

              <div>
                <label
                  htmlFor="register-email"
                  className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1.5"
                >
                  Email Address
                </label>
                <input
                  id="register-email"
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="researcher@university.edu"
                  className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-colors"
                />
              </div>

              <div>
                <label
                  htmlFor="register-password"
                  className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1.5"
                >
                  Password
                </label>
                <input
                  id="register-password"
                  type="password"
                  required
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min. 8 characters"
                  className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-colors"
                />
              </div>

              <div>
                <label
                  htmlFor="register-confirm-password"
                  className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1.5"
                >
                  Confirm Password
                </label>
                <input
                  id="register-confirm-password"
                  type="password"
                  required
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-colors"
                />
              </div>

              <Button
                type="submit"
                variant="primary"
                size="md"
                className="w-full justify-center"
                isLoading={isLoading}
              >
                Create Account <ArrowRight className="w-4 h-4 ml-1" />
              </Button>
            </form>
          )}

          <p className="text-center text-xs text-text-muted pt-2 border-t border-border">
            Already have an account?{' '}
            <Link to="/login" className="text-accent hover:text-accent-dark font-medium transition-colors">
              Sign in
            </Link>
          </p>
        </Card>

        <p className="text-center text-xs text-text-muted">
          Secured by Supabase Auth · End-to-end encrypted
        </p>
      </div>
    </div>
  );
};
