interface SparklineProps {
  counts: number[];
  width?: number;
  height?: number;
  color?: string;
  className?: string;
}

/**
 * Minimal inline SVG sparkline for daily complaint counts.
 * Zero dependencies; baseline sits at the bottom, peaks touch the top.
 */
export default function Sparkline({
  counts,
  width = 64,
  height = 20,
  color = "#d92d20",
  className,
}: SparklineProps) {
  const data = counts.length > 0 ? counts : [0];
  const max = Math.max(...data, 1);
  const step = data.length > 1 ? width / (data.length - 1) : width;

  const points = data.map((value, index) => {
    const x = data.length > 1 ? index * step : width / 2;
    const y = height - (value / max) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const line = `M ${points.join(" L ")}`;
  const area = `${line} L ${width},${height} L 0,${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      aria-hidden="true"
    >
      <path d={area} fill={color} opacity={0.12} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
