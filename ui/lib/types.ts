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
  audit_status?: string;
  is_compliant?: boolean | null;
  verdict?: string | null;
  summary?: string | null;
  narration_source?: string | null;
  ratios?: Record<string, RatioComputation> | null;
  market_cap_used?: number | null;
  trailing_cap_used?: number | null;
};

export type MarketQuote = {
  symbol: string;
  market_cap?: number | null;
  share_price?: number | null;
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
