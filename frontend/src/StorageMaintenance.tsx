import { useEffect, useState } from "react";
import { RefreshCw, Trash2, ArrowRight, ShieldCheck } from "lucide-react";
import type { Cleanup, StorageInfo } from "./types";
import { api, message, size, useText } from "./lib";

export function StorageMaintenance({
  onCleanup,
  onManageTasks,
  onRefresh,
  revision,
  english,
}: {
  onCleanup: (request: Cleanup) => void;
  onManageTasks: () => void;
  onRefresh: () => void;
  revision: number;
  english: boolean;
}) {
  const t = useText();
  const categories = [
    ["tasks", t("任务文件", "Task files")],
    ["temporary", t("临时文件", "Temporary files")],
    ["cache", t("缓存", "Caches")],
    ["logs", t("日志", "Logs")],
    ["database", t("数据库", "Database")],
    ["protected", t("模型与运行环境", "Models and runtime")],
  ] as const;
  const [info, setInfo] = useState<StorageInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function refresh(force = false) {
    setLoading(true);
    try {
      setInfo(
        await api<StorageInfo>(
          `/api/storage?include_jobs=false&refresh=${force}`,
        ),
      );
      setError("");
      if (force) onRefresh();
    } catch (e) {
      setError(message(e, english));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
  }, [revision]);
  useEffect(() => {
    const focus = () => {
      if (location.hash === "#system/storage") {
        const heading = document.getElementById("storage-maintenance");
        heading?.focus({ preventScroll: true });
        heading?.scrollIntoView({ block: "start" });
      }
    };
    focus();
    window.addEventListener("hashchange", focus);
    return () => window.removeEventListener("hashchange", focus);
  }, [!!info]);
  return (
    <section className="panel storage-maintenance">
      <header className="page-heading">
        <h2 id="storage-maintenance" tabIndex={-1}>
          {t("存储维护", "Storage maintenance")}
        </h2>
        <button disabled={loading} onClick={() => refresh(true)}>
          <RefreshCw size={17} />
          {t("刷新占用", "Refresh storage")}
        </button>
        {info && (
          <small className="muted">
            {t("最后统计", "Measured")}{" "}
            {new Date(info.updated_at).toLocaleTimeString()}
          </small>
        )}
      </header>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!info ? (
        <p className="muted">{t("正在统计占用…", "Measuring storage…")}</p>
      ) : (
        <>
          <section
            className="storage-overview project-storage"
            aria-label={t("项目存储占用", "Project storage usage")}
          >
            <header>
              <h3>{t("项目存储占用", "Project storage usage")}</h3>
              <b>{size(info.project_bytes)}</b>
            </header>
            <div className="storage-meter" aria-hidden="true">
              {categories.map(([key]) => (
                <span
                  key={key}
                  className={key}
                  style={{
                    width: `${info.project_bytes > 0 ? (info.categories[key] / info.project_bytes) * 100 : 0}%`,
                  }}
                />
              ))}
            </div>
            <div className="storage-legend">
              {categories.map(([key, label]) => (
                <div key={key} className={key}>
                  <i aria-hidden="true" />
                  <span>
                    {label}
                    {key === "protected" && (
                      <ShieldCheck
                        size={14}
                        aria-label={t("受保护", "Protected")}
                      />
                    )}
                    <strong>{size(info.categories[key])}</strong>
                  </span>
                </div>
              ))}
            </div>
          </section>
          <div className="storage-cards">
            <article>
              <h3>{t("磁盘可用", "Free disk space")}</h3>
              <strong>{size(info.disk.free)}</strong>
              <p className="muted">
                {t("磁盘总容量", "Disk capacity")} {size(info.disk.total)}
              </p>
            </article>
            <article>
              <h3>{t("任务文件", "Task files")}</h3>
              <strong>{size(info.categories.tasks)}</strong>
              <p className="muted">
                {t(
                  "素材和结果随任务一起删除。",
                  "Inputs and results are deleted with their task.",
                )}
              </p>
              <button onClick={onManageTasks}>
                {t("管理任务文件", "Manage task files")}
                <ArrowRight size={17} />
              </button>
            </article>
            <article>
              <h3>{t("可清理运行残留", "Cleanable runtime leftovers")}</h3>
              <strong className="yellow">{size(info.cleanable_bytes)}</strong>
              <p className="muted">
                {t(
                  "清理临时与重复文件，保留正式视频和任务记录。",
                  "Remove temporary and duplicate files; keep final videos and task records.",
                )}
              </p>
              <button
                className="accent"
                disabled={loading || !info.cleanable_bytes}
                onClick={() =>
                  onCleanup({ job_ids: [], kinds: ["residual", "temporary"] })
                }
              >
                <Trash2 size={17} />
                {t("清理运行残留", "Clean runtime leftovers")}
              </button>
              {info.busy && (
                <small className="muted">
                  {t(
                    "引擎忙碌：共享临时文件暂不计入可清理空间。",
                    "Engine busy: shared temporary files are currently protected.",
                  )}
                </small>
              )}
            </article>
          </div>
          <details className="advanced maintenance">
            <summary>
              {t(
                "高级维护：缓存、归档日志与数据库",
                "Advanced: caches, archived logs and database",
              )}
            </summary>
            <p className="muted">
              {t(
                "按需维护即可。清理缓存可能触发重新编译；压缩数据库会重写文件。",
                "Use when needed. Clearing caches may trigger recompilation; compaction rewrites the database.",
              )}
            </p>
            <div className="actions">
              <button
                disabled={info.busy}
                onClick={() => onCleanup({ job_ids: [], kinds: ["cache"] })}
              >
                {t("清理缓存", "Clear caches")} · {size(info.categories.cache)}
              </button>
              <button
                onClick={() => onCleanup({ job_ids: [], kinds: ["logs"] })}
              >
                {t("清理归档日志", "Clear archived logs")}
              </button>
              <button
                disabled={info.busy}
                onClick={() => onCleanup({ job_ids: [], kinds: ["database"] })}
              >
                {t("压缩数据库", "Compact database")}
              </button>
            </div>
            {info.busy && (
              <p className="muted">
                {t(
                  "缓存清理和数据库压缩需等待引擎与上传空闲。",
                  "Cache cleanup and database compaction require an idle engine and no uploads.",
                )}
              </p>
            )}
          </details>
          <details className="advanced protected-note">
            <summary>
              <ShieldCheck size={17} />{" "}
              {t("受保护的模型与运行环境", "Protected models and runtime")} ·{" "}
              {size(info.categories.protected)}
            </summary>
            <p>
              {t(
                "模型、依赖环境及正在使用的任务文件受保护。结果默认保留，由你在任务库中决定删除。",
                "Models, dependencies and task files in use are protected. Results are retained until you delete them in the task library.",
              )}
            </p>
          </details>
        </>
      )}
    </section>
  );
}
