export type Numeric = number | undefined;

export type AnalysisPayload = {
  snapshot: {
    symbol: string;
    filing_date: string;
    total_debt?: Numeric;
    cash_equiv?: Numeric;
    revenue?: Numeric;
    interest_income?: Numeric;
    dividend_income?: Numeric;
    non_permissible_income?: Numeric;
  };
  market_data: {
    market_cap?: Numeric;
    trailing_market_cap?: Numeric;
    share_price?: Numeric;
  };
};

export type RatioComputation = {
  value: number | null;
  threshold: number;
  passed: boolean | null;
  note: string;
};

export type HalalScoreResponse = {
  symbol: string;
  filing_date: string;
  is_compliant: boolean;
  ratios: Record<string, RatioComputation>;
  missing_inputs: Record<string, string>;
};

export type NarrationResponse = {
  symbol: string;
  filing_date: string;
  is_compliant: boolean;
  summary: string;
  verdict: string;
  bullets: string[];
  citations: string[];
  source?: string | null;
};

export type AnalysisResponse = {
  score: HalalScoreResponse;
  narration: NarrationResponse;
};

export type Filing = {
  symbol: string;
  company_name?: string;
  filing_date: string;
  category?: string;
  headline?: string;
  confidence?: string;
  total_debt?: number;
  cash_equiv?: number;
  revenue?: number;
  interest_income?: number;
  dividend_income?: number;
  accounts_receivable?: number;
  liquid_assets?: number;
  non_halal_income?: number;
  governance_notes?: string;
  governance_override_applied?: boolean;
  governance_override_source?: string | null;
  governance_override_reason?: string | null;
  governance_override_reviewer?: string | null;
  governance_override_updated_at?: string | null;
  audit_status?: string;
  is_compliant?: boolean | null;
  verdict?: string | null;
  summary?: string | null;
  narration_source?: string | null;
  ratios?: Record<string, RatioComputation> | null;
  market_cap_used?: number | null;
  trailing_cap_used?: number | null;
  market_data_provider?: string | null;
  quality_issues?: string[];
};

export type MarketQuote = {
  symbol: string;
  market_cap?: number | null;
  share_price?: number | null;
  provider?: string | null;
};

export type WatchlistEntry = {
  user_id: string;
  symbol: string;
  trigger: string;
};

export type AlertEvent = {
  user_id: string;
  symbol: string;
  trigger: string;
  message: string;
};

export type IngestionStats = {
  total_announcements: number;
  financial_snapshots: number;
  high_confidence?: number;
  latest_filing?: string | null;
};

export type FeedbackPayload = {
  symbol?: string;
  filing_date?: string;
  verdict?: string | null;
  message: string;
  contact?: string;
};

export type FeedbackReport = {
  id: number;
  symbol?: string | null;
  filing_date?: string | null;
  verdict?: string | null;
  message: string;
  contact?: string | null;
  source?: string | null;
  status: string;
  review_notes?: string | null;
  resolved_at?: string | null;
  resolved_by?: string | null;
  public_token?: string | null;
  status_updated_at: string;
  reevaluated_at?: string | null;
  reevaluation_notes?: string | null;
  created_at: string;
};

export type FeedbackSubmissionResponse = {
  status: string;
  ticket_id: number;
  tracking_token: string;
};

export type FeedbackTrackingStatus = {
  ticket_id: number;
  symbol?: string | null;
  filing_date?: string | null;
  verdict?: string | null;
  message: string;
  status: string;
  review_notes?: string | null;
  created_at: string;
  status_updated_at: string;
  resolved_at?: string | null;
  reevaluated_at?: string | null;
  reevaluation_notes?: string | null;
};

export type GovernanceOverride = {
  symbol: string;
  filing_date: string;
  accounts_receivable?: number | null;
  liquid_assets?: number | null;
  non_halal_income?: number | null;
  governance_notes?: string | null;
  reviewer?: string | null;
  reason?: string | null;
  source?: string | null;
  created_at: string;
  updated_at: string;
};
