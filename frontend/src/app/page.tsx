type Cluster = {
  cluster_id: string;
  cluster_label: number;
  centroid_lat: number;
  centroid_lng: number;
  size: number;
  keywords: string;
  created_at: string | null;
};

import MapClient from './MapClient';

type ClusterResponse = {
  clusters: Cluster[];
};

type Proposal = {
  cluster_id: string;
  issue_type: string;
  urgency: string;
  location: {
    centroid_lat: number;
    centroid_lng: number;
  };
  summary: string;
  recommendations: string[];
  funding_sources: string[];
  estimated_budget: string;
};

type ProposalResponse = {
  proposals: Proposal[];
};

type ThreadFeature = {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: {
    thread_id: string;
    source: string;
    created_at: string | null;
  };
};

type ThreadGeoJSON = {
  type: 'FeatureCollection';
  features: ThreadFeature[];
};

export const dynamic = 'force-dynamic';

async function fetchClusters(): Promise<ClusterResponse> {
  const res = await fetch('http://localhost:8000/clusters?limit=50', {
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Failed to load clusters: ${res.status}`);
  }
  return res.json();
}

async function fetchProposals(): Promise<ProposalResponse> {
  const res = await fetch('http://localhost:8000/proposals?limit=20', {
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Failed to load proposals: ${res.status}`);
  }
  return res.json();
}

async function fetchThreadsGeojson(): Promise<ThreadGeoJSON> {
  const res = await fetch('http://localhost:8000/threads/geojson?limit=300', {
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Failed to load thread geojson: ${res.status}`);
  }
  return res.json();
}

export default async function Home() {
  let data: ClusterResponse | null = null;
  let proposals: ProposalResponse | null = null;
  let threadsGeojson: ThreadGeoJSON | null = null;
  let error: string | null = null;

  try {
    [data, proposals, threadsGeojson] = await Promise.all([
      fetchClusters(),
      fetchProposals(),
      fetchThreadsGeojson(),
    ]);
  } catch (e: any) {
    error = e?.message || 'Unknown error';
  }

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900">
      <main className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-8">
          <h1 className="text-3xl font-semibold tracking-tight">Conflux Hotspots</h1>
          <p className="mt-2 text-zinc-600">
            Clustered citizen complaints with geospatial centroids, keywords, and draft proposals.
          </p>
        </header>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-red-700">
            {error}
          </div>
        )}

        {!error && (!data || data.clusters.length === 0) && (
          <div className="rounded-lg border border-zinc-200 bg-white px-4 py-3 text-zinc-600">
            No clusters available yet. Run the worker to ingest and cluster data.
          </div>
        )}

        {!error && data && data.clusters.length > 0 && (
          <section className="mb-10">
            <h2 className="mb-3 text-xl font-semibold">Hotspot Clusters</h2>
            <MapClient
              clusters={data.clusters}
              proposals={proposals?.proposals || []}
              threadsGeojson={threadsGeojson}
            />
            <div className="mt-6 grid gap-4">
              {data.clusters.map((c) => (
                <div key={c.cluster_id} className="rounded-lg border border-zinc-200 bg-white p-4">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-zinc-500">{c.cluster_id}</div>
                    <div className="text-sm text-zinc-500">size: {c.size}</div>
                  </div>
                  <div className="mt-2 text-lg font-medium">{c.keywords || 'No keywords'}</div>
                  <div className="mt-2 text-sm text-zinc-600">
                    centroid: {c.centroid_lat?.toFixed(4)}, {c.centroid_lng?.toFixed(4)}
                  </div>
                  {c.created_at && (
                    <div className="mt-1 text-xs text-zinc-400">created: {c.created_at}</div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {!error && proposals && proposals.proposals.length > 0 && (
          <section>
            <h2 className="mb-3 text-xl font-semibold">Draft Proposals</h2>
            <div className="grid gap-4">
              {proposals.proposals.map((p) => (
                <div key={p.cluster_id} className="rounded-lg border border-zinc-200 bg-white p-4">
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-zinc-500">{p.cluster_id}</div>
                    <div className="text-sm text-zinc-500">urgency: {p.urgency}</div>
                  </div>
                  <div className="mt-2 text-lg font-medium">{p.issue_type}</div>
                  <div className="mt-1 text-sm text-zinc-600">{p.summary}</div>
                  <div className="mt-2 text-sm text-zinc-600">
                    centroid: {p.location.centroid_lat?.toFixed(4)}, {p.location.centroid_lng?.toFixed(4)}
                  </div>
                  <div className="mt-3">
                    <div className="text-xs uppercase text-zinc-500">Recommendations</div>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-zinc-700">
                      {p.recommendations.map((r, idx) => (
                        <li key={idx}>{r}</li>
                      ))}
                    </ul>
                  </div>
                  <div className="mt-3 text-sm text-zinc-600">
                    Funding: {p.funding_sources.join(', ')}
                  </div>
                  <div className="mt-1 text-sm text-zinc-600">
                    Estimated budget: {p.estimated_budget}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
