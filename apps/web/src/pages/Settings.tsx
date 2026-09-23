import React from 'react';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';

export const Settings: React.FC = () => {
  return (
    <div className="space-y-6 max-w-4xl mx-auto animate-fadeIn">
      <div className="border-b border-border pb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary">Settings</h1>
        <p className="text-sm text-text-secondary mt-1">
          Manage your research workspace preferences, models, and integrations.
        </p>
      </div>

      <div className="space-y-4">
        <Card className="space-y-4 p-6">
          <h2 className="text-base font-semibold text-text-primary">AI Models & Embeddings</h2>
          <div className="space-y-3 text-sm">
            <div>
              <label className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1">
                Generation Model
              </label>
              <select className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent">
                <option>Google Gemini 1.5 Pro</option>
                <option>Google Gemini 1.5 Flash</option>
                <option>Google Gemini 2.0 Flash</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1">
                Embedding Model
              </label>
              <input
                type="text"
                disabled
                value="text-embedding-004 (768 dimensions)"
                className="w-full bg-neutral-100 border border-border rounded-lg px-3 py-2 text-sm text-text-secondary cursor-not-allowed"
              />
            </div>
          </div>
        </Card>

        <Card className="space-y-4 p-6">
          <h2 className="text-base font-semibold text-text-primary">Retrieval Parameters</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            <div>
              <label className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1">
                Top-K Chunks
              </label>
              <input
                type="number"
                defaultValue={8}
                min={1}
                max={20}
                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-text-muted uppercase tracking-wider mb-1">
                Similarity Threshold (Cosine)
              </label>
              <input
                type="number"
                defaultValue={0.65}
                step={0.05}
                min={0}
                max={1}
                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
          </div>
        </Card>

        <div className="flex justify-end">
          <Button variant="primary" size="md">
            Save Preferences
          </Button>
        </div>
      </div>
    </div>
  );
};
