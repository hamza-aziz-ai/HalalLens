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
    accounts_receivable?: Numeric;
    liquid_assets?: Numeric;
  };
  market_data: {
    market_cap?: Numeric;
    trailing_market_cap?: Numeric;
    share_price?: Numeric;
    provider?: string | null;
  };
};

export type RatioComputation = {
  value: number | null;
  threshold: number;
  passed: boolean | null;
  note: string;
  provider?: string | null;
};

export type HalalScoreResponse = {
  symbol: string;
  filing_date: string;
  is_compliant: boolean;
  ratios: Record<string, RatioComputation>;
  missing_inputs: Record<string, string>;
  market_cap_used?: Numeric;
  trailing_cap_used?: Numeric;
  market_data_provider?: string | null;
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
  narration: NarrationResponse | null;
};

export type BillingPlan = {
  code: string;
  name: string;
  price_inr: number;
  interval_days: number;
  features: string[];
  is_active: boolean;
};

export type RazorpayOrderResponse = {
  key_id: string;
  order_id: string;
  amount: number;
  currency: string;
  plan_code: string;
  plan_name: string;
  email: string;
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

export type FeedbackEvent = {
  id: number;
  feedback_id: number;
  event_type: string;
  status?: string | null;
  reviewer?: string | null;
  details?: string | null;
  source?: string | null;
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
  events?: FeedbackEvent[];
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

export type GovernanceMetricSet = {
  label: string;
  source: string;
  metrics: Record<string, number | null | undefined>;
  applied?: boolean | null;
  reviewer?: string | null;
  reason?: string | null;
  notes?: string | null;
  updated_at?: string | null;
  snapshot_date?: string | null;
  market_cap?: number | null;
};

export type GovernanceDifferences = Record<
  string,
  {
    override_delta?: number | null;
    indian_delta?: number | null;
  }
>;

export type GovernanceReview = {
  symbol: string;
  filing_date: string;
  ingested: GovernanceMetricSet;
  override?: GovernanceMetricSet | null;
  indian_api?: GovernanceMetricSet | null;
  differences: GovernanceDifferences;
};

export type UserProfile = {
  id: number;
  email: string;
  plan: string;
  subscription_status: string;
  subscription_renewal?: string | null;
  full_name?: string | null;
  avatar_url?: string | null;
};
