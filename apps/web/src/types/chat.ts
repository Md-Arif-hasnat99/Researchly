export interface ChatCitation {
  chunk_id: string;
  paper_id: string;
  paper_title: string;
  page_number: number;
  section: string | null;
  similarity_score: number;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  citations: ChatCitation[];
}

export type MessageRole = 'user' | 'assistant';

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationListResponse {
  conversations: Conversation[];
  total: number;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}
