import React, { useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { warmBackend } from './lib/api';
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/layout/ProtectedRoute';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import { Register } from './pages/Register';

// Lazy load heavy routes to reduce initial bundle size
const Papers = lazy(() => import('./pages/Papers').then(m => ({ default: m.Papers })));
const PaperDetail = lazy(() => import('./pages/PaperDetail').then(m => ({ default: m.PaperDetail })));
const Chat = lazy(() => import('./pages/Chat').then(m => ({ default: m.Chat })));
const Settings = lazy(() => import('./pages/Settings').then(m => ({ default: m.Settings })));

// Lightweight loading fallback
const RouteLoading = () => (
  <div className="flex items-center justify-center h-64">
    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
  </div>
);

export const App: React.FC = () => {
  // Ping the backend on every page load so a sleeping (free-tier)
  // instance starts warming while the app is still rendering.
  useEffect(() => {
    warmBackend();
  }, []);

  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* Protected application shell */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route
              path="papers"
              element={
                <Suspense fallback={<RouteLoading />}>
                  <Papers />
                </Suspense>
              }
            />
            <Route
              path="papers/:id"
              element={
                <Suspense fallback={<RouteLoading />}>
                  <PaperDetail />
                </Suspense>
              }
            />
            <Route
              path="chat"
              element={
                <Suspense fallback={<RouteLoading />}>
                  <Chat />
                </Suspense>
              }
            />
            <Route
              path="chat/:conversationId"
              element={
                <Suspense fallback={<RouteLoading />}>
                  <Chat />
                </Suspense>
              }
            />
            <Route
              path="settings"
              element={
                <Suspense fallback={<RouteLoading />}>
                  <Settings />
                </Suspense>
              }
            />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
};

export default App;