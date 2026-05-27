"use client";

import { useState, useRef, useEffect } from "react";
import type { HealthCheck } from "@/lib/types";

const ISSUE_TYPES = [
  "Road & Traffic",
  "Sanitation",
  "Water & Drainage",
  "Public Lighting",
  "Public Space & Environment",
  "General Infrastructure",
];

interface HeaderProps {
  health: HealthCheck | null;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  mapLayer: "satellite" | "street";
  onMapLayerChange: (layer: "satellite" | "street") => void;
  filterIssueType: string | null;
  onFilterChange: (issueType: string | null) => void;
}

export default function Header({ health, sidebarCollapsed, onToggleSidebar, mapLayer, onMapLayerChange, filterIssueType, onFilterChange }: HeaderProps) {
  const isHealthy = health?.status === "ok";
  const [filterOpen, setFilterOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (filterRef.current && !filterRef.current.contains(e.target as Node)) {
        setFilterOpen(false);
      }
    }
    if (filterOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [filterOpen]);

  return (
    <header className="fixed top-0 left-0 right-0 z-40 pointer-events-none">
      <div className="flex items-center justify-between px-4 py-3 pointer-events-auto">
        <div className="flex items-center">
          {sidebarCollapsed && (
            <button
              onClick={onToggleSidebar}
              className="w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200"
              style={{
                background: "rgba(255,255,255,0.9)",
                backdropFilter: "blur(8px)",
                border: "1px solid rgba(0,0,0,0.08)",
                boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
              }}
              title="Expand sidebar"
            >
              <svg className="w-3.5 h-3.5" style={{ color: "#555" }} fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
              </svg>
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div ref={filterRef} className="relative">
            <button
              onClick={() => setFilterOpen(!filterOpen)}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all duration-200"
              style={{
                background: filterIssueType ? "rgba(230,57,70,0.12)" : "rgba(255,255,255,0.9)",
                backdropFilter: "blur(8px)",
                border: `1px solid ${filterIssueType ? "rgba(230,57,70,0.3)" : "rgba(0,0,0,0.08)"}`,
                color: filterIssueType ? "#e63946" : "#555",
                boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
              }}
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 01-.659 1.591l-5.432 5.432a2.25 2.25 0 00-.659 1.591v2.927a2.25 2.25 0 01-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 00-.659-1.591L3.659 7.409A2.25 2.25 0 013 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0112 3z" />
              </svg>
              {filterIssueType || "Filter"}
            </button>
            {filterOpen && (
              <div
                className="absolute top-full right-0 mt-2 w-48 rounded-lg overflow-hidden animate-fade-in-up"
                style={{
                  background: "rgba(255,255,255,0.95)",
                  backdropFilter: "blur(12px)",
                  border: "1px solid rgba(0,0,0,0.08)",
                  boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
                }}
              >
                <button
                  onClick={() => { onFilterChange(null); setFilterOpen(false); }}
                  className="w-full text-left px-3 py-2 text-[11px] font-medium transition-colors hover:bg-gray-100"
                  style={{ color: !filterIssueType ? "#e63946" : "#555" }}
                >
                  All Issues
                </button>
                {ISSUE_TYPES.map((type) => (
                  <button
                    key={type}
                    onClick={() => { onFilterChange(type); setFilterOpen(false); }}
                    className="w-full text-left px-3 py-2 text-[11px] font-medium transition-colors hover:bg-gray-100"
                    style={{ color: filterIssueType === type ? "#e63946" : "#555" }}
                  >
                    {type}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={() => onMapLayerChange(mapLayer === "satellite" ? "street" : "satellite")}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all duration-200"
            style={{
              background: "rgba(255,255,255,0.9)",
              backdropFilter: "blur(8px)",
              border: "1px solid rgba(0,0,0,0.08)",
              color: "#555",
              boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
            }}
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 6.75V15m6-6v8.25m.503 3.498l4.875-2.437c.381-.19.622-.58.622-1.006V4.82c0-.836-.88-1.38-1.628-1.006l-3.869 1.934c-.317.159-.69.159-1.006 0L9.503 3.252a1.125 1.125 0 00-1.006 0L3.622 5.689C3.24 5.88 3 6.27 3 6.695V19.18c0 .836.88 1.38 1.628 1.006l3.869-1.934c.317-.159.69-.159 1.006 0l4.994 2.497c.317.158.69.158 1.006 0z" />
            </svg>
            {mapLayer === "satellite" ? "Street" : "Satellite"}
          </button>

          <div
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5"
            style={{
              background: "rgba(255,255,255,0.9)",
              backdropFilter: "blur(8px)",
              border: "1px solid rgba(0,0,0,0.08)",
              boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
            }}
          >
            <span
              className={`w-2 h-2 rounded-full ${isHealthy ? "animate-pulse-glow" : ""}`}
              style={{ background: isHealthy ? "var(--color-emerald)" : "var(--color-rose)" }}
            />
            <span className="text-[10px] font-medium" style={{ color: "#777" }}>
              {isHealthy ? "Live" : "Offline"}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
