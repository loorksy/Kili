export interface ChartAnnotation {
  id: string;
  type: string;
  text: string;
  created_by: string;
  updated_at: number;
  library_name?: string | null;
  visible?: boolean;
  locked?: boolean;
  origin?: string;
  revision?: number;
  points: { timestamp: number | null; value: string }[];
}
export interface CloudChartState {
  id: string;
  revision: number;
  canonical_instrument: string;
  provider_instrument: string;
  timeframe: string;
  session_key: string;
  annotations: ChartAnnotation[];
  temporary_annotations?: ChartAnnotation[];
  studies: string[];
  indicator_instances?: { id: string; indicator_id: string; calc_params: number[]; pane: "main" | "separate"; visible: boolean }[];
  computed_series?: { instance_id: string; name: string; kind: string; pane: string; color: string; values: (string | null)[] }[];
  computed_timestamps?: number[];
  drawing_tools?: { id: string; anchors: number }[];
  candle_count?: number;
  right_spacing?: number;
  visible_range?: [number, number] | null;
}
export interface ChartReference {
  chart_id: string;
  session_key: string;
}
export function parseChartReference(text: string): ChartReference | null {
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== "object" || !("chart_id" in value) || !("session_key" in value)) return null;
    if (typeof value.chart_id !== "string" || !/^chart_[a-f0-9]{32}$/.test(value.chart_id)
        || typeof value.session_key !== "string") return null;
    return { chart_id: value.chart_id, session_key: value.session_key };
  } catch { return null; }
}
