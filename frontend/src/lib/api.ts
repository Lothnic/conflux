import type { HealthCheck, RedditThread, ClusterProposal } from "./types";

const BASE_URL = "/api";

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, options);
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export async function getHealth(): Promise<HealthCheck> {
  return fetchJSON<HealthCheck>("/health");
}

export async function getIngestedThreads(): Promise<{
  threads: RedditThread[];
  source: string;
  count: number;
}> {
  return fetchJSON<{
    threads: RedditThread[];
    source: string;
    count: number;
  }>("/threads");
}

export async function getProposals(): Promise<ClusterProposal[]> {
  const data = await fetchJSON<{ proposals: ClusterProposal[] }>("/proposals");
  return data.proposals;
}

export async function generateProposal(clusterId: string): Promise<ClusterProposal> {
  const data = await fetchJSON<{ proposal: ClusterProposal }>(
    `/proposals/generate/${clusterId}`,
    { method: "POST" }
  );
  return data.proposal;
}
