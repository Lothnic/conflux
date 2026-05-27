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
    bounds?: { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
  };
  summary: string;
  recommendations: string[];
  funding_sources: string[];
  sources?: { id: string; subreddit: string; title: string }[];
  estimated_budget: string;
  size?: number;
}

export interface ClusterResult {
  cluster_id: string;
  cluster_label: number;
  centroid_lat: number;
  centroid_lng: number;
  size: number;
  keywords: string;
  created_at: string | null;
}

export interface DashboardData {
  health: HealthCheck | null;
  threads: RedditThread[];
  ingestSource: string;
  proposals: ClusterProposal[];
}

export type LoadingState = "loading" | "loaded" | "error";
