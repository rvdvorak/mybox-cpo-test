// Color-coded station status badge (architektura 8.2).

interface StatusBadgeProps {
  status: string;
}

// SCADA / EV-domain color convention. Unknown statuses fall back to gray.
const STATUS_COLORS: Record<string, string> = {
  Available: "bg-green-500",
  Preparing: "bg-yellow-500",
  Charging: "bg-blue-500",
  Finishing: "bg-yellow-500",
  Faulted: "bg-red-500",
  Offline: "bg-gray-400",
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const color = STATUS_COLORS[status] ?? "bg-gray-400";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium text-white ${color}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-white/80" />
      {status}
    </span>
  );
}
