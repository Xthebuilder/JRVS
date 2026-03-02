/**
 * Jarvis AI API Client
 * Connects Next.js frontend to Jarvis backend
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

// Type definitions
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: Date;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  stream?: boolean;
}

export interface ChatResponse {
  response: string;
  session_id: string;
  model_used: string;
  context_used?: string;
}

export interface Model {
  name: string;
  current: boolean;
  size?: number;
  modified_at?: string;
}

export interface CalendarEvent {
  id?: number;
  title: string;
  description?: string;
  event_date: string;
  reminder_minutes?: number;
  completed?: boolean;
}

export interface SearchResult {
  title: string;
  preview: string;
  url?: string;
  similarity?: number;
}

// API Client Class
export class JarvisAPI {
  private baseUrl: string;
  private sessionId: string | null = null;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  // Chat Methods
  async chat(message: string, stream: boolean = false): Promise<ChatResponse> {
    const response = await fetch(`${this.baseUrl}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message,
        session_id: this.sessionId,
        stream,
      } as ChatRequest),
    });

    if (!response.ok) {
      throw new Error(`Chat failed: ${response.statusText}`);
    }

    const data: ChatResponse = await response.json();
    this.sessionId = data.session_id; // Save session for continuity
    return data;
  }

  // WebSocket Streaming Chat
  connectWebSocket(onMessage: (chunk: string) => void, onComplete: () => void) {
    const ws = new WebSocket(this.baseUrl.replace('/api', '/ws/chat').replace('http', 'ws'));

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'chunk') {
        onMessage(data.content);
      } else if (data.type === 'done') {
        onComplete();
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    return {
      send: (message: string) => {
        ws.send(JSON.stringify({ message }));
      },
      close: () => ws.close(),
    };
  }

  // Model Methods
  async listModels(): Promise<{ models: Model[]; current: string }> {
    const response = await fetch(`${this.baseUrl}/models`);
    if (!response.ok) {
      throw new Error(`Failed to fetch models: ${response.statusText}`);
    }
    return response.json();
  }

  async switchModel(modelName: string): Promise<boolean> {
    const response = await fetch(`${this.baseUrl}/models/switch/${modelName}`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error(`Failed to switch model: ${response.statusText}`);
    }
    const data = await response.json();
    return data.success;
  }

  // Calendar Methods
  async getUpcomingEvents(days: number = 7): Promise<CalendarEvent[]> {
    const response = await fetch(`${this.baseUrl}/calendar/events?days=${days}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch events: ${response.statusText}`);
    }
    const data = await response.json();
    return data.events;
  }

  async getTodayEvents(): Promise<CalendarEvent[]> {
    const response = await fetch(`${this.baseUrl}/calendar/today`);
    if (!response.ok) {
      throw new Error(`Failed to fetch today's events: ${response.statusText}`);
    }
    const data = await response.json();
    return data.events;
  }

  async createEvent(event: CalendarEvent): Promise<number> {
    const response = await fetch(`${this.baseUrl}/calendar/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(event),
    });
    if (!response.ok) {
      throw new Error(`Failed to create event: ${response.statusText}`);
    }
    const data = await response.json();
    return data.event_id;
  }

  async completeEvent(eventId: number): Promise<boolean> {
    const response = await fetch(`${this.baseUrl}/calendar/events/${eventId}/complete`, {
      method: 'POST',
    });
    if (!response.ok) {
      throw new Error(`Failed to complete event: ${response.statusText}`);
    }
    const data = await response.json();
    return data.success;
  }

  async deleteEvent(eventId: number): Promise<boolean> {
    const response = await fetch(`${this.baseUrl}/calendar/events/${eventId}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error(`Failed to delete event: ${response.statusText}`);
    }
    const data = await response.json();
    return data.success;
  }

  // Knowledge Base Methods
  async scrapeUrl(url: string): Promise<number> {
    const response = await fetch(`${this.baseUrl}/scrape`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ url }),
    });
    if (!response.ok) {
      throw new Error(`Failed to scrape URL: ${response.statusText}`);
    }
    const data = await response.json();
    return data.document_id;
  }

  async searchDocuments(query: string, limit: number = 5): Promise<SearchResult[]> {
    const response = await fetch(`${this.baseUrl}/search?query=${encodeURIComponent(query)}&limit=${limit}`);
    if (!response.ok) {
      throw new Error(`Failed to search documents: ${response.statusText}`);
    }
    const data = await response.json();
    return data.results;
  }

  // Utility Methods
  async getHealth(): Promise<{ status: string; model: string }> {
    const response = await fetch(this.baseUrl.replace('/api', '/health'));
    if (!response.ok) {
      throw new Error(`Health check failed: ${response.statusText}`);
    }
    return response.json();
  }

  async getStats(): Promise<any> {
    const response = await fetch(`${this.baseUrl}/stats`);
    if (!response.ok) {
      throw new Error(`Failed to fetch stats: ${response.statusText}`);
    }
    return response.json();
  }

  async getHistory(limit: number = 10): Promise<any[]> {
    if (!this.sessionId) {
      return [];
    }
    const response = await fetch(`${this.baseUrl}/history/${this.sessionId}?limit=${limit}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch history: ${response.statusText}`);
    }
    const data = await response.json();
    return data.history;
  }

  // Session Management
  getSessionId(): string | null {
    return this.sessionId;
  }

  setSessionId(sessionId: string): void {
    this.sessionId = sessionId;
  }

  clearSession(): void {
    this.sessionId = null;
  }
}

// Export singleton instance
export const jarvisAPI = new JarvisAPI();

// React Hook
export function useJarvisAPI() {
  return jarvisAPI;
}
