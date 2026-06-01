"use client";

import { useState, useEffect, useRef } from "react";

interface ResearchStep {
  step: string;
  status: string;
  label?: string;
  output?: string;
  doc_id?: string;
  download_url?: string;
}

interface ResearchSidebarProps {
  clusterId: string;
  issueType: string;
  onClose: () => void;
}

const STEP_ICONS: Record<string, string> = { satellite: "🛰️", poi: "📍", policy: "📜", document: "📄" };
const STEP_LABELS: Record<string, string> = { satellite: "Satellite Context", poi: "Points of Interest", policy: "Policy Analysis", document: "Comprehensive Report" };

const GOVT_PORTALS: Record<string, { name: string; url: string; desc: string }[]> = {
  "Road & Traffic": [
    { name: "PWD Delhi Grievance", url: "https://pwd.delhi.gov.in/contact-us", desc: "File road repair, pothole, and traffic infrastructure complaints" },
    { name: "Delhi Traffic Police", url: "https://traffic.delhipolice.gov.in/complaint", desc: "Report traffic signal issues, congestion, and violations" },
    { name: "MCD Citizen Portal", url: "https://mcdonline.nic.in/citizenportal/", desc: "Submit municipal road and streetlight complaints" },
    { name: "CPGRAMS", url: "https://pgportal.gov.in/", desc: "Centralised Public Grievance — escalates to all departments" },
    { name: "LG Delhi", url: "https://lg.delhi.gov.in/", desc: "Escalate unresolved matters to Lieutenant Governor" },
  ],
  "Sanitation": [
    { name: "MCD Swachhata Portal", url: "https://mcdonline.nic.in/citizenportal/", desc: "Report garbage, waste collection, and street cleaning issues" },
    { name: "Swachh Bharat Urban", url: "https://sbmurban.org/", desc: "File sanitation complaints under Swachh Bharat Mission" },
    { name: "CPGRAMS", url: "https://pgportal.gov.in/", desc: "Centralised Public Grievance — escalates to all departments" },
    { name: "LG Delhi", url: "https://lg.delhi.gov.in/", desc: "Escalate unresolved sanitation matters" },
  ],
  "Water & Drainage": [
    { name: "Delhi Jal Board", url: "https://delhijalboard.delhi.gov.in/complaint", desc: "Report water supply, sewer, drainage, and contamination issues" },
    { name: "CPGRAMS", url: "https://pgportal.gov.in/", desc: "Centralised Public Grievance — escalates to all departments" },
    { name: "NDMA Flood Portal", url: "https://ndma.gov.in/", desc: "Report waterlogging and flood-prone areas to NDMA" },
    { name: "LG Delhi", url: "https://lg.delhi.gov.in/", desc: "Escalate unresolved water/drainage matters" },
  ],
  "Public Lighting": [
    { name: "MCD Streetlight Portal", url: "https://mcdonline.nic.in/citizenportal/", desc: "Report non-functional streetlights and electrical issues" },
    { name: "BSES/TPDDL", url: "https://www.bsesdelhi.com/", desc: "Report power-related streetlight and electrical complaints" },
    { name: "CPGRAMS", url: "https://pgportal.gov.in/", desc: "Centralised Public Grievance — escalates to all departments" },
  ],
  "Public Space & Environment": [
    { name: "DPCC", url: "https://www.dpcc.delhigovt.nic.in/", desc: "Report pollution, noise, and environmental violations" },
    { name: "NDMC Parks", url: "https://www.ndmc.gov.in/", desc: "Report park maintenance and public space issues" },
    { name: "CPGRAMS", url: "https://pgportal.gov.in/", desc: "Centralised Public Grievance — escalates to all departments" },
    { name: "MyGov", url: "https://www.mygov.in/", desc: "Submit citizen feedback and ideas for urban improvement" },
  ],
  "General Infrastructure": [
    { name: "CPGRAMS", url: "https://pgportal.gov.in/", desc: "Centralised Public Grievance — all departments" },
    { name: "Delhi e-District", url: "https://edistrict.delhigovt.nic.in/", desc: "File grievances with Delhi government departments" },
    { name: "LG Delhi", url: "https://lg.delhi.gov.in/", desc: "Escalate unresolved matters to Lieutenant Governor" },
  ],
};

function getPortals(issueType: string) {
  return GOVT_PORTALS[issueType] || GOVT_PORTALS["General Infrastructure"];
}

// Convert inline **bold** within a line into React nodes (the Groq policy/POI
// output uses inline bold that the line-by-line renderer would otherwise show raw).
function renderInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} style={{ color: "#222" }}>{part.slice(2, -2)}</strong>
    ) : (
      part
    )
  );
}

function renderMarkdownToHTML(md: string): string {
  let html = md
    .replace(/^### (.+)$/gm, '<h3 class="r-h3">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="r-h2">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="r-h1">$1</h1>')
    .replace(/^---$/gm, '<hr class="r-hr"/>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^- (.+)$/gm, '<li class="r-li">$1</li>')
    .replace(/((?:<li class="r-li">.*<\/li>\n?)+)/g, '<ul class="r-ul">$1</ul>')
    .replace(/\n\n/g, '</p><p class="r-p">')
    .replace(/^(.+)$/gm, (line: string) => {
      if (line.startsWith('<h') || line.startsWith('<hr') || line.startsWith('<ul') || line.startsWith('<li') || line.startsWith('</ul')) return line;
      return `<p class="r-p">${line}</p>`;
    });
  html = html.replace(/\n/g, '');
  html = `<div class="research-report">${html}</div>`;
  return html;
}

export default function ResearchSidebar({ clusterId, issueType, onClose }: ResearchSidebarProps) {
  const [steps, setSteps] = useState<ResearchStep[]>([]);
  const [complete, setComplete] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [mode, setMode] = useState<"research" | "report">("research");
  const reportRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource(`/api/research/${clusterId}`);
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      const step: ResearchStep = JSON.parse(event.data);
      if (step.step === "done") { setComplete(true); setMode("report"); es.close(); return; }
      setSteps((prev) => {
        const existing = prev.findIndex((s) => s.step === step.step);
        if (existing >= 0) { const copy = [...prev]; copy[existing] = step; return copy; }
        return [...prev, step];
      });
      if (step.step === "document" && step.status === "done") {
        setPreviewDoc(step.output || null);
        setDownloadUrl(step.download_url || null);
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [clusterId]);

  const handleExportPDF = () => {
    const printWindow = window.open("", "_blank");
    if (!printWindow) return;
    const docContent = previewDoc || "";
    const html = renderMarkdownToHTML(docContent);
    printWindow.document.write(`
      <!DOCTYPE html><html><head><meta charset="utf-8"><title>Conflux Report — ${clusterId}</title>
      <style>
        @page { size: A4; margin: 20mm; }
        body { font-family: "Georgia", "Times New Roman", serif; font-size: 12pt; line-height: 1.7; color: #1a1a1a; max-width: 700px; margin: 0 auto; padding: 20px; }
        .r-h1 { font-size: 20pt; color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; margin-top: 0; }
        .r-h2 { font-size: 14pt; color: #333; margin-top: 24px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
        .r-h3 { font-size: 12pt; color: #555; margin-top: 16px; }
        .r-p { margin: 8px 0; }
        .r-ul { padding-left: 20px; margin: 8px 0; }
        .r-li { margin: 4px 0; }
        .r-hr { border: none; border-top: 1px solid #ddd; margin: 20px 0; }
        strong { color: #222; }
        .report-footer { margin-top: 30px; padding-top: 10px; border-top: 1px solid #ccc; font-size: 9pt; color: #888; }
      </style></head><body>${html}<div class="report-footer">Generated by Conflux — Civic Intelligence for Delhi NCR | ${new Date().toISOString().split("T")[0]}</div></body></html>
    `);
    printWindow.document.close();
    printWindow.focus();
    setTimeout(() => printWindow.print(), 500);
  };

  const currentStep = steps.find((s) => s.status === "running");
  const sortedSteps = [...steps].sort((a, b) => {
    const order = ["satellite", "poi", "policy", "document"];
    return order.indexOf(a.step) - order.indexOf(b.step);
  });
  const portals = getPortals(issueType);

  return (
    <aside
      className="fixed z-40 top-0 right-0 bottom-0 w-[480px] max-w-[90vw] flex flex-col animate-fade-in-up"
      style={{
        background: "#faf9f7",
        borderLeft: "1px solid rgba(0,0,0,0.1)",
        boxShadow: "-4px 0 24px rgba(0,0,0,0.06)",
      }}
    >
      <div className="flex items-center justify-between px-5 py-4 flex-shrink-0" style={{ borderBottom: "1px solid rgba(0,0,0,0.08)" }}>
        <div>
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-md flex items-center justify-center text-[10px] font-bold" style={{ background: "#1a73e8", color: "#fff" }}>R</span>
            <h2 className="text-[13px] font-bold" style={{ color: "#1a1a1a" }}>Research Engine</h2>
          </div>
          <p className="text-[10px] mt-0.5" style={{ color: "#888" }}>{issueType} — {clusterId}</p>
        </div>
        <div className="flex items-center gap-1">
          {complete && (
            <>
              <button onClick={() => setMode("research")} className="text-[10px] px-2 py-1 rounded-md transition-colors font-medium" style={{ background: mode === "research" ? "rgba(26,115,232,0.1)" : "transparent", color: mode === "research" ? "#1a73e8" : "#888" }}>Steps</button>
              <button onClick={() => setMode("report")} className="text-[10px] px-2 py-1 rounded-md transition-colors font-medium" style={{ background: mode === "report" ? "rgba(26,115,232,0.1)" : "transparent", color: mode === "report" ? "#1a73e8" : "#888" }}>Report</button>
            </>
          )}
          <button onClick={onClose} className="w-7 h-7 rounded-md flex items-center justify-center hover:bg-[#e8e6e2] transition-colors ml-1">
            <svg className="w-3.5 h-3.5" style={{ color: "#888" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {mode === "research" && (
          <div className="px-5 py-4 space-y-3">
            {!complete && (
              <div className="text-center py-12">
                <div className="w-10 h-10 rounded-full animate-spin mx-auto mb-4" style={{ border: "3px solid rgba(26,115,232,0.15)", borderTopColor: "#1a73e8" }} />
                <p className="text-[11px] font-medium" style={{ color: "#666" }}>
                  {currentStep ? currentStep.label : "Initializing research engine..."}
                </p>
              </div>
            )}

            {sortedSteps.map((s) => (
              <div key={s.step} className="rounded-lg overflow-hidden transition-all" style={{ border: "1px solid rgba(0,0,0,0.06)", background: "#fff" }}>
                <div className="flex items-center gap-2 px-4 py-2.5" style={{ borderBottom: s.output ? "1px solid rgba(0,0,0,0.04)" : "none" }}>
                  <span>{STEP_ICONS[s.step]}</span>
                  <span className="text-[11px] font-semibold flex-1" style={{ color: "#333" }}>{STEP_LABELS[s.step]}</span>
                  {s.status === "running" && <span className="w-2.5 h-2.5 rounded-full animate-pulse" style={{ background: "#1a73e8" }} />}
                  {s.status === "done" && <span className="text-[10px] font-medium" style={{ color: "#2d9a5c" }}>Done</span>}
                </div>
                {s.output && (
                  <div className="px-4 py-3 text-[12px] leading-relaxed" style={{ color: "#555", maxHeight: "200px", overflowY: "auto" }}>
                    {s.output.split("\n").map((line, i) => {
                      if (line.startsWith("### ")) return <h4 key={i} className="text-[12px] font-bold mt-3 mb-1" style={{ color: "#333" }}>{line.slice(4)}</h4>;
                      if (line.startsWith("## ")) return <h3 key={i} className="text-[13px] font-bold mt-3 mb-1" style={{ color: "#333" }}>{line.slice(3)}</h3>;
                      if (line.startsWith("# ")) return <h2 key={i} className="text-[14px] font-bold mt-3 mb-1" style={{ color: "#1a73e8" }}>{line.slice(2)}</h2>;
                      if (line.startsWith("- ") || line.startsWith("* ")) return <div key={i} className="flex gap-2 ml-2"><span className="text-[10px] mt-[5px]">●</span><span>{renderInline(line.slice(2))}</span></div>;
                      if (line.trim() === "") return <div key={i} className="h-2" />;
                      if (line.startsWith("---")) return <hr key={i} className="my-2" style={{ borderColor: "rgba(0,0,0,0.08)" }} />;
                      return <p key={i} className="my-1">{renderInline(line)}</p>;
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {mode === "report" && previewDoc && (
          <div ref={reportRef} className="px-6 py-5">
            <div id="report-content" className="text-[13px] leading-[1.75]" style={{ fontFamily: "'Georgia', 'Times New Roman', serif", color: "#2a2a2a" }}>
              {previewDoc.split("\n").map((line, i) => {
                if (line.startsWith("### ")) return <h4 key={i} className="text-[14px] font-bold mt-6 mb-2" style={{ color: "#444" }}>{line.slice(4)}</h4>;
                if (line.startsWith("## ")) return <h3 key={i} className="text-[16px] font-bold mt-8 mb-3 pb-1" style={{ color: "#333", borderBottom: "1px solid rgba(0,0,0,0.1)" }}>{line.slice(3)}</h3>;
                if (line.startsWith("# ")) return <h2 key={i} className="text-[20px] font-bold mt-6 mb-4 pb-2" style={{ color: "#1a73e8", borderBottom: "2px solid #1a73e8" }}>{line.slice(2)}</h2>;
                if (line.startsWith("- ") || line.startsWith("* ")) return <div key={i} className="flex gap-2.5 ml-3 my-1.5"><span className="text-[10px] mt-[6px] flex-shrink-0" style={{ color: "#1a73e8" }}>●</span><span>{renderInline(line.slice(2))}</span></div>;
                const numbered = line.match(/^(\d+)\.\s+(.*)$/);
                if (numbered) return <div key={i} className="flex gap-2.5 ml-3 my-1.5"><span className="text-[11px] font-bold mt-px flex-shrink-0" style={{ color: "#1a73e8" }}>{numbered[1]}.</span><span>{renderInline(numbered[2])}</span></div>;
                if (line.startsWith("---")) return <hr key={i} className="my-5" style={{ borderColor: "rgba(0,0,0,0.1)" }} />;
                if (line.startsWith("**") && line.endsWith("**")) return <p key={i} className="my-3 font-bold text-[13px]" style={{ color: "#333" }}>{line.slice(2, -2)}</p>;
                if (line.trim() === "") return <div key={i} className="h-2.5" />;
                return <p key={i} className="my-2 leading-relaxed">{renderInline(line)}</p>;
              })}
            </div>

            <div className="mt-8 pt-5" style={{ borderTop: "1px solid rgba(0,0,0,0.1)" }}>
              <h3 className="text-[13px] font-bold mb-3" style={{ color: "#333" }}>🏛️ Submit to Government Portals</h3>
              <p className="text-[11px] mb-3" style={{ color: "#777" }}>This report&apos;s findings can be submitted through these Delhi NCR grievance portals:</p>
              <div className="space-y-2">
                {portals.map((p, i) => (
                  <a key={i} href={p.url} target="_blank" rel="noopener noreferrer" className="block rounded-lg p-3 transition-all hover:shadow-sm" style={{ background: "#fff", border: "1px solid rgba(0,0,0,0.08)" }}>
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded flex items-center justify-center text-[10px] font-bold flex-shrink-0" style={{ background: "#e3f0ff", color: "#1a73e8" }}>{i + 1}</span>
                      <div>
                        <p className="text-[11px] font-semibold" style={{ color: "#1a73e8" }}>{p.name}</p>
                        <p className="text-[10px] mt-0.5" style={{ color: "#888" }}>{p.desc}</p>
                      </div>
                      <svg className="w-3 h-3 ml-auto flex-shrink-0" style={{ color: "#aaa" }} fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" /></svg>
                    </div>
                  </a>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="px-5 py-3.5 flex-shrink-0 flex gap-2" style={{ borderTop: "1px solid rgba(0,0,0,0.08)", background: "#faf9f7" }}>
        {complete && previewDoc && (
          <>
            <a
              href={downloadUrl || `/api/research/${clusterId}/download/0`}
              download={`conflux-report-${clusterId}.md`}
              className="flex-1 py-2.5 rounded-lg text-[11px] font-semibold text-center transition-all hover:opacity-90"
              style={{ background: "#2a2a2a", color: "#fff" }}
            >
              ⬇ Download .MD
            </a>
            <button
              onClick={handleExportPDF}
              className="flex-1 py-2.5 rounded-lg text-[11px] font-semibold text-center transition-all hover:opacity-90"
              style={{ background: "#1a73e8", color: "#fff" }}
            >
              🖨️ Export PDF
            </button>
          </>
        )}
        {!complete && (
          <div className="flex-1 text-center py-2">
            <p className="text-[10px]" style={{ color: "#aaa" }}>
              {currentStep ? `${currentStep.label}...` : "Research in progress..."}
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
