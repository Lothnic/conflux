"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import LocalityPreviewMap from "@/components/LocalityPreviewMap";
import { getAgentRuns } from "@/lib/api";
import type { AgentRunTrace, AgentStepTrace, ClusterProposal, RedditThread } from "@/lib/types";
import {
  CATEGORY_BG,
  CATEGORY_COLORS,
  coordinateLabel,
  evidenceCount,
  issueCategory,
  issueTitle,
  locationConfidenceLabel,
  locationPrecisionLabel,
  reportedDate,
  severityLabel,
  severityScore,
} from "@/lib/issues";

interface ResearchStep {
  step: string;
  status: string;
  label?: string;
  output?: string;
  tool?: string;
  run_id?: string;
  doc_id?: string;
  download_url?: string;
}

interface PlanningAnalysisPanelProps {
  issue: ClusterProposal | null;
  threads: RedditThread[];
  onClose: () => void;
}

interface AnalysisState {
  issueId: string;
  steps: ResearchStep[];
  report: string | null;
  downloadUrl: string | null;
  running: boolean;
}

interface TraceState {
  issueId: string;
  runs: AgentRunTrace[];
  loading: boolean;
  error: string | null;
}

const STEP_ORDER = ["context", "geolocation", "poi", "policy", "reasoning", "recommendation", "document"];

const STEP_LABELS: Record<string, string> = {
  context: "Issue context",
  geolocation: "Geolocation",
  poi: "Nearby context",
  policy: "Policy analysis",
  reasoning: "Agent reasoning",
  recommendation: "Action plan",
  document: "Report synthesis",
};

function bullets(items: string[] | undefined, empty: string) {
  if (!items || items.length === 0) {
    return <p className="text-xs leading-5 text-slate-500">{empty}</p>;
  }
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2 text-xs leading-5 text-slate-700">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#d92d20]" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function sourceLabel(source: { subreddit: string }) {
  const provider = source.subreddit || "public report";
  if (provider.startsWith("news:")) return provider.slice(5);
  if (provider.startsWith("gov:")) return provider.slice(4);
  return `r/${provider}`;
}

function sourceHref(source: { id: string; subreddit: string; url?: string }) {
  if (source.url) return source.url;
  if (source.subreddit?.startsWith("news:") || source.subreddit?.startsWith("gov:")) return "";
  return `https://reddit.com/r/${source.subreddit || "delhi"}/comments/${source.id}`;
}

function renderMarkdownLinks(text: string) {
  const parts = text.split(/(\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g);
  return parts.map((part, index) => {
    const match = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (!match) return part;
    return (
      <a
        key={index}
        href={match[2]}
        target="_blank"
        rel="noopener noreferrer"
        className="font-semibold text-[#175cd3] underline decoration-slate-300 underline-offset-2 hover:text-[#0b4a9f]"
      >
        {match[1]}
      </a>
    );
  });
}

function shortRunId(runId: string): string {
  return runId.length > 10 ? `${runId.slice(0, 10)}...` : runId;
}

function formatTraceTime(value: string | null): string {
  if (!value) return "Pending";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recorded";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function summarizeTracePayload(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload || {});
  if (entries.length === 0) return "No payload recorded";

  const parts = entries.slice(0, 3).map(([key, value]) => {
    if (Array.isArray(value)) return `${key}: ${value.length} item${value.length === 1 ? "" : "s"}`;
    if (value && typeof value === "object") return `${key}: object`;
    const text = String(value ?? "");
    return `${key}: ${text.length > 64 ? `${text.slice(0, 64)}...` : text}`;
  });
  return parts.join(" · ");
}

function stepTraceLabel(step: AgentStepTrace): string {
  return STEP_LABELS[step.step_name] || step.step_name.replaceAll("_", " ");
}

export default function PlanningAnalysisPanel({ issue, threads, onClose }: PlanningAnalysisPanelProps) {
  const [analysis, setAnalysis] = useState<AnalysisState>({
    issueId: "",
    steps: [],
    report: null,
    downloadUrl: null,
    running: false,
  });
  const [traceState, setTraceState] = useState<TraceState>({
    issueId: "",
    runs: [],
    loading: false,
    error: null,
  });
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    eventSourceRef.current?.close();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [issue?.cluster_id]);

  useEffect(() => {
    if (!issue?.cluster_id) {
      return;
    }

    let cancelled = false;
    getAgentRuns(issue.cluster_id)
      .then((runs) => {
        if (!cancelled) {
          setTraceState({ issueId: issue.cluster_id, runs, loading: false, error: null });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setTraceState({
            issueId: issue.cluster_id,
            runs: [],
            loading: false,
            error: error instanceof Error ? error.message : "Could not load agent trace",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [issue?.cluster_id]);

  const linkedThreads = useMemo(() => {
    if (!issue) return [];
    return threads.filter((thread) => thread.cluster_id === issue.cluster_id).slice(0, 5);
  }, [issue, threads]);

  if (!issue) {
    return (
      <aside className="fixed right-4 top-[72px] bottom-4 z-40 hidden w-[420px] flex-col rounded-md border border-white/15 bg-white/95 shadow-xl backdrop-blur xl:flex">
        <div className="flex flex-1 items-center justify-center px-8 text-center">
          <div>
            <p className="text-sm font-bold text-slate-900">Select an issue marker</p>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              Click a red marker or an item in the issue queue to open AI planning analysis.
            </p>
          </div>
        </div>
      </aside>
    );
  }

  const category = issueCategory(issue.issue_type);
  const score = severityScore(issue);
  const isCurrentAnalysis = analysis.issueId === issue.cluster_id;
  const steps = isCurrentAnalysis ? analysis.steps : [];
  const report = isCurrentAnalysis ? analysis.report : null;
  const downloadUrl = isCurrentAnalysis ? analysis.downloadUrl : null;
  const running = isCurrentAnalysis && analysis.running;
  const sortedSteps = [...steps].sort((a, b) => STEP_ORDER.indexOf(a.step) - STEP_ORDER.indexOf(b.step));
  const currentStep = sortedSteps.find((step) => step.status === "running");
  const complete = Boolean(report);
  const traceRuns = traceState.issueId === issue.cluster_id ? traceState.runs : [];
  const latestTrace = traceRuns[0];
  const visibleTraceSteps = latestTrace?.steps?.length ? latestTrace.steps : [];
  const citationSources = issue.sources?.length
    ? issue.sources.slice(0, 4).map((source) => ({
        id: source.id,
        label: sourceLabel(source),
        title: source.title,
        url: sourceHref(source),
      }))
    : linkedThreads.slice(0, 4).map((thread) => ({
        id: thread.id,
        label: "Citizen report",
        title: thread.title,
        url: thread.url,
      }));

  function startAnalysis() {
    if (!issue || running) return;
    setAnalysis({
      issueId: issue.cluster_id,
      steps: [],
      report: null,
      downloadUrl: null,
      running: true,
    });

    const es = new EventSource(`/api/research/${issue.cluster_id}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const step: ResearchStep = JSON.parse(event.data);
      if (step.step === "done") {
        setAnalysis((prev) => (prev.issueId === issue.cluster_id ? { ...prev, running: false } : prev));
        es.close();
        getAgentRuns(issue.cluster_id)
          .then((runs) => {
            setTraceState({ issueId: issue.cluster_id, runs, loading: false, error: null });
          })
          .catch((error: unknown) => {
            setTraceState({
              issueId: issue.cluster_id,
              runs: [],
              loading: false,
              error: error instanceof Error ? error.message : "Could not refresh agent trace",
            });
          });
        return;
      }
      setAnalysis((prev) => {
        if (prev.issueId !== issue.cluster_id) return prev;
        const steps = [...prev.steps];
        const existing = steps.findIndex((item) => item.step === step.step);
        if (existing >= 0) {
          steps[existing] = step;
        } else {
          steps.push(step);
        }
        return {
          ...prev,
          steps,
          report: step.step === "document" && step.status === "done" ? step.output || "" : prev.report,
          downloadUrl: step.step === "document" && step.status === "done" ? step.download_url || null : prev.downloadUrl,
        };
      });
    };

    es.onerror = () => {
      setAnalysis((prev) => (prev.issueId === issue.cluster_id ? { ...prev, running: false } : prev));
      es.close();
    };
  }

  return (
    <aside className="fixed right-4 top-[72px] bottom-4 z-40 flex w-[456px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-md border border-slate-200 bg-white shadow-xl">
      <div className="border-b border-slate-200 px-5 py-4">
        <LocalityPreviewMap lat={issue.location.lat} lon={issue.location.lon} title={issueTitle(issue)} />

        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2">
              <span
                className="rounded px-2 py-1 text-[10px] font-bold uppercase"
                style={{ color: CATEGORY_COLORS[category], background: CATEGORY_BG[category] }}
              >
                {category}
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {reportedDate(issue, threads)}
              </span>
            </div>
            <h2 className="truncate text-base font-bold text-slate-950">{issueTitle(issue)}</h2>
            <p className="mt-1 text-xs text-slate-500">Estimated location: {coordinateLabel(issue)}</p>
            <p className="mt-1 text-[10px] font-medium text-slate-400">
              {locationConfidenceLabel(issue.location.confidence)} · {locationPrecisionLabel(issue.location.precision_meters)}
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            title="Close analysis panel"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="mt-4 grid grid-cols-3 overflow-hidden rounded-md border border-slate-200">
          <div className="bg-slate-50 px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Severity</p>
            <p className="mt-1 text-lg font-bold text-[#d92d20]">{score}</p>
            <p className="text-[10px] text-slate-500">{severityLabel(score)}</p>
          </div>
          <div className="border-x border-slate-200 bg-slate-50 px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Evidence</p>
            <p className="mt-1 text-lg font-bold text-slate-950">{evidenceCount(issue, threads)}</p>
            <p className="text-[10px] text-slate-500">sources</p>
          </div>
          <div className="bg-slate-50 px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Cost</p>
            <p className="mt-1 truncate text-sm font-bold text-slate-950">{issue.estimated_budget || "TBD"}</p>
            <p className="text-[10px] text-slate-500">estimate</p>
          </div>
        </div>

        {citationSources.length > 0 && (
          <div className="mt-3 rounded-md border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Citations</p>
              <p className="text-[10px] font-medium text-slate-400">{citationSources.length} linked</p>
            </div>
            <div className="divide-y divide-slate-100">
              {citationSources.map((source) =>
                source.url ? (
                  <a
                    key={source.id}
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block px-3 py-2 hover:bg-slate-50"
                  >
                    <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{source.label}</p>
                    <p className="mt-0.5 line-clamp-1 text-[11px] font-semibold text-[#175cd3]">{source.title}</p>
                  </a>
                ) : (
                  <div key={source.id} className="px-3 py-2">
                    <p className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{source.label}</p>
                    <p className="mt-0.5 line-clamp-1 text-[11px] font-semibold text-slate-700">{source.title}</p>
                  </div>
                )
              )}
            </div>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <section className="mb-5">
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Problem Summary</h3>
          <p className="text-sm leading-6 text-slate-800">{issue.summary}</p>
        </section>

        <section className="mb-5 rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">AI Planning Workflow</h3>
              <p className="mt-1 text-xs text-slate-500">
                {running ? currentStep?.label || currentStep?.step || "Analysis running" : complete ? "Analysis complete" : "Ready to investigate"}
              </p>
            </div>
            <button
              onClick={startAnalysis}
              disabled={running}
              className="rounded-md bg-[#175cd3] px-3 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {running ? "Running" : complete ? "Re-run" : "Run Analysis"}
            </button>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {STEP_ORDER.map((stepKey, index) => {
              const step = sortedSteps.find((item) => item.step === stepKey);
              const done = step?.status === "done";
              const active = step?.status === "running";
              return (
                <div key={stepKey} className="rounded border border-slate-200 bg-white p-2">
                  <div
                    className="mb-2 flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold"
                    style={{
                      background: done ? "#dcfae6" : active ? "#eff8ff" : "#f1f5f9",
                      color: done ? "#067647" : active ? "#175cd3" : "#64748b",
                    }}
                  >
                    {done ? "✓" : index + 1}
                  </div>
                  <p className="text-[10px] font-semibold leading-4 text-slate-700">{STEP_LABELS[stepKey]}</p>
                  {step?.tool && (
                    <p className="mt-1 truncate text-[9px] font-medium text-slate-400">{step.tool}</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section className="mb-5 rounded-md border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2.5">
            <div>
              <h3 className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Agent Trace</h3>
              <p className="mt-1 text-[10px] font-medium text-slate-400">
                {latestTrace
                  ? `Run ${shortRunId(latestTrace.run_id)} · ${latestTrace.status}`
                  : traceState.loading
                    ? "Loading persisted tool calls"
                    : "No persisted run yet"}
              </p>
            </div>
            <div className="rounded bg-slate-50 px-2 py-1 text-[10px] font-bold uppercase text-slate-500">
              {visibleTraceSteps.length || sortedSteps.length} steps
            </div>
          </div>

          {traceState.error && (
            <div className="border-b border-slate-100 px-3 py-2 text-xs text-[#b42318]">{traceState.error}</div>
          )}

          {visibleTraceSteps.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {visibleTraceSteps.map((step, index) => (
                <details key={`${latestTrace?.run_id}-${step.step_name}-${index}`} className="group px-3 py-2.5" open={index < 2}>
                  <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-800">{stepTraceLabel(step)}</p>
                      <p className="mt-1 truncate text-[10px] font-medium text-slate-400">
                        {step.tool_name || "agent"} · {formatTraceTime(step.created_at)}
                      </p>
                    </div>
                    <span
                      className="shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase"
                      style={{
                        color: step.status === "done" ? "#067647" : step.status === "error" ? "#b42318" : "#175cd3",
                        background: step.status === "done" ? "#dcfae6" : step.status === "error" ? "#fee4e2" : "#eff8ff",
                      }}
                    >
                      {step.status}
                    </span>
                  </summary>
                  <div className="mt-2 rounded border border-slate-100 bg-slate-50 p-2">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Input</p>
                    <p className="mt-1 text-[11px] leading-5 text-slate-600">{summarizeTracePayload(step.input)}</p>
                    <p className="mt-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">Output</p>
                    <p className="mt-1 text-[11px] leading-5 text-slate-600">{summarizeTracePayload(step.output)}</p>
                  </div>
                </details>
              ))}
            </div>
          ) : sortedSteps.length > 0 ? (
            <div className="divide-y divide-slate-100">
              {sortedSteps.map((step, index) => (
                <div key={`${step.step}-${index}`} className="px-3 py-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-800">{step.label || STEP_LABELS[step.step] || step.step}</p>
                      <p className="mt-1 truncate text-[10px] font-medium text-slate-400">{step.tool || "live agent stream"}</p>
                    </div>
                    <span className="shrink-0 rounded bg-[#eff8ff] px-1.5 py-0.5 text-[9px] font-bold uppercase text-[#175cd3]">
                      {step.status}
                    </span>
                  </div>
                  {step.output && <p className="mt-2 line-clamp-3 text-[11px] leading-5 text-slate-600">{step.output}</p>}
                </div>
              ))}
            </div>
          ) : (
            <div className="px-3 py-5 text-center">
              <p className="text-xs font-semibold text-slate-600">No agent execution recorded for this issue.</p>
              <p className="mt-1 text-[11px] leading-5 text-slate-400">Run analysis to persist context, policy, reasoning, and recommendation tool traces.</p>
            </div>
          )}
        </section>

        <section className="mb-5">
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Context Analysis</h3>
          <p className="text-xs leading-5 text-slate-600">
            The issue is represented by {issue.size ?? 1} linked civic report{(issue.size ?? 1) === 1 ? "" : "s"} near{" "}
            an estimated geocoded location at {coordinateLabel(issue)} with {locationConfidenceLabel(issue.location.confidence).toLowerCase()}. Nearby infrastructure, public facilities, and historical complaint evidence should be checked before final authorization.
          </p>
        </section>

        <section className="mb-5">
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Government Policy Assessment</h3>
          {bullets(issue.responsible_agencies, "No responsible agency mapping is available yet.")}
        </section>

        <section className="mb-5">
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Recommended Actions</h3>
          {bullets(issue.recommendations, "No recommendation has been generated for this issue yet.")}
        </section>

        <section className="mb-5">
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Impact Forecast</h3>
          <div className="grid grid-cols-2 gap-2">
            {[
              ["Safety improvement", score >= 80 ? "High" : "Medium"],
              ["Accessibility gains", issue.issue_type.includes("Road") ? "High" : "Medium"],
              ["Environmental impact", issueCategory(issue.issue_type) === "Environment" ? "High" : "Low"],
              ["Traffic reduction", issue.issue_type.includes("Traffic") ? "Medium" : "Low"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md border border-slate-200 bg-white p-3">
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</p>
                <p className="mt-1 text-sm font-bold text-slate-900">{value}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mb-5">
          <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Explainability</h3>
          <div className="rounded-md border border-slate-200 bg-white p-3">
            <p className="text-xs leading-5 text-slate-700">
              Based on citizen reports, estimated geocoding, severity, linked evidence, agency ownership, and generated planning recommendations, this issue is prioritized as {severityLabel(score).toLowerCase()}.
            </p>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-[#067647]" style={{ width: `${Math.min(score, 92)}%` }} />
            </div>
            <p className="mt-1 text-[10px] font-medium text-slate-500">Confidence score: {Math.min(score, 92)}%</p>
          </div>
        </section>

        {Boolean((issue.sources?.length ?? 0) || linkedThreads.length) && (
          <section className="mb-5">
            <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Evidence Used</h3>
            <div className="space-y-2">
              {issue.sources?.slice(0, 5).map((source, index) => (
                <a
                  key={`${source.id}-${index}`}
                  href={sourceHref(source)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block rounded-md border border-slate-200 bg-white p-3 hover:bg-slate-50"
                >
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{sourceLabel(source)}</p>
                  <p className="mt-1 line-clamp-2 text-xs font-medium leading-5 text-slate-700">{source.title}</p>
                </a>
              ))}
              {(!issue.sources || issue.sources.length === 0) &&
                linkedThreads.map((thread) => (
                  <a
                    key={thread.id}
                    href={thread.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block rounded-md border border-slate-200 bg-white p-3 hover:bg-slate-50"
                  >
                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Citizen report</p>
                    <p className="mt-1 line-clamp-2 text-xs font-medium leading-5 text-slate-700">{thread.title}</p>
                  </a>
                ))}
            </div>
          </section>
        )}

        {report && (
          <section className="mb-2">
            <h3 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Generated Report</h3>
            <div className="max-h-72 overflow-y-auto rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="whitespace-pre-wrap text-xs leading-5 text-slate-700">
                {renderMarkdownLinks(report)}
              </div>
            </div>
          </section>
        )}
      </div>

      <div className="flex gap-2 border-t border-slate-200 bg-white px-5 py-3">
        <a
          href={downloadUrl || `/api/research/${issue.cluster_id}/download/0`}
          download={`conflux-analysis-${issue.cluster_id}.md`}
          className={`flex-1 rounded-md px-3 py-2 text-center text-xs font-bold ${
            complete ? "bg-slate-900 text-white" : "pointer-events-none bg-slate-100 text-slate-400"
          }`}
        >
          Download Report
        </a>
        <button className="flex-1 rounded-md border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50">
          Assign Agency
        </button>
      </div>
    </aside>
  );
}
