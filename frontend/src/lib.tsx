import {
  createContext,
  useContext,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import { X, Film } from "lucide-react";
import type { Job } from "./types";
export const LocaleContext = createContext({
  english: false,
  setEnglish: (_value: boolean) => {},
});
export function useText() {
  const { english } = useContext(LocaleContext);
  return (zh: string, en: string) => (english ? en : zh);
}
export function size(bytes: number) {
  if (!Number.isFinite(bytes)) return "—";
  const n = Math.max(0, bytes);
  return n >= 1024 ** 3
    ? `${(n / 1024 ** 3).toFixed(1)} GiB`
    : n >= 1024 ** 2
      ? `${(n / 1024 ** 2).toFixed(1)} MiB`
      : `${Math.ceil(n / 1024)} KiB`;
}
export function duration(n: number) {
  return `${Math.floor(n / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(n % 60)
    .toString()
    .padStart(2, "0")}`;
}
export function seconds(n: number) {
  return Number(n.toFixed(3)).toString();
}
export function date(s: string, english: boolean) {
  return new Date(s).toLocaleString(english ? "en-GB" : "zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
export function message(error: unknown, english = false) {
  const text = error instanceof Error ? error.message : String(error);
  const pieces = text.split(" / ");
  return pieces.length === 2 ? pieces[english ? 1 : 0] : text;
}
export class ApiError extends Error {
  constructor(
    text: string,
    public code?: string,
  ) {
    super(text);
  }
}
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let text = "Request failed";
    let code: string | undefined;
    try {
      const body = await response.json();
      code = body.code;
      text =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
    } catch {}
    throw new ApiError(text, code);
  }
  return response.json();
}
export const jsonBody = (value: unknown) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});
export const terminal = (j: Pick<Job, "status">) =>
  ["succeeded", "failed", "cancelled"].includes(j.status);
export function useStatus() {
  const t = useText();
  return (s: string) =>
    ({
      queued: t("排队中", "Queued"),
      running: t("生成中", "Running"),
      succeeded: t("已完成", "Complete"),
      failed: t("失败", "Failed"),
      cancelled: t("已取消", "Cancelled"),
    })[s] || s;
}
export function usePreset() {
  const t = useText();
  return (s: string) =>
    ({
      preview: t("预览", "Preview"),
      standard: t("标准", "Standard"),
      native: t("原生", "Native"),
    })[s] || s;
}
export function useStage() {
  const t = useText();
  return (j: Job) =>
    j.cancel_requested && !terminal(j)
      ? t(
          "正在取消，等待引擎释放资源",
          "Cancelling; waiting for engine acknowledgement",
        )
      : {
          waiting: t("等待推理引擎就绪", "Waiting for engine"),
          recovering: t("重新连接任务", "Reconnecting task"),
          loading: t("加载本地模型", "Loading local model"),
          encoding: t("编码画面与声音描述", "Encoding your description"),
          sampling: t(
            `采样 ${j.sample_step || 0} / ${j.sample_steps || 20}`,
            `Sampling ${j.sample_step || 0} / ${j.sample_steps || 20}`,
          ),
          video_decode: t("视频解码", "Decoding video"),
          audio_decode: t("音频解码", "Decoding audio"),
          saving: t("保存视频", "Saving video"),
          queued: t("任务已加入队列", "Task queued"),
        }[j.stage_code] || j.stage_code;
}
export function Status({ value }: { value: string }) {
  const label = useStatus();
  return (
    <span className={`status ${value}`}>
      <i />
      {label(value)}
    </span>
  );
}
export function Thumb({ job }: { job: Pick<Job, "id" | "status"> }) {
  const ref = useRef<HTMLImageElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.style.display = "block";
  }, [job.id]);
  return (
    <span className="thumb">
      <Film size={25} />
      {job.status === "succeeded" && (
        <img
          ref={ref}
          src={`/api/jobs/${job.id}/poster`}
          alt=""
          loading="lazy"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      )}
    </span>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const t = useText();
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? "modal wide" : "modal"}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <header>
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label={t("关闭", "Close")}
        >
          <X />
        </button>
      </header>
      {children}
    </dialog>
  );
}
