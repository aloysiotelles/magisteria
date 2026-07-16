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
  documento?: string;
  source?: string;
  local?: string;
}

export type AskEvent =
  | { tipo: 'fontes'; request_id: string; mensagem_busca: string; fontes: AskSource[] }
  | { tipo: 'texto'; texto: string; status_revisao: string; motivo_revisao: string }
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
