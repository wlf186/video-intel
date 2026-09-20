export type Mode = "t2v" | "i2v" | "r2v";
export type Preset = "preview" | "standard" | "native";
export type Job = {
  id: string;
  prompt: string;
  soundscape: string;
  effective_prompt: string;
  prompt_format?: "guided" | "raw";
  prompt_template_version?: string;
  prompt_warnings?: string[];
  music?: string;
  reference_descriptions?: string[];
  mode: Mode;
  preset: Preset;
  seed: number;
  width: number;
  height: number;
  frames: number;
  fps: number;
  requested_duration_seconds: number;
  duration_seconds: number;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  stage_code: string;
  progress: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  error_code: string | null;
  images: string[];
  metrics: Record<string, number>;
  cancel_requested: boolean;
  storage_bytes?: number | null;
  sample_step?: number;
  sample_steps?: number;
};
export type Capabilities = {
  max_prompt_chars: number;
  max_soundscape_chars: number;
  max_music_chars: number;
  max_raw_prompt_chars: number;
  max_reference_description_chars: number;
  prompt_formats: Array<"auto" | "guided" | "raw">;
  prompt_template_version: string;
  presets: Record<Preset, [number, number]>;
  default_preset: Preset;
  default_duration: number;
  durations: {
    requested_duration_seconds: number;
    frames: number;
    duration_seconds: number;
  }[];
};
export type PromptPreview = {
  effective_prompt: string;
  prompt_format: "guided" | "raw";
  prompt_template_version: string;
  prompt_warnings: string[];
};
export type StorageInfo = {
  categories: Record<string, number>;
  cleanable_bytes: number;
  jobs?: Array<
    Pick<
      Job,
      | "id"
      | "prompt"
      | "status"
      | "preset"
      | "duration_seconds"
      | "created_at"
      | "mode"
    > & { bytes: number }
  >;
  disk: { total: number; used: number; free: number };
  project_bytes: number;
  updated_at: string;
  busy: boolean;
};
export type SystemInfo = {
  status: string;
  backend: boolean;
  worker_alive: boolean;
  version: string;
  models: Record<Mode, boolean>;
  gpu: {
    name: string;
    used_mib: number;
    total_mib: number;
    utilization: number;
  } | null;
  memory: { total: number; available: number };
  disk: { total: number; free: number };
  bind: string;
  queue: number;
  running: number;
  paths: Record<string, string>;
  recent_errors: { id: string; error: string; finished_at: string }[];
  updated_at: number;
};
export type Cleanup = { job_ids: string[]; kinds: string[] };
export type CleanupPreview = {
  estimated_bytes: number;
  items: { id: string; bytes: number }[];
  skipped: { id: string; reason: string }[];
};
export type CleanupResult = {
  reclaimed_bytes: number;
  deleted: { id: string }[];
  failed: { id: string; reason: string }[];
  skipped: { id: string; reason: string }[];
};
export type Page = "workbench" | "history" | "system";
