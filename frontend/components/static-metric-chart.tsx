type StaticMetricChartProps = {
  title: string;
  src: string;
  alt: string;
};

export function StaticMetricChart({ title, src, alt }: StaticMetricChartProps) {
  return (
    <figure className="border border-zinc-300 p-4">
      <figcaption className="text-sm font-semibold text-zinc-950">
        {title}
      </figcaption>
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className="mt-3 h-auto w-full"
      />
    </figure>
  );
}
