export interface SubscriptionSummary {
  account_type: string;
  subscription_status: string;
  is_full_access: boolean;
  daily_query_count: number;
  script_generation_count: number;
  presentation_generation_count: number;
}

export interface MobileUser {
  id: number;
  full_name: string;
  email: string;
  role: string;
  subscription: SubscriptionSummary;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: 'Bearer';
  expires_in: number;
  user?: MobileUser;
}

export interface StoredSession {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

export interface AskSource {
  arquivo?: string;
  documento?: string;
  source?: string;
  local?: string;
  marcador?: string;
}

export interface SearchHistoryItem {
  id: number;
  normalized_topic: string;
  display_title: string;
  topic_category: string;
  depth_level: 'resumido' | 'explicativo' | 'aprofundado';
  language: string;
  created_at: string;
  last_searched_at: string;
  search_count: number;
  repeated: boolean;
  query?: string;
}

export interface AskMetadata {
  plan: {
    topic: string;
    category: string;
    depth: string;
    composite: boolean;
    components: string[];
    covered_components: string[];
    continuation_required: boolean;
  };
  suggestions: string[];
  continuation_query: string;
  cache_hit: boolean;
  coverage: Record<string, unknown>;
}

export type AskEvent =
  | { tipo: 'fontes'; request_id: string; mensagem_busca: string; fontes: AskSource[] }
  | { tipo: 'texto'; texto: string; status_revisao: string; motivo_revisao: string }
  | ({ tipo: 'metadados' } & AskMetadata)
  | { tipo: 'erro'; mensagem: string }
  | { tipo: 'fim' };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
