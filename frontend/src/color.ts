function mix(start: number, end: number, t: number): number {
  return Math.round(start + (end - start) * t);
}

function hex(channels: number[]): string {
  return `#${channels.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

/** Square-root choropleth so a few large counties do not flatten the rest of the state. */
export function choropleth(value: number, max: number): string {
  if (!(max > 0) || !(value > 0)) return "#1c3142";
  const t = Math.min(1, Math.sqrt(value / max));
  const low = [28, 58, 79];
  const mid = [242, 193, 78];
  const high = [214, 84, 28];
  const [from, to, local] = t < 0.55 ? [low, mid, t / 0.55] : [mid, high, (t - 0.55) / 0.45];
  return hex([mix(from[0], to[0], local), mix(from[1], to[1], local), mix(from[2], to[2], local)]);
}

export function formatNumber(value: number, digits = 0): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

export function landfallIndex(frames: Array<{ position: [number, number]; wind_kt: number | null }>): number {
  let best = 0;
  let bestWind = -1;
  frames.forEach((frame, index) => {
    const [lon, lat] = frame.position;
    const overFlorida = lat >= 24.4 && lat <= 31.2 && lon >= -87.8 && lon <= -79.7;
    const wind = frame.wind_kt ?? 0;
    if (overFlorida && wind >= bestWind) {
      bestWind = wind;
      best = index;
    }
  });
  return best;
}
