import type { Job, Mode, Preset } from "./types";

export type Draft = {
  prompt: string;
  soundscape: string;
  music: string;
  music_mode: "none" | "custom";
  prompt_format: "guided" | "raw";
  raw_prompt: string;
  raw_initialized: boolean;
  reference_descriptions: string[];
  source_image_count: number;
  mode: Mode;
  preset: Preset;
  duration_seconds: number;
  seed: number;
  source_job_id?: string;
};

export const initialDraft: Draft = {
  prompt: "",
  soundscape: "",
  music: "",
  music_mode: "none",
  prompt_format: "guided",
  raw_prompt: "",
  raw_initialized: false,
  reference_descriptions: [],
  source_image_count: 0,
  mode: "t2v",
  preset: "native",
  duration_seconds: 5,
  seed: -1,
};

export function readPromptDraft(value: Partial<Draft>): Draft {
  const draft = { ...initialDraft, ...value };
  if (
    !value.prompt_format &&
    /^[ \t]*(integrated_multimodal_description|detailed_description):/m.test(
      draft.prompt,
    )
  ) {
    draft.prompt_format = "raw";
    draft.raw_prompt = draft.prompt;
    draft.raw_initialized = true;
  }
  return draft;
}

export function draftFromJob(job: Job): Draft {
  const legacy = !job.prompt_template_version;
  const raw = legacy || job.prompt_format === "raw";
  return {
    ...initialDraft,
    prompt: legacy || !raw ? job.prompt : "",
    soundscape: job.soundscape || "",
    music: job.music || "",
    music_mode:
      job.music?.trim() && job.music.trim() !== "N/A" ? "custom" : "none",
    prompt_format: raw ? "raw" : "guided",
    raw_prompt: raw ? job.effective_prompt || job.prompt : "",
    raw_initialized: raw,
    reference_descriptions: job.reference_descriptions || [],
    source_image_count: job.images.length,
    mode: job.mode,
    preset: job.preset,
    duration_seconds: job.requested_duration_seconds,
    seed: job.seed,
    source_job_id: job.mode === "t2v" ? undefined : job.id,
  };
}

export function promptFields(draft: Draft) {
  const raw = draft.prompt_format === "raw";
  return {
    prompt: raw ? draft.raw_prompt : draft.prompt,
    prompt_format: draft.prompt_format,
    mode: draft.mode,
    soundscape: raw ? "" : draft.soundscape,
    music: !raw && draft.music_mode === "custom" ? draft.music : "",
    reference_descriptions:
      !raw && draft.mode === "r2v" ? draft.reference_descriptions : [],
  };
}
