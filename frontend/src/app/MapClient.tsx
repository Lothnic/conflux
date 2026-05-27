'use client';

import { useEffect, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

type Cluster = {
  cluster_id: string;
  cluster_label: number;
  centroid_lat: number;
  centroid_lng: number;
  size: number;
  keywords: string;
  created_at: string | null;
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

type MapClientProps = {
  clusters: Cluster[];
  proposals: Proposal[];
  threadsGeojson: ThreadGeoJSON | null;
};

type LayerState = {
  showThreads: boolean;
  showClusters: boolean;
  urgency: 'all' | 'high' | 'medium' | 'low';
};

const urgencyColor: Record<string, string> = {
  high: '#dc2626',
  medium: '#f59e0b',
  low: '#16a34a',
};

function getUrgency(clusterId: string, proposals: Proposal[]): string {
  const match = proposals.find((p) => p.cluster_id === clusterId);
  return match?.urgency || 'low';
}

function getPopupHTML(cluster: Cluster, proposals: Proposal[]): string {
  const proposal = proposals.find((p) => p.cluster_id === cluster.cluster_id);
  if (!proposal) {
    return `<div><strong>${cluster.keywords || 'No keywords'}</strong><div>size: ${cluster.size}</div></div>`;
  }
  const recs = proposal.recommendations
    .map((r) => `<li>${r}</li>`)
    .join('');
  return `
    <div style="min-width:220px">
      <div style="font-weight:600">${proposal.issue_type}</div>
      <div style="margin-top:4px">${proposal.summary}</div>
      <div style="margin-top:6px;font-size:12px;color:#555">urgency: ${proposal.urgency}</div>
      <div style="margin-top:6px;font-size:12px;color:#555">budget: ${proposal.estimated_budget}</div>
      <div style="margin-top:6px">Recommendations:</div>
      <ul style="padding-left:16px;margin:4px 0 0 0">${recs}</ul>
    </div>
  `;
}

export default function MapClient({ clusters, proposals, threadsGeojson }: MapClientProps) {
  const [layers, setLayers] = useState<LayerState>({
    showThreads: true,
    showClusters: true,
    urgency: 'all',
  });

  useEffect(() => {
    const map = L.map('conflux-map', {
      zoomControl: true,
    }).setView([28.6139, 77.209], 11);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    if (layers.showThreads && threadsGeojson && threadsGeojson.features.length > 0) {
      threadsGeojson.features.forEach((f) => {
        const [lng, lat] = f.geometry.coordinates;
        const dot = L.circleMarker([lat, lng], {
          radius: 3,
          color: '#2563eb',
          fillColor: '#3b82f6',
          fillOpacity: 0.5,
          weight: 1,
        });
        dot.bindPopup(`<div>thread: ${f.properties.thread_id}</div>`);
        dot.addTo(map);
      });
    }

    if (layers.showClusters) {
      clusters.forEach((c) => {
        if (typeof c.centroid_lat !== 'number' || typeof c.centroid_lng !== 'number') return;
        const urgency = getUrgency(c.cluster_id, proposals);
        if (layers.urgency !== 'all' && urgency !== layers.urgency) return;
        const color = urgencyColor[urgency] || urgencyColor.low;
        const radius = Math.max(6, Math.min(30, c.size * 2));

        const marker = L.circleMarker([c.centroid_lat, c.centroid_lng], {
          radius,
          color,
          fillColor: color,
          fillOpacity: 0.6,
          weight: 2,
        });

        marker.bindPopup(getPopupHTML(c, proposals));
        marker.addTo(map);
      });
    }

    return () => {
      map.remove();
    };
  }, [clusters, proposals, threadsGeojson, layers]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm text-zinc-700">
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={layers.showClusters}
            onChange={(e) => setLayers((s) => ({ ...s, showClusters: e.target.checked }))}
          />
          Show clusters
        </label>
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={layers.showThreads}
            onChange={(e) => setLayers((s) => ({ ...s, showThreads: e.target.checked }))}
          />
          Show threads
        </label>
        <label className="inline-flex items-center gap-2">
          Urgency
          <select
            className="rounded border border-zinc-300 bg-white px-2 py-1"
            value={layers.urgency}
            onChange={(e) => setLayers((s) => ({ ...s, urgency: e.target.value as LayerState['urgency'] }))}
          >
            <option value="all">All</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <div className="ml-auto flex items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-600"></span>High</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-amber-500"></span>Medium</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-green-600"></span>Low</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-blue-600"></span>Thread</span>
        </div>
      </div>
      <div id="conflux-map" className="h-96 w-full rounded-lg border border-zinc-200" />
    </div>
  );
}
