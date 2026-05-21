// Dual-axis power / energy chart for the station detail view (architektura 8.4).
// Left axis: instantaneous power (kW, blue). Right axis: cumulative energy
// (kWh, green) for the current or last session. Meter readings carry energy in
// Wh (integer); converted to kWh here for consistency with the sessions table.

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MeterReading } from "../types";
import { formatClock } from "../utils/formatTime";

interface PowerChartProps {
  readings: MeterReading[];
}

export default function PowerChart({ readings }: PowerChartProps) {
  if (readings.length === 0) {
    return (
      <div className="flex h-72 items-center justify-center rounded-lg border border-gray-200 text-sm text-gray-400">
        No meter readings to display
      </div>
    );
  }

  const data = readings.map((r) => ({
    time: formatClock(r.ts),
    power_kw: r.power_kw,
    // Wh -> kWh; energy_wh is an integer, so the division is exact to 3 dp.
    energy_kwh: r.energy_wh / 1000,
  }));

  return (
    <div className="h-72 w-full rounded-lg border border-gray-200 p-3">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey="time" tick={{ fontSize: 11 }} minTickGap={32} />
          <YAxis
            yAxisId="power"
            tick={{ fontSize: 11 }}
            label={{ value: "kW", angle: -90, position: "insideLeft", fontSize: 11 }}
          />
          <YAxis
            yAxisId="energy"
            orientation="right"
            tick={{ fontSize: 11 }}
            label={{ value: "kWh", angle: 90, position: "insideRight", fontSize: 11 }}
          />
          <Tooltip />
          <Legend />
          <Line
            yAxisId="power"
            type="monotone"
            dataKey="power_kw"
            name="Power (kW)"
            stroke="#3b82f6"
            dot={false}
            isAnimationActive={false}
          />
          <Line
            yAxisId="energy"
            type="monotone"
            dataKey="energy_kwh"
            name="Energy (kWh)"
            stroke="#22c55e"
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
