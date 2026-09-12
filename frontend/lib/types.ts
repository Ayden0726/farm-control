export type Printer = {
  id: string;
  name: string;
  model: string;
  adapter_type: string;
  base_url: string | null;
  has_api_key: boolean;
  is_enabled: boolean;
  status: string;
  nozzle_temp: number;
  bed_temp: number;
  target_nozzle: number;
  target_bed: number;
  current_file: string | null;
  progress_percent: number;
  time_remaining_seconds: number;
  current_job_id: string | null;
  assigned_spool_id: string | null;
  assigned_spool_name: string | null;
  last_error: string | null;
  last_seen_at: string | null;
  total_print_seconds: number;
  total_jobs: number;
  failed_jobs: number;
  last_maintenance_at: string | null;
  maintenance_interval_hours: number;
  maintenance_notes: string;
  qr_token: string;
  hours_until_maintenance: number | null;
  current_part?: string | null;
  production_run?: string | null;
  quantity_completed?: number | null;
  quantity_remaining?: number | null;
  eta?: string | null;
  filament_name?: string | null;
  filament_material?: string | null;
  estimated_filament_used_g?: number;
  estimated_filament_cost?: number;
};

export type Job = {
  id: string;
  production_run_id: string | null;
  production_run_name: string | null;
  gcode_file_id: string;
  gcode_filename: string | null;
  part_id: string | null;
  part_sku: string | null;
  assigned_printer_id: string | null;
  assigned_printer_name: string | null;
  actual_printer_id: string | null;
  actual_printer_name: string | null;
  status: string;
  queue_position: number;
  quantity_produced: number;
  progress_percent: number;
  started_at: string | null;
  completed_at: string | null;
  fail_reason: string | null;
  estimated_filament_grams: number;
  filament_used_grams: number;
  filament_cost: number;
  estimated_time_seconds: number;
  qr_token: string;
  created_at: string;
  filament_override?: boolean;
  hold_reason?: string | null;
  filament_required_g?: number;
  filament_available_g?: number;
};

export type RunItem = {
  id: string;
  part_id: string;
  part_sku: string;
  part_name: string;
  gcode_file_id: string | null;
  gcode_filename: string | null;
  required_qty: number;
  printed_qty: number;
  passed_qc: number;
  failed_qc: number;
  remaining_qty: number;
  remaining_to_print: number;
};

export type ProductionRun = {
  id: string;
  name: string;
  status: string;
  notes: string;
  created_at: string;
  printer_ids: string[];
  items: RunItem[];
  queued_jobs: number;
  printing_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
};

export type Part = {
  id: string;
  sku: string;
  name: string;
  description: string;
  is_active: boolean;
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_available: number;
};

export type GCode = {
  id: string;
  filename: string;
  part_id: string | null;
  part_sku: string | null;
  quantity_per_file: number;
  material: string;
  estimated_time_seconds: number;
  estimated_filament_grams: number;
  version: number;
  is_archived: boolean;
  notes: string;
  compatible_printer_ids: string[];
};

export type Stl = {
  id: string;
  filename: string;
  part_id: string | null;
  part_sku: string | null;
  notes: string;
  file_size_bytes: number;
  created_at: string;
  bbox_x_mm: number | null;
  bbox_y_mm: number | null;
  bbox_z_mm: number | null;
  triangle_count: number | null;
  copies_per_plate: number | null;
  pack_rotated: boolean;
  pack_cols: number | null;
  pack_rows: number | null;
  pack_bed_x_mm: number | null;
  pack_bed_y_mm: number | null;
  pack_gap_mm: number | null;
};

export type FarmSettings = {
  company_name: string;
  woocommerce_url: string;
  woocommerce_configured: boolean;
  notify_webhook_configured: boolean;
  simulated_time_scale: number;
  app_version: string;
  update_command: string;
  auto_part_ejection: boolean;
  pack_bed_x_mm: number;
  pack_bed_y_mm: number;
  pack_gap_mm: number;
};

export type Spool = {
  id: string;
  name: string;
  manufacturer: string;
  material: string;
  color: string;
  initial_weight_g: number;
  remaining_weight_g: number;
  cost: number;
  cost_per_kg: number;
  assigned_printer_id: string | null;
  assigned_printer_name: string | null;
  drying_status: string;
  qr_token: string;
  is_low: boolean;
};

export type Order = {
  id: string;
  reference: string;
  customer_name: string;
  customer_email: string;
  notes: string;
  source: string;
  status: string;
  shipping_status: string;
  production_run_id: string | null;
  lines: { product_id: string; product_sku: string; product_name: string; quantity: number }[];
  part_needs: {
    part_id: string;
    part_sku: string;
    part_name: string;
    required_qty: number;
    reserved_qty: number;
    to_produce: number;
  }[];
};

export type Product = {
  id: string;
  sku: string;
  name: string;
  description: string;
  woocommerce_product_id: number | null;
  is_active: boolean;
  bom: { id: string; part_id: string; part_sku: string; part_name: string; quantity: number; is_optional: boolean }[];
};

export type Dashboard = {
  generated_at: string;
  counts: Record<string, number>;
  printers: Printer[];
  waiting_for_bed_clear: Printer[];
  failed_jobs: Job[];
  upcoming_jobs: Job[];
  production_runs: ProductionRun[];
  orders_waiting: { id: string; reference: string; customer_name: string; status: string }[];
  orders_ready: { id: string; reference: string; customer_name: string; status: string }[];
  low_filament: {
    id: string;
    name: string;
    material: string;
    color: string;
    remaining_weight_g: number;
  }[];
};
