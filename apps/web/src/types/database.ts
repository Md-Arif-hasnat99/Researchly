/**
 * TypeScript type definitions generated from the Supabase schema.
 * Auto-generate in future with: supabase gen types typescript --project-id <id>
 */

export type PaperStatus = 'uploaded' | 'processing' | 'ready' | 'failed';
export type MessageRole = 'user' | 'assistant';

export interface Database {
  public: {
    Tables: {
      profiles: {
        Row: {
          id: string;
          name: string | null;
          email: string | null;
          avatar_url: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          name?: string | null;
          email?: string | null;
          avatar_url?: string | null;
        };
        Update: {
          name?: string | null;
          avatar_url?: string | null;
        };
      };
      papers: {
        Row: {
          id: string;
          user_id: string;
          title: string;
          authors: string[];
          abstract: string | null;
          publication_year: number | null;
          file_path: string;
          file_size: number | null;
          total_pages: number | null;
          status: PaperStatus;
          error_message: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database['public']['Tables']['papers']['Row'], 'id' | 'created_at' | 'updated_at'>;
        Update: Partial<Database['public']['Tables']['papers']['Insert']>;
      };
      paper_chunks: {
        Row: {
          id: string;
          paper_id: string;
          content: string;
          page_number: number;
          section: string | null;
          chunk_index: number;
          embedding: number[] | null;
          created_at: string;
        };
        Insert: Omit<Database['public']['Tables']['paper_chunks']['Row'], 'id' | 'created_at'>;
        Update: Partial<Database['public']['Tables']['paper_chunks']['Insert']>;
      };
      conversations: {
        Row: {
          id: string;
          user_id: string;
          title: string;
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database['public']['Tables']['conversations']['Row'], 'id' | 'created_at' | 'updated_at'>;
        Update: Partial<Database['public']['Tables']['conversations']['Insert']>;
      };
      messages: {
        Row: {
          id: string;
          conversation_id: string;
          role: MessageRole;
          content: string;
          created_at: string;
        };
        Insert: Omit<Database['public']['Tables']['messages']['Row'], 'id' | 'created_at'>;
        Update: never;
      };
      citations: {
        Row: {
          id: string;
          message_id: string;
          paper_id: string;
          chunk_id: string;
          page_number: number;
          similarity_score: number | null;
          created_at: string;
        };
        Insert: Omit<Database['public']['Tables']['citations']['Row'], 'id' | 'created_at'>;
        Update: never;
      };
    };
    Functions: {
      match_paper_chunks: {
        Args: {
          query_embedding: number[];
          match_count?: number;
          similarity_cutoff?: number;
          filter_paper_ids?: string[] | null;
        };
        Returns: {
          id: string;
          paper_id: string;
          content: string;
          page_number: number;
          section: string | null;
          chunk_index: number;
          similarity: number;
        }[];
      };
    };
  };
}
