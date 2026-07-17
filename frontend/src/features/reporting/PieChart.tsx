interface Slice {
  label: string
  value: number
  color: string
}

/** Minimal donut-less pie built from SVG arc paths. Values need not sum to 100. */
export function PieChart({ data, size = 190 }: { data: Slice[]; size?: number }) {
  const total = data.reduce((s, d) => s + d.value, 0)
  const r = size / 2
  const cx = r
  const cy = r
  let angle = -Math.PI / 2 // start at 12 o'clock

  const arc = (value: number) => {
    const slice = (value / total) * Math.PI * 2
    const x1 = cx + r * Math.cos(angle)
    const y1 = cy + r * Math.sin(angle)
    angle += slice
    const x2 = cx + r * Math.cos(angle)
    const y2 = cy + r * Math.sin(angle)
    const large = slice > Math.PI ? 1 : 0
    return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`
  }

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {data.map((d) => (
        <path key={d.label} d={arc(d.value)} fill={d.color} />
      ))}
    </svg>
  )
}