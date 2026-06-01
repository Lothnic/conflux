"use client";

import type { ClusterProposal, HealthCheck, RedditThread } from "@/lib/types";
import {
  CATEGORY_BG,
  CATEGORY_COLORS,
  ISSUE_CATEGORIES,
  evidenceCount,
  issueCategory,
  issueTitle,
  locationConfidenceLabel,
  reportedDate,
  severityLabel,
  severityScore,
} from "@/lib/issues";

interface IssueBrowserProps {
  issues: ClusterProposal[];
  threads: RedditThread[];
  selectedIssue: ClusterProposal | null;
  health: HealthCheck | null;
  ingestSource: string;
  loading: boolean;
  collapsed: boolean;
  filterIssueType: string | null;
  onFilterChange: (issueType: string | null) => void;
  onSelectIssue: (issue: ClusterProposal | null) => void;
  onToggle: () => void;
}

function issueTypeOptions(issues: ClusterProposal[]): string[] {
  return Array.from(new Set(issues.map((issue) => issue.issue_type))).sort();
}

export default function IssueBrowser({
  issues,
  threads,
  selectedIssue,
  health,
  ingestSource,
  loading,
  collapsed,
  filterIssueType,
  onFilterChange,
  onSelectIssue,
  onToggle,
}: IssueBrowserProps) {
  const validIssues = issues.filter(
    (issue) => issue.location && typeof issue.location.lat === "number" && typeof issue.location.lon === "number"
  );
  const highSeverity = validIssues.filter((issue) => severityScore(issue) >= 80).length;
  const sources = threads.length;

  if (collapsed) {
    return (
      <aside className="fixed left-0 top-0 bottom-0 z-50 flex w-14 flex-col items-center border-r border-slate-200 bg-white">
        <button
          onClick={onToggle}
          className="mt-4 flex h-9 w-9 items-center justify-center rounded-md bg-[#d92d20] text-xs font-bold text-white"
          title="Expand issue browser"
        >
          C
        </button>
        <div className="mt-5 flex flex-1 flex-col gap-2">
          {validIssues.slice(0, 8).map((issue) => {
            const category = issueCategory(issue.issue_type);
            const selected = selectedIssue?.cluster_id === issue.cluster_id;
            return (
              <button
                key={issue.cluster_id}
                onClick={() => onSelectIssue(selected ? null : issue)}
                className="h-7 w-7 rounded-full border text-[10px] font-bold"
                style={{
                  color: CATEGORY_COLORS[category],
                  background: CATEGORY_BG[category],
                  borderColor: selected ? CATEGORY_COLORS[category] : "transparent",
                }}
                title={issueTitle(issue)}
              >
                {severityScore(issue)}
              </button>
            );
          })}
        </div>
        <span
          className="mb-4 h-2 w-2 rounded-full"
          style={{ background: health?.status === "ok" ? "#067647" : "#d92d20" }}
        />
      </aside>
    );
  }

  return (
    <aside className="fixed left-0 top-0 bottom-0 z-50 flex w-[336px] max-w-[88vw] flex-col border-r border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-4 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-[#d92d20] text-sm font-bold text-white">
              C
            </span>
            <div>
              <h1 className="text-sm font-bold text-slate-950">Conflux</h1>
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                Civic Issue Desk
              </p>
            </div>
          </div>
          <button
            onClick={onToggle}
            className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
            title="Collapse issue browser"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.7} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
            </svg>
          </button>
        </div>

        <div className="mt-4 grid grid-cols-3 overflow-hidden rounded-md border border-slate-200">
          <div className="bg-slate-50 px-2 py-2 text-center">
            <p className="text-base font-bold text-slate-950">{validIssues.length}</p>
            <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">Issues</p>
          </div>
          <div className="border-x border-slate-200 bg-slate-50 px-2 py-2 text-center">
            <p className="text-base font-bold text-[#d92d20]">{highSeverity}</p>
            <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">Critical</p>
          </div>
          <div className="bg-slate-50 px-2 py-2 text-center">
            <p className="text-base font-bold text-slate-950">{sources}</p>
            <p className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">Reports</p>
          </div>
        </div>
      </div>

      <div className="border-b border-slate-200 px-4 py-3">
        <label className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
          Category
        </label>
        <select
          value={filterIssueType ?? ""}
          onChange={(event) => onFilterChange(event.target.value || null)}
          className="h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-xs font-medium text-slate-800 outline-none focus:border-slate-400"
        >
          <option value="">All civic issues</option>
          {issueTypeOptions(validIssues).map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
          {validIssues.length === 0 &&
            ISSUE_CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="mb-2 flex items-center justify-between px-1">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Issue Queue</p>
          <p className="text-[10px] font-medium text-slate-400">{filterIssueType || "All categories"}</p>
        </div>

        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="rounded-md border border-slate-200 bg-white p-3">
                <div className="skeleton mb-3 h-3 w-32" />
                <div className="skeleton h-2 w-full" />
              </div>
            ))}
          </div>
        ) : validIssues.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-300 px-4 py-8 text-center">
            <p className="text-sm font-semibold text-slate-700">No mapped issues yet</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">Run ingestion to populate the civic issue desk.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {validIssues.map((issue) => {
              const category = issueCategory(issue.issue_type);
              const score = severityScore(issue);
              const selected = selectedIssue?.cluster_id === issue.cluster_id;
              return (
                <button
                  key={issue.cluster_id}
                  onClick={() => onSelectIssue(issue)}
                  className="w-full rounded-md border bg-white p-3 text-left transition hover:border-slate-300 hover:bg-slate-50"
                  style={{
                    borderColor: selected ? CATEGORY_COLORS[category] : "#e2e8f0",
                    boxShadow: selected ? "inset 3px 0 0 #d92d20" : "none",
                  }}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[11px] font-bold"
                      style={{ color: CATEGORY_COLORS[category], background: CATEGORY_BG[category] }}
                    >
                      {score}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h3 className="truncate text-[13px] font-bold text-slate-950">{issueTitle(issue)}</h3>
                        <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold uppercase text-slate-600">
                          {severityLabel(score)}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-slate-600">{issue.summary}</p>
                      <div className="mt-2 flex items-center justify-between text-[10px] font-medium text-slate-400">
                        <span>{locationConfidenceLabel(issue.location.confidence)}</span>
                        <span>{evidenceCount(issue, threads)} evidence</span>
                      </div>
                      <p className="mt-1 text-[10px] text-slate-400">Reported {reportedDate(issue, threads)}</p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="border-t border-slate-200 px-4 py-2.5">
        <div className="flex items-center justify-between text-[10px] text-slate-500">
          <span>{health?.status === "ok" ? "Backend live" : "Backend offline"}</span>
          <span>{ingestSource || "local source"}</span>
        </div>
      </div>
    </aside>
  );
}
