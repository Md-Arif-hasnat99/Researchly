import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Send, FileText, MessageSquare, Plus, Trash2, Loader2, Sparkles } from 'lucide-react';
import { listConversations, getConversation, streamQuestion, deleteConversation, listPapers } from '../lib/api';
import { PaperScopeSelector } from '../components/chat/PaperScopeSelector';
import { MarkdownContent } from '../components/chat/MarkdownContent';
import type { Conversation, Message, ChatCitation } from '../types/chat';
import type { Paper } from '../types/paper';

// Extended message type for frontend to support inline citations from the POST response
interface ChatMessage extends Message {
  citations?: ChatCitation[];
  /** Whether this answer's context was reranked before generation (FR-15). */
  reranked?: boolean;
}

export const Chat: React.FC = () => {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [scopedPaperIds, setScopedPaperIds] = useState<string[]>([]);
  // Off by default: reranking adds a model round-trip to every turn, so it
  // is something a user opts into rather than pays for silently.
  const [rerank, setRerank] = useState(false);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchConversations();
    fetchPapers();
  }, []);

  const fetchPapers = async () => {
    try {
      const data = await listPapers();
      setPapers(data.papers);
    } catch (err) {
      console.error('Failed to list papers for scoping:', err);
    }
  };

  const toggleScope = (id: string) => {
    setScopedPaperIds((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  };

  useEffect(() => {
    if (conversationId) {
      fetchConversationDetail(conversationId);
    } else {
      setMessages([]);
    }
  }, [conversationId]);

  useEffect(() => {
    // Scroll to bottom when messages change
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const fetchConversations = async () => {
    try {
      const data = await listConversations();
      setConversations(data.conversations);
    } catch (err) {
      console.error('Failed to list conversations:', err);
    }
  };

  const fetchConversationDetail = async (id: string) => {
    try {
      setIsLoading(true);
      const data = await getConversation(id);
      setMessages(data.messages as ChatMessage[]);
    } catch (err) {
      console.error('Failed to fetch conversation:', err);
      navigate('/chat');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteConversation = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await deleteConversation(id);
      setConversations(conversations.filter((c) => c.id !== id));
      if (conversationId === id) {
        navigate('/chat');
      }
    } catch (err) {
      console.error('Failed to delete conversation:', err);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const query = input.trim();
    setInput('');
    
    // Optimistic UI for user message
    const tempUserMsgId = `temp-user-${Date.now()}`;
    const newUserMsg: ChatMessage = {
      id: tempUserMsgId,
      conversation_id: conversationId || '',
      role: 'user',
      content: query,
      created_at: new Date().toISOString(),
    };
    
    setMessages((prev) => [...prev, newUserMsg]);
    setIsLoading(true);

    // A placeholder assistant message that tokens are appended into, so the
    // answer appears as it is written instead of after a multi-second wait.
    const tempAssistantId = `temp-assistant-${Date.now()}`;
    let answerSoFar = '';
    setMessages((prev) => [
      ...prev,
      {
        id: tempAssistantId,
        conversation_id: conversationId || '',
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString(),
        citations: [],
      },
    ]);

    const appendToAnswer = (text: string) => {
      answerSoFar += text;
      setMessages((prev) =>
        prev.map((m) => (m.id === tempAssistantId ? { ...m, content: answerSoFar } : m)),
      );
    };

    try {
      const res = await streamQuestion(query, conversationId, scopedPaperIds, rerank, {
        onToken: appendToAnswer,
        onCitations: (citations) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === tempAssistantId ? { ...m, citations } : m)),
          );
        },
      });

      if (!conversationId) {
        // If it was a new conversation, navigate to the new URL
        // We'll also refresh the conversation list to show it
        fetchConversations();
        navigate(`/chat/${res.conversation_id}`, { replace: true });
      }

      // Replace the streaming placeholder with the persisted message.
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempAssistantId
            ? {
                ...m,
                id: res.message_id,
                conversation_id: res.conversation_id,
                content: res.answer || answerSoFar,
                citations: res.citations,
                reranked: res.reranked,
              }
            : m,
        ),
      );

      if (!conversationId) {
        // The optimistic messages were created before the conversation
        // existed, so their conversation_id is still a placeholder.
        setMessages((prev) =>
          prev.map((m) => ({ ...m, conversation_id: res.conversation_id })),
        );
      }
    } catch (err) {
      console.error('Failed to ask question:', err);
      // Drop the empty placeholder; a failed request has no answer to show.
      setMessages((prev) => prev.filter((m) => m.id !== tempAssistantId));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-[calc(100vh-8.5rem)] flex gap-6 relative">
      
      {/* Sidebar for Conversations */}
      <div className={`
        ${isSidebarOpen ? 'flex' : 'hidden'} 
        w-64 flex-col bg-surface border border-border rounded-xl shadow-xs overflow-hidden shrink-0 lg:flex
      `}>
        <div className="p-4 border-b border-border">
          <Button 
            variant="primary" 
            className="w-full flex items-center justify-center gap-2"
            onClick={() => navigate('/chat')}
          >
            <Plus className="w-4 h-4" />
            New Chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {conversations.length === 0 ? (
            <div className="text-sm text-text-muted text-center py-4">No conversations yet</div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => navigate(`/chat/${conv.id}`)}
                className={`
                  group flex items-center justify-between p-3 rounded-lg cursor-pointer transition-colors
                  ${conv.id === conversationId ? 'bg-neutral-100 border border-border' : 'hover:bg-neutral-50 border border-transparent'}
                `}
              >
                <div className="flex items-center gap-3 overflow-hidden">
                  <MessageSquare className="w-4 h-4 text-text-muted shrink-0" />
                  <span className="text-sm font-medium text-text-primary truncate" title={conv.title}>
                    {conv.title}
                  </span>
                </div>
                <button
                  onClick={(e) => handleDeleteConversation(e, conv.id)}
                  className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-red-500 transition-opacity p-1"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Chat Panel */}
      <div className="flex-1 flex flex-col bg-surface border border-border rounded-xl overflow-hidden shadow-xs">
        
        {/* Chat Header */}
        <div className="px-5 py-3 border-b border-border flex items-center justify-between bg-neutral-50/50">
          <div className="flex items-center gap-3">
            {/* Mobile Sidebar Toggle */}
            <button 
              className="lg:hidden text-text-muted hover:text-text-primary"
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            >
              <MessageSquare className="w-5 h-5" />
            </button>
            <div>
              <h2 className="text-sm font-semibold text-text-primary">
                {conversationId ? 'Conversation' : 'New Chat'}
              </h2>
              <p className="text-xs text-text-muted">Research Assistant</p>
            </div>
          </div>
        </div>

        {/* Message Stream */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {messages.length === 0 && !isLoading && (
            <div className="h-full flex flex-col items-center justify-center text-text-muted space-y-3">
              <MessageSquare className="w-10 h-10 opacity-20" />
              <p className="text-sm">Start a new conversation by asking a question.</p>
            </div>
          )}

          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'}`}
            >
              <div
                className={`max-w-3xl rounded-xl p-4 text-sm leading-relaxed ${
                  m.role === 'user'
                    ? 'bg-accent text-white whitespace-pre-wrap'
                    : 'bg-background border border-border text-text-primary'
                }`}
              >
                {m.role === 'user' ? m.content : <MarkdownContent>{m.content}</MarkdownContent>}
              </div>

              {m.reranked && (
                <div
                  className="flex items-center gap-1.5 mt-1.5 text-[11px] text-text-muted"
                  data-testid="message-reranked"
                >
                  <Sparkles className="w-3 h-3" />
                  <span>Sources re-ranked by relevance</span>
                </div>
              )}

              {/* Citations section if assistant and citations exist */}
              {m.citations && m.citations.length > 0 && (
                <div className="mt-2.5 space-y-1.5 max-w-2xl w-full">
                  <div className="text-[11px] font-semibold text-text-muted uppercase tracking-wider">
                    Source Evidence
                  </div>
                  {m.citations.map((c, idx) => (
                    <details
                      key={c.chunk_id + idx}
                      className="bg-neutral-50 border border-border rounded-lg p-2.5 text-xs text-text-secondary group"
                    >
                      <summary className="flex items-center justify-between gap-3 cursor-pointer hover:text-accent transition-colors list-none marker:hidden [&::-webkit-details-marker]:hidden">
                        <div className="font-medium text-text-primary flex items-center gap-1.5">
                          <FileText className="w-3.5 h-3.5 text-accent" />
                          <span>{c.paper_title} · Page {c.page_number}</span>
                        </div>
                        <div className="text-[10px] font-mono text-text-muted opacity-60">
                          {c.similarity_score ? (c.similarity_score * 100).toFixed(1) + '%' : 'Source'}
                        </div>
                      </summary>
                      {c.content && (
                        <div className="mt-2 p-2 bg-white border border-border rounded text-text-primary whitespace-pre-wrap leading-relaxed border-l-2 border-l-accent opacity-90">
                          {c.content}
                        </div>
                      )}
                    </details>
                  ))}
                </div>
              )}
            </div>
          ))}

          {isLoading && (
            <div className="flex items-start">
              <div className="bg-background border border-border rounded-xl p-4 flex items-center gap-2">
                <Loader2 className="w-4 h-4 text-accent animate-spin" />
                <span className="text-sm text-text-muted">Researching...</span>
              </div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>

        {/* Query Input */}
        <div className="border-t border-border bg-surface">
          <PaperScopeSelector
            papers={papers}
            selected={scopedPaperIds}
            onToggle={toggleScope}
            disabled={isLoading}
          />
          <div className="px-4 pt-1">
            <label className="flex items-center gap-2 text-xs text-text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(e) => setRerank(e.target.checked)}
                disabled={isLoading}
                className="h-3.5 w-3.5 rounded border-border text-accent focus:ring-accent disabled:opacity-50"
                data-testid="chat-rerank-toggle"
              />
              <span>AI rerank sources</span>
              <span className="text-text-muted/70">
                &mdash; more accurate, slower
              </span>
            </label>
          </div>
          <div className="p-4 pt-1">
            <form onSubmit={handleSendMessage} className="flex items-center gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a question about your indexed papers..."
                disabled={isLoading}
                className="flex-1 bg-background border border-border rounded-lg px-4 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50"
              />
              <Button type="submit" variant="primary" size="md" disabled={!input.trim() || isLoading}>
                <Send className="w-4 h-4" />
              </Button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};
