import type { ClusterProposal, RedditThread } from "./types";

export const ISSUE_CATEGORIES = [
  "Transportation",
  "Safety",
  "Environment",
  "Infrastructure",
  "Housing",
] as const;

export type IssueCategory = (typeof ISSUE_CATEGORIES)[number];

export const CATEGORY_COLORS: Record<IssueCategory, string> = {
  Transportation: "#d92d20",
  Safety: "#b42318",
  Environment: "#067647",
  Infrastructure: "#175cd3",
  Housing: "#7a2e0e",
};

export const CATEGORY_BG: Record<IssueCategory, string> = {
  Transportation: "#fff1f0",
  Safety: "#fef3f2",
  Environment: "#ecfdf3",
  Infrastructure: "#eff8ff",
  Housing: "#fff7ed",
};

export function issueCategory(issueType: string): IssueCategory {
  const normalized = issueType.toLowerCase();
  if (normalized.includes("traffic") || normalized.includes("road") || normalized.includes("transit")) {
    return "Transportation";
  }
  if (normalized.includes("lighting") || normalized.includes("safety") || normalized.includes("crime")) {
    return "Safety";
  }
  if (normalized.includes("environment") || normalized.includes("park") || normalized.includes("sanitation")) {
    return "Environment";
  }
  if (normalized.includes("housing") || normalized.includes("shelter")) {
    return "Housing";
  }
  return "Infrastructure";
}

export function severityScore(issue: ClusterProposal): number {
  const base = issue.urgency === "high" ? 86 : issue.urgency === "medium" ? 61 : 34;
  const sizeBoost = Math.min(Math.max(issue.size ?? 1, 1) * 2, 10);
  return Math.min(base + sizeBoost, 98);
}

export function severityLabel(score: number): string {
  if (score >= 80) return "Critical";
  if (score >= 60) return "Elevated";
  if (score >= 40) return "Moderate";
  return "Routine";
}

export function issueTitle(issue: ClusterProposal): string {
  return issue.issue_type;
}

export function evidenceCount(issue: ClusterProposal, threads: RedditThread[]): number {
  const linkedThreads = threads.filter((thread) => thread.cluster_id === issue.cluster_id).length;
  return Math.max(issue.sources?.length ?? 0, linkedThreads);
}

export function reportedDate(issue: ClusterProposal, threads: RedditThread[]): string {
  const dates = threads
    .filter((thread) => thread.cluster_id === issue.cluster_id && thread.created_utc)
    .map((thread) => new Date(thread.created_utc).getTime())
    .filter((time) => Number.isFinite(time));

  const time = dates.length > 0 ? Math.max(...dates) : Date.now();
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(time));
}

export function coordinateLabel(issue: ClusterProposal): string {
  return `${issue.location.lat.toFixed(4)}, ${issue.location.lon.toFixed(4)}`;
}

export function locationConfidenceLabel(confidence?: number | null): string {
  if (confidence == null) return "Unscored estimate";
  if (confidence >= 0.75) return "High-confidence estimate";
  if (confidence >= 0.5) return "Medium-confidence estimate";
  if (confidence > 0) return "Low-confidence estimate";
  return "Unresolved estimate";
}

export function locationPrecisionLabel(precisionMeters?: number | null): string {
  if (!precisionMeters) return "Precision unknown";
  if (precisionMeters <= 150) return `Street-level, ~${precisionMeters}m`;
  if (precisionMeters <= 1000) return `Area-level, ~${precisionMeters}m`;
  return `Broad area, ~${Math.round(precisionMeters / 1000)}km`;
}
