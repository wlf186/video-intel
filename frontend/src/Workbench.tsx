import { useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  Image as ImageIcon,
  Images,
  Play,
  Download,
  Copy,
  ChevronRight,
  Upload,
  X,
  Clock,
  FileText,
  Square,
  Expand,
  Volume2,
  VolumeX,
} from "lucide-react";
import type { Capabilities, Job, Preset } from "./types";
import {
  ApiError,
  api,
  duration,
  message,
  seconds,
  Status,
  terminal,
  usePreset,
  useStage,
  useText,
} from "./lib";
import { type Draft, promptFields } from "./promptState";
import { PromptEditor } from "./PromptEditor";
export { initialDraft, type Draft } from "./promptState";
export function Player({ job }: { job: Job }) {
  const t = useText();
  const ref = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState(false);
  return (
    <div className="player">
      <video
        ref={ref}
        src={`/api/jobs/${job.id}/video`}
        preload="metadata"
        poster={`/api/jobs/${job.id}/poster`}
        playsInline
        onTimeUpdate={(e) => setPosition(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onError={() => setError(true)}
        onClick={() => {
          const v = ref.current;
          if (v) v.paused ? v.play().catch(() => setError(true)) : v.pause();
        }}
      />
      {error && (
        <p className="error">
          {t(
            "无法播放视频，请尝试下载或重新加载。",
            "Unable to play. Try downloading or reloading.",
          )}
        </p>
      )}
      <div className="transport">
        <button
          className="icon-button"
          onClick={() => {
            const v = ref.current;
            if (v) v.paused ? v.play().catch(() => setError(true)) : v.pause();
          }}
          aria-label={playing ? t("暂停", "Pause") : t("播放", "Play")}
        >
          {playing ? <Square size={19} /> : <Play size={20} />}
        </button>
        <span>
          {duration(position)} / {duration(job.duration_seconds)}
        </span>
        <input
          type="range"
          min={0}
          max={job.duration_seconds}
          step={0.01}
          value={position}
          onChange={(e) => {
            if (ref.current) ref.current.currentTime = +e.target.value;
            setPosition(+e.target.value);
          }}
          aria-label={t("播放进度", "Playback position")}
        />
        <button
          className="icon-button"
          aria-label={t("切换静音", "Toggle mute")}
          onClick={() => {
            if (ref.current) ref.current.muted = !muted;
            setMuted(!muted);
          }}
        >
          {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
        </button>
        <button
          className="icon-button"
          aria-label={t("全屏", "Fullscreen")}
          onClick={() => ref.current?.requestFullscreen()}
        >
          <Expand size={19} />
        </button>
      </div>
    </div>
  );
}
export function Result({
  job,
  onReuse,
  onCancel,
}: {
  job: Job | null;
  onReuse: (j: Job) => void;
  onCancel: (j: Job) => void;
}) {
  const t = useText(),
    preset = usePreset(),
    stage = useStage();
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    if (!job || terminal(job)) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job?.id, job?.status]);
  if (!job)
    return (
      <div className="preview-empty panel">
        <Clapperboard size={54} />
        <h2>
          {t("你的下一个镜头，从这里开始", "Your next scene starts here")}
        </h2>
        <p>
          {t(
            "描述画面与声音，或上传一张参考图。",
            "Describe the picture and sound, or add a reference image.",
          )}
        </p>
        <span>MiniMax H3 · {t("本地音画生成", "Local video + audio")}</span>
      </div>
    );
  const elapsed =
    job.started_at && !terminal(job)
      ? Math.max(0, (clock - new Date(job.started_at).getTime()) / 1000)
      : job.metrics.elapsed_seconds || 0;
  return (
    <>
      <div className="preview-frame panel">
        {job.status === "succeeded" ? (
          <Player key={job.id} job={job} />
        ) : (
          <div className="progress-stage">
            <Clapperboard size={52} />
            <Status value={job.status} />
            <h2>
              {terminal(job)
                ? t("这次任务未完成", "This task did not complete")
                : stage(job)}
            </h2>
            {!terminal(job) && (
              <>
                <div className="progress">
                  <span style={{ width: `${job.progress}%` }} />
                </div>
                <span className="mono">
                  {job.progress}% · {t("已用时", "Elapsed")} {duration(elapsed)}
                </span>
              </>
            )}
            {job.error && <p className="error">{job.error}</p>}
            {job.status === "failed" && (
              <p className="muted">
                {t(
                  "复用参数可创建新任务，原任务记录会保留。",
                  "Reuse settings to create a new task; this record is preserved.",
                )}
              </p>
            )}
          </div>
        )}
      </div>
      <section className="result-summary panel">
        <div>
          <Status value={job.status} />
          <p>
            {preset(job.preset)} · {seconds(job.duration_seconds)}{" "}
            {t("秒", "s")} · {t("带声", "Stereo audio")}
          </p>
        </div>
        <div className="actions">
          {job.status === "succeeded" && (
            <a
              className="button accent"
              href={`/api/jobs/${job.id}/video?download=true`}
            >
              <Download size={18} />
              {t("下载 MP4", "Download MP4")}
            </a>
          )}
          <button onClick={() => onReuse(job)}>
            <Copy size={17} />
            {t("复用参数", "Reuse settings")}
          </button>
          {!terminal(job) && (
            <button
              className="danger"
              disabled={job.cancel_requested}
              onClick={() => onCancel(job)}
            >
              {t("取消任务", "Cancel task")}
            </button>
          )}
        </div>
      </section>
    </>
  );
}
export function Workbench({
  draft,
  setDraft,
  caps,
  selected,
  jobs,
  onSelect,
  onSubmit,
  onReuse,
  onCancel,
  files,
  setFiles,
  onManageTasks,
  onStorage,
  onHistory,
  english,
}: {
  draft: Draft;
  setDraft: (x: Draft) => void;
  caps: Capabilities | null;
  selected: Job | null;
  jobs: Job[];
  onSelect: (x: Job) => void;
  onSubmit: (x: Job) => void;
  onReuse: (x: Job) => void;
  onCancel: (x: Job) => void;
  files: File[];
  setFiles: (files: File[]) => void;
  onManageTasks: () => void;
  onStorage: () => void;
  onHistory: () => void;
  english: boolean;
}) {
  const t = useText(),
    preset = usePreset();
  const [lowDisk, setLowDisk] = useState(false),
    [previews, setPreviews] = useState<string[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const urls = files.map((f) => URL.createObjectURL(f));
    setPreviews(urls);
    return () => urls.forEach(URL.revokeObjectURL);
  }, [files]);
  const mapping = caps?.durations.find(
    (d) => d.requested_duration_seconds === draft.duration_seconds,
  );
  const active = jobs.filter((j) => !terminal(j));
  const history = jobs.filter(
    (j) =>
      j.status === "succeeded" &&
      j.preset === draft.preset &&
      j.mode === draft.mode &&
      j.requested_duration_seconds === draft.duration_seconds,
  );
  const estimate = history.length
    ? Math.round(
        history.reduce((sum, j) => sum + (j.metrics.elapsed_seconds || 0), 0) /
          history.length /
          60,
      )
    : null;
  const change = (values: Partial<Draft>) => setDraft({ ...draft, ...values });
  function choose(list: FileList | null) {
    if (!list) return;
    const next = Array.from(list);
    if (
      next.length > (draft.mode === "i2v" ? 1 : 3) ||
      next.some(
        (f) =>
          f.size > 15 * 1024 ** 2 ||
          !["image/png", "image/jpeg", "image/webp"].includes(f.type),
      )
    ) {
      setError(
        t(
          "请选择符合数量要求的 PNG、JPEG 或 WebP，每张不超过 15MB。",
          "Choose PNG, JPEG or WebP images, up to 15MB each, within the image limit.",
        ),
      );
      return;
    }
    setFiles(next);
    change({
      source_job_id: undefined,
      source_image_count: 0,
      reference_descriptions: draft.mode === "r2v" ? next.map(() => "") : [],
    });
    setError("");
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (
      draft.prompt_format === "guided" &&
      draft.music_mode === "custom" &&
      !draft.music.trim()
    ) {
      setError(
        t("请填写自定义配乐描述。", "Enter a custom score description."),
      );
      return;
    }
    setBusy(true);
    setLowDisk(false);
    try {
      const body = new FormData();
      const fields = {
        ...promptFields(draft),
        preset: draft.preset,
        seed: draft.seed,
        duration_seconds: draft.duration_seconds,
        source_job_id: draft.source_job_id,
      };
      for (const [key, value] of Object.entries(fields))
        if (value !== undefined)
          body.append(
            key,
            Array.isArray(value) ||
              ["prompt", "soundscape", "music"].includes(key)
              ? JSON.stringify(value)
              : String(value),
          );
      body.append("text_encoding", "json");
      files.forEach((file) => body.append("images", file));
      const job = await api<Job>("/api/jobs", { method: "POST", body });
      onSubmit(job);
    } catch (e) {
      setError(message(e, english));
      setLowDisk(e instanceof ApiError && e.code === "insufficient_storage");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="workbench">
      <form className="editor panel" onSubmit={submit}>
        <h1>{t("生成视频", "Generate video")}</h1>
        <div
          className="mode-tabs"
          role="tablist"
          aria-label={t("生成方式", "Generation mode")}
        >
          {(
            [
              ["t2v", FileText, t("文字生成", "Text")],
              ["i2v", ImageIcon, t("首帧生成", "First frame")],
              ["r2v", Images, t("外观参考", "Reference")],
            ] as const
          ).map(([mode, Icon, label]) => (
            <button
              key={mode}
              type="button"
              role="tab"
              aria-selected={draft.mode === mode}
              className={draft.mode === mode ? "active" : ""}
              onClick={() =>
                change({
                  mode,
                  source_job_id: undefined,
                  source_image_count: 0,
                  reference_descriptions: [],
                })
              }
            >
              <Icon size={21} />
              {label}
            </button>
          ))}
        </div>
        {draft.mode !== "t2v" && (
          <div
            className="image-input"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              choose(e.dataTransfer.files);
            }}
          >
            <button
              type="button"
              className="upload-button"
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={22} />
              <span>
                {t("选择或拖放图片", "Choose or drop images")}
                <small>
                  {draft.mode === "i2v"
                    ? t("1 张 · 将按画布居中裁剪", "1 image · Center cropped")
                    : t(
                        "1–3 张 · 保留原图比例",
                        "1–3 images · Original aspect ratio",
                      )}
                </small>
              </span>
            </button>
            <input
              ref={fileRef}
              hidden
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple={draft.mode === "r2v"}
              onChange={(e) => choose(e.target.files)}
            />
            {(previews.length > 0 || draft.source_job_id) && (
              <div className="image-previews">
                {(previews.length
                  ? previews
                  : Array.from(
                      { length: draft.source_image_count },
                      (_, i) => `/api/jobs/${draft.source_job_id}/images/${i}`,
                    )
                ).map((url, i) => (
                  <figure key={url}>
                    <img src={url} alt={t(`图片 ${i + 1}`, `Image ${i + 1}`)} />
                    <figcaption>
                      {t(`图片 ${i + 1}`, `Image ${i + 1}`)}
                    </figcaption>
                  </figure>
                ))}
              </div>
            )}
            {draft.source_job_id && !files.length && (
              <div className="reuse-images">
                <span>
                  {t(
                    "将复用原任务的图片",
                    "Original task images will be reused",
                  )}
                </span>
                <button
                  type="button"
                  className="icon-button"
                  onClick={() =>
                    change({
                      source_job_id: undefined,
                      source_image_count: 0,
                      reference_descriptions: [],
                    })
                  }
                  aria-label={t("移除复用图片", "Remove reused images")}
                >
                  <X size={16} />
                </button>
              </div>
            )}
          </div>
        )}
        <PromptEditor
          draft={draft}
          change={change}
          imageCount={files.length || draft.source_image_count}
          english={english}
        />
        <div className="settings-row">
          <label className="field">
            <span>{t("画质", "Quality")}</span>
            <select
              value={draft.preset}
              onChange={(e) => change({ preset: e.target.value as Preset })}
            >
              {(["preview", "standard", "native"] as const).map((p) => (
                <option key={p} value={p}>
                  {preset(p)} · {caps?.presets[p].join(" × ") || p}
                </option>
              ))}
            </select>
          </label>
          <div className="duration-field">
            <label htmlFor="duration-number">
              {t("时长（秒）", "Duration (s)")}
            </label>
            <div className="duration-control">
              <input
                id="duration-number"
                aria-label={t("视频时长", "Video duration")}
                type="number"
                min={4}
                max={15}
                step={1}
                required
                value={draft.duration_seconds}
                onChange={(e) => change({ duration_seconds: +e.target.value })}
              />
              <div>
                <input
                  type="range"
                  aria-label={t("时长滑块", "Duration slider")}
                  min={4}
                  max={15}
                  step={1}
                  value={draft.duration_seconds}
                  onChange={(e) =>
                    change({ duration_seconds: +e.target.value })
                  }
                />
                <div className="range-labels">
                  <span>4</span>
                  <span>15</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <p className="actual-duration">
          {t("实际输出", "Actual output")}{" "}
          {mapping ? seconds(mapping.duration_seconds) : "—"} {t("秒", "s")} ·{" "}
          {mapping?.frames || "—"} {t("帧", "frames")} · 24fps
        </p>
        <details className="advanced">
          <summary>
            {t("高级设置 · 随机种子", "Advanced · Random seed")}
          </summary>
          <label className="field">
            <span>
              {t("随机种子（-1 为随机）", "Random seed (−1 for random)")}
            </span>
            <input
              type="number"
              min={-1}
              max={4294967295}
              step={1}
              value={draft.seed}
              onChange={(e) => change({ seed: +e.target.value })}
            />
          </label>
        </details>
        <div className="form-bottom">
          <p className="estimate">
            <Clock size={15} />
            {estimate !== null
              ? t(
                  `本机历史参考：约 ${estimate} 分钟`,
                  `Local reference: about ${estimate} min`,
                )
              : t(
                  "此组合暂无本机耗时记录",
                  "No local timing record for this combination",
                )}
          </p>
          {lowDisk && (
            <div className="actions">
              <button type="button" onClick={onManageTasks}>
                {t("管理任务文件", "Manage task files")}
              </button>
              <button type="button" onClick={onStorage}>
                {t("清理运行残留", "Clean runtime leftovers")}
              </button>
            </div>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button
            className="primary generate"
            disabled={busy || !mapping}
            type="submit"
          >
            <Play size={22} />
            {busy
              ? t("提交中…", "Submitting…")
              : t("生成视频", "Generate video")}
          </button>
          <button
            className="text-button example"
            type="button"
            onClick={() =>
              change({
                prompt_format: "guided",
                prompt:
                  draft.mode === "r2v"
                    ? english
                      ? "[Shot 1] Live-action. <Subject 1> sits on a courtside bench. <Subject 2>, the basketball, rests at their feet. They raise <Subject 3>, the coffee cup, take a sip, and lower it gently. A continuous medium shot slowly pushes in. Preserve the referenced appearances."
                      : "[Shot 1] 写实风格。<Subject 1> 人物坐在球场边的长椅上，<Subject 2> 篮球静置在脚边。人物举起 <Subject 3> 咖啡杯喝一口，再轻轻放低。中景镜头缓慢推近，保持参考主体外观，单个连续镜头。"
                    : draft.mode === "i2v"
                      ? english
                        ? "The subject from the first frame moves gently forward, preserving its appearance and the initial composition. The camera follows at slow speed in one continuous shot."
                        : "从首帧的主体和构图开始，主体轻缓向前移动，保留原有外观。镜头缓慢跟随，单个连续镜头。"
                      : english
                        ? "A small red toy car rolls slowly along a wet garden path. The camera follows gently. A single continuous realistic shot."
                        : "红色玩具车驶过雨后的花园石径，镜头缓慢跟随。写实风格，单个连续镜头。",
                soundscape:
                  draft.mode === "r2v"
                    ? english
                      ? "Light wind, distant basketball bounces and soft clothing rustle."
                      : "轻微风声、远处篮球落地声和衣物摩擦声。"
                    : english
                      ? "Gentle ambient sound and physical sounds matching the movement."
                      : "轻柔环境声，以及与动作同步的物体运动声。",
                music_mode: "none",
                music: "",
              })
            }
          >
            {t("试用示例描述", "Try an example")}
          </button>
        </div>
      </form>
      <div className="viewer">
        <Result job={selected} onReuse={onReuse} onCancel={onCancel} />
        {selected && selected.images.length > 0 && (
          <div className="used-images">
            <span>{t("本次采用的图片", "Images used")}</span>
            {selected.images.map((_, i) => (
              <img
                key={i}
                src={`/api/jobs/${selected.id}/images/${i}`}
                alt={t(`图片 ${i + 1}`, `Image ${i + 1}`)}
              />
            ))}
          </div>
        )}
        <section className="queue panel">
          <header>
            <h2>
              {t("当前队列", "Current queue")}{" "}
              {active.length > 0 && <small>{active.length}</small>}
            </h2>
            <button className="text-button" onClick={onHistory}>
              {t("查看任务库", "View history")}
              <ChevronRight size={16} />
            </button>
          </header>
          {active.length === 0 ? (
            <div className="queue-empty">
              <FileText size={31} />
              <p>{t("暂无等待任务", "No pending tasks")}</p>
              <small>
                {t(
                  "生成的任务将显示在这里",
                  "Your upcoming tasks will appear here",
                )}
              </small>
            </div>
          ) : (
            active.map((job, i) => (
              <button
                className={`queue-row ${selected?.id === job.id ? "selected" : ""}`}
                key={job.id}
                onClick={() => onSelect(job)}
              >
                <span className="queue-number">
                  {job.status === "running" ? (
                    <Play size={15} />
                  ) : (
                    String(i + 1).padStart(2, "0")
                  )}
                </span>
                <span className="queue-description">
                  {job.prompt}
                  <small>
                    {seconds(job.duration_seconds)}s · {preset(job.preset)}
                  </small>
                </span>
                <Status value={job.status} />
              </button>
            ))
          )}
        </section>
      </div>
    </div>
  );
}
