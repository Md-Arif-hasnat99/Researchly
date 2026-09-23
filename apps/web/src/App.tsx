import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { Dashboard } from './pages/Dashboard';
import { Papers } from './pages/Papers';
import { Chat } from './pages/Chat';
import { Compare } from './pages/Compare';
import { LiteratureReview } from './pages/LiteratureReview';
import { ResearchGaps } from './pages/ResearchGaps';
import { Settings } from './pages/Settings';
import { Login } from './pages/Login';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="papers" element={<Papers />} />
          <Route path="chat" element={<Chat />} />
          <Route path="chat/:conversationId" element={<Chat />} />
          <Route path="compare" element={<Compare />} />
          <Route path="literature-review" element={<LiteratureReview />} />
          <Route path="research-gaps" element={<ResearchGaps />} />
          <Route path="settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
