export interface HealthCheck {
  status: string;
  service: string;
}

export interface RedditThread {
  id: string;
  title: string;
  url: string;
  author: string;
  created_utc: string;
  upvotes: number;
  num_comments: number;
  flair: string;
  content: string;
  subreddit: string;
  lat?: number;
  lng?: number;
  cluster_id?: string;
  location_text?: string | null;
  location_method?: string | null;
  location_confidence?: number | null;
  location_precision_meters?: number | null;
}

export interface IngestResponse {
  status: string;
  source: string;
  count: number;
  flair_breakdown: Record<string, number>;
}

export interface ClusterProposal {
  cluster_id: string;
  issue_type: string;
  urgency: "low" | "medium" | "high";
  location: {
    lat: number;
    lon: number;
    confidence?: number | null;
    precision_meters?: number | null;
    method?: string | null;
    bounds?: { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
  };
  summary: string;
  recommendations: string[];
  funding_sources: string[];
  communication_plan: string[];
  responsible_agencies: string[];
  impact_rationale: string;
  sources?: { id: string; subreddit: string; title: string; url?: string }[];
  estimated_budget: string;
  size?: number;
}

export interface AgentStepTrace {
  step_name: string;
  tool_name: string;
  status: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  created_at: string | null;
}

export interface AgentRunTrace {
  run_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  steps: AgentStepTrace[];
}

export interface ClusterResult {
  cluster_id: string;
  cluster_label: number;
  centroid_lat: number;
  centroid_lng: number;
  size: number;
  keywords: string;
  created_at: string | null;
  location_confidence?: number | null;
  location_precision_meters?: number | null;
}

export interface DashboardData {
  health: HealthCheck | null;
  threads: RedditThread[];
  ingestSource: string;
  proposals: ClusterProposal[];
}

export type LoadingState = "loading" | "loaded" | "error";
