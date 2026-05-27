"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import Header from "@/components/Header";
import Sidebar from "@/components/Sidebar";
import type { ClusterProposal, DashboardData, LoadingState } from "@/lib/types";
import { getHealth, getProposals, getIngestedThreads } from "@/lib/api";

const MapSection = dynamic(() => import("@/components/MapSection"), { ssr: false });

const ISSUE_TYPES = [
  "Road & Traffic",
  "Sanitation",
  "Water & Drainage",
  "Public Lighting",
  "Public Space & Environment",
  "General Infrastructure",
];

export type MapLayer = "satellite" | "street";

export default function Home() {
  const [data, setData] = useState<DashboardData>({
    health: null,
    threads: [],
    ingestSource: "",
    proposals: [],
  });
  const [state, setState] = useState<LoadingState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [selectedCluster, setSelectedCluster] = useState<ClusterProposal | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mapLayer, setMapLayer] = useState<MapLayer>("satellite");
  const [filterIssueType, setFilterIssueType] = useState<string | null>(null);

  const handleSelectCluster = useCallback((c: ClusterProposal | null) => {
    setSelectedCluster(c);
    if (c && sidebarCollapsed) {
      setSidebarCollapsed(false);
    }
  }, [sidebarCollapsed]);

  const handleToggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
    if (!sidebarCollapsed) {
      setSelectedCluster(null);
    }
  }, [sidebarCollapsed]);

  const handleUpdateProposal = useCallback((clusterId: string, updated: ClusterProposal) => {
    setData((prev) => ({
      ...prev,
      proposals: prev.proposals.map((p) =>
        p.cluster_id === clusterId ? updated : p
      ),
    }));
    setSelectedCluster((prev) =>
      prev?.cluster_id === clusterId ? updated : prev
    );
  }, []);

  const filteredProposals = useMemo(() => {
    if (!filterIssueType) return data.proposals;
    return data.proposals.filter((p) => p.issue_type === filterIssueType);
  }, [data.proposals, filterIssueType]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [health, proposals, ingest] = await Promise.all([
          getHealth(),
          getProposals().catch(() => []),
          getIngestedThreads().catch(() => ({
            threads: [] as never[],
            source: "",
            count: 0,
          })),
        ]);

        if (!cancelled) {
          setData({
            health,
            threads: ingest.threads,
            ingestSource: ingest.source,
            proposals,
          });
          setState("loaded");
        }
      } catch (err) {
        if (!cancelled) {
          setErrorMessage(err instanceof Error ? err.message : "Failed to load data");
          setState("error");
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="relative w-full h-screen overflow-hidden" style={{ background: "#0c0c0c" }}>
      <MapSection
        proposals={filteredProposals}
        threads={data.threads}
        isLoading={state === "loading"}
        selectedCluster={selectedCluster}
        onSelectCluster={handleSelectCluster}
        mapLayer={mapLayer}
      />

      <Header
        health={data.health}
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={handleToggleSidebar}
        mapLayer={mapLayer}
        onMapLayerChange={setMapLayer}
        filterIssueType={filterIssueType}
        onFilterChange={setFilterIssueType}
      />

      <Sidebar
        proposals={filteredProposals}
        threads={data.threads}
        selectedCluster={selectedCluster}
        health={data.health}
        ingestSource={data.ingestSource}
        loading={state === "loading"}
        onSelectCluster={handleSelectCluster}
        onToggle={handleToggleSidebar}
        collapsed={sidebarCollapsed}
        onUpdateProposal={handleUpdateProposal}
      />

      {state === "error" && (
        <div
          className="fixed top-4 right-4 z-[100] max-w-sm rounded-xl p-4 animate-fade-in-up"
          style={{
            background: "rgba(251,113,133,0.08)",
            border: "1px solid rgba(251,113,133,0.15)",
            backdropFilter: "blur(16px)",
          }}
        >
          <div className="flex items-center gap-2 mb-1">
            <svg
              className="w-4 h-4 flex-shrink-0"
              style={{ color: "#fb7185" }}
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
              />
            </svg>
            <p className="text-sm font-medium" style={{ color: "#fb7185" }}>
              Connection Error
            </p>
          </div>
          <p className="text-xs" style={{ color: "rgba(251,113,133,0.6)" }}>
            {errorMessage}. Make sure the backend is running on port 8000.
          </p>
        </div>
      )}
    </div>
  );
}
