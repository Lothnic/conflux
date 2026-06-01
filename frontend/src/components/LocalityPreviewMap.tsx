"use client";

import { useEffect, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

interface LocalityPreviewMapProps {
  lat: number;
  lon: number;
  title: string;
}

export default function LocalityPreviewMap({ lat, lon, title }: LocalityPreviewMapProps) {
  const mapNodeRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);

  useEffect(() => {
    const node = mapNodeRef.current;
    if (!node) return;

    const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
    if (!token) return;

    mapboxgl.accessToken = token;

    mapRef.current?.remove();

    const map = new mapboxgl.Map({
      container: node,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [lon, lat],
      zoom: 16.4,
      pitch: 67,
      bearing: -28,
      interactive: false,
      attributionControl: false,
      logoPosition: "bottom-left",
      antialias: true,
    });

    mapRef.current = map;
    const marker = new mapboxgl.Marker({ color: "#d92d20", scale: 0.7 })
      .setLngLat([lon, lat])
      .addTo(map);

    let frame = 0;
    let animationFrame = 0;

    map.on("load", () => {
      const layers = map.getStyle().layers || [];
      const labelLayer = layers.find(
        (layer) => layer.type === "symbol" && layer.layout && "text-field" in layer.layout
      );

      if (!map.getSource("mapbox-dem")) {
        map.addSource("mapbox-dem", {
          type: "raster-dem",
          url: "mapbox://mapbox.mapbox-terrain-dem-v1",
          tileSize: 512,
          maxzoom: 14,
        });
      }
      map.setTerrain({ source: "mapbox-dem", exaggeration: 1.15 });

      if (!map.getLayer("3d-buildings")) {
        map.addLayer(
          {
            id: "3d-buildings",
            source: "composite",
            "source-layer": "building",
            filter: ["==", "extrude", "true"],
            type: "fill-extrusion",
            minzoom: 15,
            paint: {
              "fill-extrusion-color": "#d8dee8",
              "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 15, 0, 16, ["get", "height"]],
              "fill-extrusion-base": ["interpolate", ["linear"], ["zoom"], 15, 0, 16, ["get", "min_height"]],
              "fill-extrusion-opacity": 0.72,
            },
          },
          labelLayer?.id
        );
      }

      const animate = () => {
        frame += 0.14;
        map.setBearing(-28 + Math.sin(frame / 24) * 26);
        map.setPitch(64 + Math.sin(frame / 40) * 5);
        animationFrame = window.requestAnimationFrame(animate);
      };
      animationFrame = window.requestAnimationFrame(animate);
    });

    return () => {
      window.cancelAnimationFrame(animationFrame);
      marker.remove();
      map.remove();
      mapRef.current = null;
    };
  }, [lat, lon]);

  if (!process.env.NEXT_PUBLIC_MAPBOX_TOKEN) {
    return (
      <div className="locality-preview locality-preview--fallback">
        <div className="flex h-full items-center justify-center px-6 text-center">
          <div>
            <p className="text-xs font-bold text-white">Mapbox token required</p>
            <p className="mt-1 text-[11px] leading-5 text-white/65">
              Set NEXT_PUBLIC_MAPBOX_TOKEN to enable the 3D locality preview.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="locality-preview" aria-label={`Estimated locality preview for ${title}`}>
      <div ref={mapNodeRef} className="locality-preview__map" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/45 to-transparent px-3 py-2">
        <p className="truncate text-[10px] font-bold uppercase tracking-wider text-white/80">Estimated Locality</p>
        <p className="truncate text-xs font-semibold text-white">{title}</p>
      </div>
    </div>
  );
}
