"use client";

import { useEffect, useRef, useCallback } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { ClusterProposal, RedditThread } from "@/lib/types";

const MARKER_COLOR = "#e63946";
const MARKER_SELECTED = "#ff1a2d";

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

interface MapSectionProps {
  proposals: ClusterProposal[];
  threads: RedditThread[];
  isLoading: boolean;
  selectedCluster: ClusterProposal | null;
  onSelectCluster: (cluster: ClusterProposal | null) => void;
  mapLayer: "satellite" | "street";
}

export default function MapSection({
  proposals,
  threads,
  isLoading,
  selectedCluster,
  onSelectCluster,
  mapLayer,
}: MapSectionProps) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const densityLayerRef = useRef<L.LayerGroup | null>(null);
  const markerMapRef = useRef<Map<string, L.CircleMarker>>(new Map());
  const onSelectClusterRef = useRef(onSelectCluster);
  const threadMarkersLayerRef = useRef<L.LayerGroup | null>(null);
  const proposalsMapRef = useRef<Map<string, ClusterProposal>>(new Map());
  const satelliteLayerRef = useRef<L.TileLayer | null>(null);
  const streetLayerRef = useRef<L.TileLayer | null>(null);
  const labelsLayerRef = useRef<L.TileLayer | null>(null);

  useEffect(() => {
    onSelectClusterRef.current = onSelectCluster;
  }, [onSelectCluster]);

  const mapRefCallback = useCallback((node: HTMLDivElement | null) => {
    mapContainerRef.current = node;
    if (!node || mapInstanceRef.current) return;

    const map = L.map(node, {
      center: [28.6139, 77.209],
      zoom: 11,
      zoomControl: false,
      attributionControl: false,
    });

    const satelliteTile = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        maxZoom: 19,
        attribution: "Tiles &copy; Esri",
      }
    ).addTo(map);
    satelliteLayerRef.current = satelliteTile;

    const streetTile = L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
      }
    );
    streetLayerRef.current = streetTile;

    const labelsTile = L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png",
      { maxZoom: 19 }
    ).addTo(map);
    labelsLayerRef.current = labelsTile;

    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.control.attribution({ position: "bottomright", prefix: false })
      .addAttribution(
        '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; Esri &copy; CARTO'
      )
      .addTo(map);

    const densityLayer = L.layerGroup().addTo(map);
    const clusterLayer = L.layerGroup().addTo(map);
    const threadLayer = L.layerGroup().addTo(map);
    densityLayerRef.current = densityLayer;
    markersLayerRef.current = clusterLayer;
    threadMarkersLayerRef.current = threadLayer;
    mapInstanceRef.current = map;

    map.on("click", () => {
      onSelectClusterRef.current(null);
    });

    setTimeout(() => map.invalidateSize(), 200);
  }, []);

  useEffect(() => {
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const satellite = satelliteLayerRef.current;
    const street = streetLayerRef.current;
    const map = mapInstanceRef.current;
    if (!map || !satellite || !street) return;

    if (mapLayer === "satellite") {
      map.removeLayer(street);
      map.addLayer(satellite);
    } else {
      map.removeLayer(satellite);
      map.addLayer(street);
    }
  }, [mapLayer]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    const clusterLayer = markersLayerRef.current;
    const densityLayer = densityLayerRef.current;
    const threadLayer = threadMarkersLayerRef.current;
    if (!map || !clusterLayer || !densityLayer || !threadLayer) return;

    clusterLayer.clearLayers();
    densityLayer.clearLayers();
    threadLayer.clearLayers();
    markerMapRef.current.clear();

    const propsMap = new Map<string, ClusterProposal>();
    proposals.forEach((p) => {
      if (p.cluster_id) propsMap.set(p.cluster_id, p);
    });
    proposalsMapRef.current = propsMap;

    const valid = proposals.filter(
      (p) => p.location && typeof p.location.lat === "number" && typeof p.location.lon === "number"
    );

    const bounds: [number, number][] = [];
    const isSelected = (c: ClusterProposal) => selectedCluster?.cluster_id === c.cluster_id;

    threads.forEach((t) => {
      if (t.lat == null || t.lng == null) return;
      const safeTitle = escapeHtml(t.title);
      const safeSubreddit = escapeHtml(t.subreddit);
      const dot = L.circleMarker([t.lat, t.lng], {
        radius: 4,
        color: "transparent",
        fillColor: t.cluster_id ? "#f04438" : "#94a3b8",
        fillOpacity: t.cluster_id ? 0.55 : 0.35,
        weight: 0,
      });
      dot.bindTooltip(
        `<div style=\"font-family:system-ui,sans-serif;font-size:10px;max-width:180px;color:#fff;background:rgba(15,23,42,0.94);padding:3px 8px;border-radius:5px;line-height:1.3;\">
          ${safeTitle}<br><span style="color:#cbd5e1;font-size:9px;">Citizen report - r/${safeSubreddit} - ${t.upvotes} upvotes</span>
        </div>`,
        { direction: "top", offset: [0, -8] }
      );
      dot.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        if (t.cluster_id && propsMap.has(t.cluster_id)) {
          onSelectCluster(propsMap.get(t.cluster_id)!);
        }
      });
      dot.addTo(threadLayer);
    });

    if (valid.length === 0) return;

    valid.forEach((cluster) => {
      const safeIssueType = escapeHtml(cluster.issue_type);
      const lat = cluster.location.lat;
      const lon = cluster.location.lon;
      bounds.push([lat, lon]);
      const selected = isSelected(cluster);

      const densityRadius = Math.min(220 + (cluster.size ?? 1) * 45, 680);
      L.circle([lat, lon], {
        radius: densityRadius,
        color: MARKER_COLOR,
        fillColor: MARKER_COLOR,
        fillOpacity: selected ? 0.16 : 0.08,
        opacity: selected ? 0.35 : 0.2,
        weight: 1,
        interactive: false,
      }).addTo(densityLayer);

      const marker = L.circleMarker([lat, lon], {
        radius: selected ? 14 : 10,
        color: selected ? "#fff" : MARKER_COLOR,
        fillColor: selected ? MARKER_SELECTED : MARKER_COLOR,
        fillOpacity: selected ? 0.9 : 0.8,
        weight: selected ? 3 : 2,
        className: selected ? "cluster-marker-selected" : "cluster-marker",
      });

      marker.bindTooltip(
        `<div style="font-family:system-ui,sans-serif;font-size:11px;font-weight:700;color:#fff;background:rgba(15,23,42,0.94);padding:4px 10px;border-radius:6px;white-space:nowrap;box-shadow:0 2px 8px rgba(0,0,0,0.3)">
          ${safeIssueType}<br><span style="color:#cbd5e1;font-size:9px;font-weight:500;">Estimated geocoded location</span>
        </div>`,
        { direction: "top", offset: [0, -10], className: "" }
      );

      marker.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        onSelectCluster(cluster);
      });

      marker.addTo(clusterLayer);
      markerMapRef.current.set(String(cluster.cluster_id), marker);
    });

    if (selectedCluster && markerMapRef.current.has(String(selectedCluster.cluster_id))) {
      const selMarker = markerMapRef.current.get(String(selectedCluster.cluster_id))!;
      const latlng = selMarker.getLatLng();
      map.flyTo(latlng, Math.max(map.getZoom(), 13), { duration: 0.8 });
    } else if (bounds.length > 0) {
      map.fitBounds(bounds, { padding: [64, 64], maxZoom: 13 });
    }
  }, [proposals, threads, selectedCluster, onSelectCluster]);

  return (
    <>
      <div
        ref={mapRefCallback}
        className="absolute inset-0 w-full h-full"
        style={{ background: "#1a1a1a", zIndex: 0 }}
      />
      {isLoading && (
        <div
          className="absolute inset-0 z-[1] flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.4)", backdropFilter: "blur(4px)" }}
        >
          <div className="flex flex-col items-center gap-3 animate-fade-in">
            <div
              className="w-8 h-8 rounded-full animate-spin"
              style={{ border: "2px solid rgba(230,57,70,0.2)", borderTopColor: "#e63946" }}
            />
            <p className="text-[11px] font-medium tracking-wide" style={{ color: "#ccc" }}>
              Loading map…
            </p>
          </div>
        </div>
      )}
    </>
  );
}
