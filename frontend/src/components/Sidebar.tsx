"use client";

import { useState } from "react";
import type { ClusterProposal, RedditThread, HealthCheck } from "@/lib/types";
import { generateProposal } from "@/lib/api";

const URGENCY_CONFIG: Record<string, { color: string; bg: string; label: string; pct: number }> = {
  high: { color: "#e63946", bg: "#e6394615", label: "High Priority", pct: 90 },
  medium: { color: "#e8a634", bg: "#e8a63415", label: "Medium Priority", pct: 55 },
  low: { color: "#2d9a5c", bg: "#2d9a5c15", label: "Low Priority", pct: 25 },
};

interface SidebarProps {
  proposals: ClusterProposal[];
  threads: RedditThread[];
  selectedCluster: ClusterProposal | null;
  health: HealthCheck | null;
  ingestSource: string;
  loading: boolean;
  onSelectCluster: (c: ClusterProposal | null) => void;
  onToggle: () => void;
  collapsed: boolean;
  onUpdateProposal: (clusterId: string, updated: ClusterProposal) => void;
}

function shortClusterId(clusterId: string): string {
  const parts = clusterId.split("-");
  return parts[parts.length - 1] || clusterId;
}

export default function Sidebar({
  proposals,
  threads,
  selectedCluster,
  health,
  ingestSource,
  loading,
  onSelectCluster,
  onToggle,
  collapsed,
  onUpdateProposal,
}: SidebarProps) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState("");

  const validProposals = proposals.filter(
    (p) => p.location && typeof p.location.lat === "number" && typeof p.location.lon === "number"
  );
  const displayProposals = validProposals.length > 0 ? validProposals : [];

  if (collapsed) {
    return (
      <aside
        className="fixed left-0 top-0 bottom-0 z-50 flex flex-col items-center pt-4 pb-5 w-12"
        style={{
          background: "var(--sidebar-bg)",
          borderRight: "1px solid var(--sidebar-border)",
        }}
      >
        <button
          onClick={onToggle}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[10px] font-bold mb-5"
          style={{ background: "#e63946", color: "#fff" }}
        >
          C
        </button>

        <div className="flex-1 flex flex-col items-center gap-2">
          {displayProposals.slice(0, 6).map((c) => {
            const urg = URGENCY_CONFIG[c.urgency] ?? URGENCY_CONFIG.medium;
            const isSel = selectedCluster?.cluster_id === c.cluster_id;
            return (
              <button
                key={c.cluster_id}
                onClick={() => onSelectCluster(isSel ? null : c)}
                className="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold transition-all duration-200"
                style={{
                  background: urg.bg,
                  color: urg.color,
                  outline: isSel ? `2px solid ${urg.color}` : "none",
                  outlineOffset: "2px",
                  transform: isSel ? "scale(1.2)" : "scale(1)",
                }}
                title={c.cluster_id}
              >
                {shortClusterId(c.cluster_id)}
              </button>
            );
          })}
        </div>

        <span
          className="block w-2 h-2 rounded-full mt-auto"
          style={{ background: health?.status === "ok" ? "var(--color-emerald)" : "var(--color-rose)" }}
        />
      </aside>
    );
  }

  if (selectedCluster) {
    const c = selectedCluster;
    const urg = URGENCY_CONFIG[c.urgency] ?? URGENCY_CONFIG.medium;

    return (
      <aside
        className="fixed left-0 top-0 bottom-0 z-50 w-[320px] max-w-[85vw] flex flex-col animate-fade-in-up overflow-hidden"
        style={{
          background: "var(--sidebar-bg)",
          borderRight: "1px solid var(--sidebar-border)",
        }}
      >
        <div className="flex items-center gap-2 px-4 py-3.5" style={{ borderBottom: "1px solid var(--sidebar-border)" }}>
          <button
            onClick={() => onSelectCluster(null)}
            className="flex-shrink-0 w-7 h-7 rounded-md flex items-center justify-center transition-colors hover:bg-[#eeece8]"
          >
            <svg className="w-4 h-4" style={{ color: "var(--sidebar-text-muted)" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
            </svg>
          </button>
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <span
              className="flex-shrink-0 w-3 h-3 rounded-full"
              style={{ background: urg.color }}
            />
            <h2 className="text-[14px] font-semibold truncate" style={{ color: "var(--sidebar-text)" }}>
              {c.issue_type}
            </h2>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="px-5 pt-5 pb-4">
            <div className="flex items-center gap-1.5 mb-3">
              <svg className="w-3.5 h-3.5" style={{ color: "var(--sidebar-text-muted)" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
              </svg>
              <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--sidebar-text-muted)" }}>Summary</span>
            </div>
            <p className="text-[13px] leading-[1.65]" style={{ color: "var(--sidebar-text-secondary)" }}>
              {c.summary}
            </p>
          </div>

          <div className="mx-5 h-px" style={{ background: "var(--sidebar-border)" }} />

          <div className="px-5 py-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-1.5">
                <svg className="w-3.5 h-3.5" style={{ color: "var(--sidebar-text-muted)" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0-10.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                </svg>
                <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--sidebar-text-muted)" }}>Urgency</span>
              </div>
              <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded" style={{ color: urg.color, background: urg.bg }}>
                {urg.label}
              </span>
            </div>
            <div className="relative h-2 rounded-full overflow-hidden" style={{ background: "#e8e5e0" }}>
              <div
                className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                style={{
                  width: `${urg.pct}%`,
                  background: `linear-gradient(90deg, #2d9a5c, #e8a634 50%, #e63946)`,
                }}
              />
              <div
                className="absolute top-1/2 -translate-y-1/2 w-3.5 h-3.5 rounded-full border-2 border-white shadow-md transition-all duration-500"
                style={{
                  left: `${urg.pct}%`,
                  transform: `translateX(-50%) translateY(-50%)`,
                  background: urg.color,
                }}
              />
            </div>
            <p className="text-[12px] leading-[1.6] mt-3" style={{ color: "var(--sidebar-text-secondary)" }}>
              {c.urgency === "high"
                ? "This issue poses an immediate risk to public safety and wellbeing, requiring swift intervention and resource allocation."
                : c.urgency === "medium"
                  ? "Moderate concern requiring planned intervention within the near term to prevent escalation."
                  : "Lower priority issue that should be monitored and addressed during routine maintenance cycles."}
            </p>
          </div>

          <div className="mx-5 h-px" style={{ background: "var(--sidebar-border)" }} />

          <div className="px-5 py-4">
            <div className="flex items-center justify-between w-full">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4" style={{ color: "var(--sidebar-text)" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
                <span className="text-[14px] font-bold" style={{ color: "var(--sidebar-text)" }}>Sources</span>
              </div>
              <button
                onClick={() => setSourcesOpen(!sourcesOpen)}
                className="w-6 h-6 rounded flex items-center justify-center transition-colors hover:bg-[#e2e0dc]"
                style={{ background: "#eeece8", color: "var(--sidebar-text)" }}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d={sourcesOpen ? "M19.5 12h-15" : "M12 4.5v15m7.5-7.5h-15"} />
                </svg>
              </button>
            </div>
            {sourcesOpen && (
              <div className="mt-4 grid grid-cols-2 gap-2 animate-fade-in">
                {c.sources && c.sources.length > 0 ? (
                  c.sources.slice(0, 4).map((s, i) => (
                    <a
                      key={i}
                      href={`https://reddit.com/r/${s.subreddit}/comments/${s.id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-3 rounded-lg flex flex-col justify-between h-[76px] transition-colors hover:bg-gray-50"
                      style={{ background: "#ffffff", border: "1px solid var(--sidebar-card-border)" }}
                    >
                      <div>
                        <div className="w-5 h-5 rounded-full flex items-center justify-center mb-1.5" style={{ background: "#ff4500" }}>
                          <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M24 11.779c0-1.459-1.192-2.645-2.657-2.645-.715 0-1.363.286-1.84.746-1.81-1.191-4.259-1.949-6.971-2.046l1.483-4.669 4.016.941-.006.058c0 1.193.975 2.163 2.174 2.163 1.198 0 2.172-.97 2.172-2.163s-.975-2.164-2.172-2.164c-.92 0-1.704.574-2.021 1.379l-4.329-1.015c-.189-.046-.381.063-.44.249l-1.654 5.207c-2.838.034-5.409.798-7.3 2.025-.474-.438-1.103-.712-1.799-.712-1.465 0-2.656 1.187-2.656 2.646 0 .97.533 1.811 1.317 2.271-.052.282-.086.567-.086.857 0 3.911 4.808 7.093 10.719 7.093s10.72-3.182 10.72-7.093c0-.274-.029-.544-.075-.81.832-.447 1.405-1.312 1.405-2.318zm-17.224 1.816c0-.868.71-1.575 1.582-1.575.872 0 1.581.707 1.581 1.575s-.709 1.574-1.581 1.574-1.582-.706-1.582-1.574zm9.061 4.669c-1.797 1.768-4.698 1.768-6.495 0-.171-.168-.171-.439 0-.608.172-.169.45-.169.622 0 1.455 1.434 3.821 1.434 5.273 0 .172-.169.45-.169.622 0 .172.169.172.44 0 .608zm-.525-3.095c-.872 0-1.582-.706-1.582-1.574 0-.868.71-1.575 1.582-1.575.871 0 1.581.707 1.581 1.575s-.71 1.574-1.581 1.574z"/></svg>
                        </div>
                      </div>
                      <span className="text-[11px] font-medium leading-[1.2] line-clamp-2" style={{ color: "var(--sidebar-text-secondary)" }}>{s.title}</span>
                    </a>
                  ))
                ) : (
                  <div className="col-span-2 text-center py-4">
                    <p className="text-[11px]" style={{ color: "var(--sidebar-text-muted)" }}>No external sources found.</p>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="mx-5 h-px" style={{ background: "var(--sidebar-border)" }} />

          <div className="px-5 py-4">
            <div className="flex items-center gap-1.5 mb-3">
              <svg className="w-3.5 h-3.5" style={{ color: "var(--sidebar-text-muted)" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
              </svg>
              <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--sidebar-text-muted)" }}>Improvement</span>
            </div>
            <ul className="space-y-2">
              {c.recommendations.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-[12px] leading-[1.55]" style={{ color: "var(--sidebar-text-secondary)" }}>
                  <span className="flex-shrink-0 w-1.5 h-1.5 rounded-full mt-1.5" style={{ background: "#e63946" }} />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="px-5 py-3.5" style={{ borderTop: "1px solid var(--sidebar-border)" }}>
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] font-medium" style={{ color: "var(--sidebar-text-muted)" }}>Estimated Budget</span>
            <span className="text-[14px] font-bold" style={{ color: "var(--sidebar-text)" }}>{c.estimated_budget}</span>
          </div>
          <button
            onClick={async () => {
              setGenerating(true);
              setGenError("");
              try {
                const proposal = await generateProposal(c.cluster_id);
                onUpdateProposal(c.cluster_id, proposal);
              } catch (e) {
                setGenError(e instanceof Error ? e.message : "Failed to generate proposal");
              } finally {
                setGenerating(false);
              }
            }}
            disabled={generating}
            className="w-full py-2.5 rounded-lg text-[12px] font-semibold transition-all duration-200"
            style={{
              background: generating ? "#c0392b" : "#e63946",
              color: "#fff",
              boxShadow: "0 2px 8px rgba(230,57,70,0.25)",
              opacity: generating ? 0.7 : 1,
            }}
          >
            {generating ? "⏳ Generating..." : "📋 Generate Proposal"}
          </button>
          {genError && (
            <p className="text-[10px] mt-1 text-center" style={{ color: "#e63946" }}>
              {genError}
            </p>
          )}
        </div>
      </aside>
    );
  }

  return (
    <aside
      className="fixed left-0 top-0 bottom-0 z-50 w-[300px] max-w-[85vw] flex flex-col animate-fade-in-up"
      style={{
        background: "var(--sidebar-bg)",
        borderRight: "1px solid var(--sidebar-border)",
      }}
    >
      <div className="flex items-center justify-between px-4 py-3.5" style={{ borderBottom: "1px solid var(--sidebar-border)" }}>
        <div className="flex items-center gap-2.5">
          <span
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[10px] font-bold"
            style={{ background: "#e63946", color: "#fff" }}
          >
            C
          </span>
          <div>
            <h1 className="text-[14px] font-bold leading-tight" style={{ color: "var(--sidebar-text)" }}>Conflux</h1>
            <p className="text-[9px] font-medium tracking-[0.08em] uppercase" style={{ color: "var(--sidebar-text-muted)" }}>Urban Intelligence</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${health?.status === "ok" ? "animate-pulse-glow" : ""}`}
            style={{ background: health?.status === "ok" ? "var(--color-emerald)" : "var(--color-rose)" }}
          />
          <button
            onClick={onToggle}
            className="w-7 h-7 rounded-md flex items-center justify-center transition-colors hover:bg-[#eeece8]"
          >
            <svg className="w-3.5 h-3.5" style={{ color: "var(--sidebar-text-muted)" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex mx-4 mt-3 rounded-lg overflow-hidden" style={{ border: "1px solid var(--sidebar-card-border)" }}>
        <div className="flex-1 p-2 text-center" style={{ background: "var(--sidebar-card-bg)" }}>
          <p className="text-sm font-bold" style={{ color: "#e63946" }}>{displayProposals.length}</p>
          <p className="text-[8px] font-medium uppercase tracking-wider" style={{ color: "var(--sidebar-text-muted)" }}>Clusters</p>
        </div>
        <div className="flex-1 p-2 text-center" style={{ borderLeft: "1px solid var(--sidebar-card-border)", borderRight: "1px solid var(--sidebar-card-border)", background: "var(--sidebar-card-bg)" }}>
          <p className="text-sm font-bold" style={{ color: "var(--sidebar-text)" }}>{threads.length}</p>
          <p className="text-[8px] font-medium uppercase tracking-wider" style={{ color: "var(--sidebar-text-muted)" }}>Reports</p>
        </div>
        <div className="flex-1 p-2 text-center" style={{ background: "var(--sidebar-card-bg)" }}>
          <p className="text-sm font-bold" style={{ color: "var(--sidebar-text)" }}>{displayProposals.length}</p>
          <p className="text-[8px] font-medium uppercase tracking-wider" style={{ color: "var(--sidebar-text-muted)" }}>Proposals</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pt-3 pb-4 space-y-1">
        <p className="text-[9px] font-semibold uppercase tracking-wider mb-2 px-1" style={{ color: "var(--sidebar-text-muted)" }}>
          Issue Clusters
        </p>

        {loading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg p-3" style={{ background: "var(--sidebar-card-bg)", border: "1px solid var(--sidebar-card-border)" }}>
              <div className="skeleton h-3 w-28 mb-2" />
              <div className="skeleton h-2 w-full" />
            </div>
          ))
        ) : displayProposals.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-[12px]" style={{ color: "var(--sidebar-text-muted)" }}>No clusters yet</p>
            <p className="text-[10px] mt-1" style={{ color: "var(--sidebar-text-muted)" }}>Run the ingestion pipeline first</p>
          </div>
        ) : (
          displayProposals.map((c) => {
            const urg = URGENCY_CONFIG[c.urgency] ?? URGENCY_CONFIG.medium;
            return (
              <button
                key={c.cluster_id}
                onClick={() => onSelectCluster(c)}
                className="w-full text-left group rounded-lg p-3 transition-all duration-200"
                style={{ border: "1px solid transparent" }}
                onMouseOver={(e) => {
                  e.currentTarget.style.background = "var(--sidebar-hover)";
                  e.currentTarget.style.borderColor = "var(--sidebar-card-border)";
                }}
                onMouseOut={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.borderColor = "transparent";
                }}
              >
                <div className="flex items-start gap-2.5">
                  <span
                    className="flex-shrink-0 w-3 h-3 rounded-full mt-0.5"
                    style={{ background: urg.color }}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <h3 className="text-[12px] font-semibold truncate" style={{ color: "var(--sidebar-text)" }}>
                        {c.issue_type}
                      </h3>
                      <span
                        className="flex-shrink-0 text-[8px] font-bold uppercase px-1.5 py-0.5 rounded"
                        style={{ background: urg.bg, color: urg.color }}
                      >
                        {c.urgency}
                      </span>
                    </div>
                    <p className="text-[11px] line-clamp-2 leading-[1.5]" style={{ color: "var(--sidebar-text-muted)" }}>
                      {c.summary}
                    </p>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>

      <div className="px-4 py-2.5 text-center" style={{ borderTop: "1px solid var(--sidebar-border)" }}>
        <p className="text-[9px]" style={{ color: "var(--sidebar-text-muted)" }}>
          Conflux · Open source civic-tech · {ingestSource || "local"}
        </p>
      </div>
    </aside>
  );
}
