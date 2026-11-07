import maplibregl, { type GeoJSONSource, type Map } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import type { FeatureCollection } from "../types";

type Props = {
  geojson: FeatureCollection;
  colors: Record<string, string>;
  selected: string | null;
  track: [number, number][];
  position: [number, number] | null;
  onSelect: (fips: string) => void;
};

function painted(geojson: FeatureCollection, colors: Record<string, string>, selected: string | null): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: geojson.features.map((feature) => {
      const fips = String(feature.id ?? feature.properties.GEOID ?? "");
      return {
        ...feature,
        properties: {
          ...feature.properties,
          fips,
          name: String(feature.properties.NAME ?? fips),
          color: colors[fips] ?? "#1c3142",
          selected: fips === selected ? 1 : 0,
        },
      };
    }),
  };
}

export function MapView({ geojson, colors, selected, track, position, onSelect }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": "#071018" } }],
      },
      center: [-83.6, 27.9],
      zoom: 5.45,
      attributionControl: false,
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();
    map.on("load", () => {
      map.addSource("counties", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "counties-fill",
        type: "fill",
        source: "counties",
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.94 },
      });
      map.addLayer({
        id: "counties-line",
        type: "line",
        source: "counties",
        paint: {
          "line-color": ["case", ["==", ["get", "selected"], 1], "#f6d58a", "#081018"],
          "line-width": ["case", ["==", ["get", "selected"], 1], 2.4, 0.7],
        },
      });
      map.addSource("track", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "track-line",
        type: "line",
        source: "track",
        paint: { "line-color": "#f0b429", "line-width": 2.6, "line-opacity": 0.95 },
      });
      map.addSource("position", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "position-dot",
        type: "circle",
        source: "position",
        paint: {
          "circle-radius": 6,
          "circle-color": "#fff7e3",
          "circle-stroke-color": "#f0b429",
          "circle-stroke-width": 2,
        },
      });
      map.on("click", "counties-fill", (event) => {
        const fips = event.features?.[0]?.properties?.fips;
        if (fips) onSelectRef.current(String(fips));
      });
      map.on("mouseenter", "counties-fill", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "counties-fill", () => {
        map.getCanvas().style.cursor = "";
      });
      const bounds = new maplibregl.LngLatBounds();
      const walk = (coords: unknown): void => {
        if (!Array.isArray(coords)) return;
        if (typeof coords[0] === "number" && typeof coords[1] === "number") {
          bounds.extend([coords[0] as number, coords[1] as number]);
          return;
        }
        coords.forEach(walk);
      };
      geojson.features.forEach((feature) => walk(feature.geometry.coordinates));
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 28, duration: 0 });
      setReady(true);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [geojson]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("counties") as GeoJSONSource).setData(painted(geojson, colors, selected));
    (map.getSource("track") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: track },
        },
      ],
    });
    (map.getSource("position") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: position
        ? [
            {
              type: "Feature",
              properties: {},
              geometry: { type: "Point", coordinates: position },
            },
          ]
        : [],
    });
  }, [ready, geojson, colors, selected, track, position]);

  return <div ref={container} className="map" role="application" aria-label="Florida county map" />;
}
