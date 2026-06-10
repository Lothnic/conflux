# Graph Report - conflux  (2026-06-10)

## Corpus Check
- 65 files · ~25,972 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 420 nodes · 692 edges · 35 communities (24 shown, 11 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 11 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `05e5b98d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Backend API & Complaint Processing|Backend API & Complaint Processing]]
- [[_COMMUNITY_Ingestion Worker & Proposal Generation|Ingestion Worker & Proposal Generation]]
- [[_COMMUNITY_Frontend UI Components|Frontend UI Components]]
- [[_COMMUNITY_Policy Research & Agent Pipeline|Policy Research & Agent Pipeline]]
- [[_COMMUNITY_Issue Display & Analysis Components|Issue Display & Analysis Components]]
- [[_COMMUNITY_Frontend Package Configuration|Frontend Package Configuration]]
- [[_COMMUNITY_Frontend TypeScript Config|Frontend TypeScript Config]]
- [[_COMMUNITY_Research Sidebar Component|Research Sidebar Component]]
- [[_COMMUNITY_Database Layer|Database Layer]]
- [[_COMMUNITY_Delhi Policy Documents & READMEs|Delhi Policy Documents & READMEs]]
- [[_COMMUNITY_App Layout|App Layout]]
- [[_COMMUNITY_Claude Settings|Claude Settings]]
- [[_COMMUNITY_ESLint Config|ESLint Config]]
- [[_COMMUNITY_Next.js Config|Next.js Config]]
- [[_COMMUNITY_PostCSS Config|PostCSS Config]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]

## God Nodes (most connected - your core abstractions)
1. `init_db_sync()` - 20 edges
2. `compilerOptions` - 16 edges
3. `run_research()` - 15 edges
4. `get_proposals()` - 13 edges
5. `generate_proposal_for_cluster_endpoint()` - 12 edges
6. `fetch_latest_clusters()` - 12 edges
7. `PlanningAnalysisPanel()` - 12 edges
8. `ClusterProposal` - 12 edges
9. `resolve_location()` - 12 edges
10. `main()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `_load_local_cluster_fallback()` --calls--> `Path`  [INFERRED]
  research.py → app/core/config.py
- `extract_keywords()` --calls--> `Counter`  [INFERRED]
  worker/clustering.py → policy_retriever.py
- `Conflux` --conceptually_related_to--> `Delhi Drainage and Water Infrastructure Notes`  [INFERRED]
  README.md → policy_docs/delhi_drainage_water.md
- `Conflux` --conceptually_related_to--> `Delhi Public Lighting and Safety Notes`  [INFERRED]
  README.md → policy_docs/delhi_lighting_safety.md
- `Conflux` --conceptually_related_to--> `Delhi Road and Traffic Safety Notes`  [INFERRED]
  README.md → policy_docs/delhi_road_safety.md

## Import Cycles
- None detected.

## Communities (35 total, 11 thin omitted)

### Community 0 - "Backend API & Complaint Processing"
Cohesion: 0.33
Nodes (9): Counter, _cosine(), _load_docs(), PolicyHit, Lightweight local policy retrieval for the planning agent.  This is intentionall, retrieve_policy(), _tf(), _tokens() (+1 more)

### Community 1 - "Ingestion Worker & Proposal Generation"
Cohesion: 0.08
Nodes (35): cluster_results Table, daily_ingest Table, Backward-compatible shim — delegates to app.core.database.  New code should impo, 1. System Architecture, 2. Reddit Ingestion Strategy, 3. Database Schema, 4. Data Flow, 5. Tech Stack Summary (+27 more)

### Community 2 - "Frontend UI Components"
Cohesion: 0.06
Nodes (45): MapLayer, MapSection, HeaderProps, IssueBrowser(), IssueBrowserProps, issueTypeOptions(), MapSectionProps, AnalysisState (+37 more)

### Community 3 - "Policy Research & Agent Pipeline"
Cohesion: 0.18
Nodes (27): Any, AgentState, assess_geolocation(), _call_llm(), _citation_url(), _event(), _fallback_agencies(), _finish_run() (+19 more)

### Community 4 - "Issue Display & Analysis Components"
Cohesion: 0.16
Nodes (6): Conflux Backend — Civic-tech AI Platform, BaseSettings, get_settings(), Application configuration using Pydantic Settings., Settings, Path

### Community 5 - "Frontend Package Configuration"
Cohesion: 0.08
Nodes (24): dependencies, leaflet, mapbox-gl, next, react, react-dom, devDependencies, eslint (+16 more)

### Community 6 - "Frontend TypeScript Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+11 more)

### Community 7 - "Research Sidebar Component"
Cohesion: 0.22
Nodes (7): getPortals(), GOVT_PORTALS, ResearchSidebar(), ResearchSidebarProps, ResearchStep, STEP_ICONS, STEP_LABELS

### Community 8 - "Database Layer"
Cohesion: 0.09
Nodes (42): database_available(), Conflux Backend — Civic-tech AI Platform Author: Lothnic  This module creates th, build_prompt(), call_groq(), fetch_stored_proposals(), generate_proposal_for_cluster(), Engine, LLM-powered proposal generation using Groq API. Replaces the heuristic keyword-m (+34 more)

### Community 9 - "Delhi Policy Documents & READMEs"
Cohesion: 0.12
Nodes (11): Delhi Drainage and Water Infrastructure Notes, Delhi Public Lighting and Safety Notes, Delhi Road and Traffic Safety Notes, Delhi Sanitation and Public Space Notes, Conflux, Deployment, FastAPI, Next.js (+3 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (31): BaseModel, ComplainList, init_db_sync(), Create tables if the database is available. Returns False otherwise., ClusterProposal, ComplainList, Complaint, ProposalResponse (+23 more)

### Community 17 - "Community 17"
Cohesion: 0.29
Nodes (6): Deployment, FastAPI Backend, FastAPI Backend on Render, Frontend on Vercel, Vercel Services Option, Worker

### Community 18 - "Community 18"
Cohesion: 0.33
Nodes (5): buildCommand, framework, headers, installCommand, $schema

### Community 19 - "Community 19"
Cohesion: 0.50
Nodes (3): Deploy on Vercel, Getting Started, Learn More

### Community 28 - "Community 28"
Cohesion: 0.11
Nodes (20): Engine, AsyncEngine, AsyncSession, Connection, create_async_engine_instance(), create_sync_engine(), create_tables(), _ensure_columns() (+12 more)

### Community 32 - "Community 32"
Cohesion: 0.33
Nodes (9): createBackendUrl(), GET(), HOP_BY_HOP_HEADERS, OPTIONS(), POST(), proxy(), proxyHeaders(), responseHeaders() (+1 more)

### Community 34 - "Community 34"
Cohesion: 0.22
Nodes (13): extract_location_candidate(), extract_location_candidate_locally(), geocode_text(), geocoder_importance_score(), precision_to_meters(), Geocoding and location resolution for civic complaints.  Uses an LLM to extract, Resolve a complaint to a geolocation with quality metadata., Backward-compatible wrapper for older callers/tests. (+5 more)

## Knowledge Gaps
- **98 isolated node(s):** `allow`, `$schema`, `plugin`, `@opencode-ai/plugin`, `Engine` (+93 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `init_db_sync()` connect `Community 16` to `Database Layer`, `Community 28`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `run_research()` connect `Policy Research & Agent Pipeline` to `Database Layer`, `Community 16`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `Path` connect `Issue Display & Analysis Components` to `Community 16`, `Policy Research & Agent Pipeline`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **What connects `allow`, `$schema`, `plugin` to the rest of the system?**
  _151 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Ingestion Worker & Proposal Generation` be split into smaller, more focused modules?**
  _Cohesion score 0.08170731707317073 - nodes in this community are weakly interconnected._
- **Should `Frontend UI Components` be split into smaller, more focused modules?**
  _Cohesion score 0.06453028972783142 - nodes in this community are weakly interconnected._
- **Should `Frontend Package Configuration` be split into smaller, more focused modules?**
  _Cohesion score 0.08 - nodes in this community are weakly interconnected._