import { useEffect, useState } from "react";
import { RefreshCw, FileText, Activity, Server, Cpu } from "lucide-react";
import { StorageMaintenance } from "./StorageMaintenance";
import type { Cleanup, SystemInfo } from "./types";
import { api, message, Modal, size, useText } from "./lib";
export function SystemPage({
  onCleanup,
  onManageTasks,
  onRefreshStorage,
  storageRevision,
  english,
}: {
  onCleanup: (request: Cleanup) => void;
  onManageTasks: () => void;
  onRefreshStorage: () => void;
  storageRevision: number;
  english: boolean;
}) {
  const t = useText();
  const [info, setInfo] = useState<SystemInfo | null>(null),
    [error, setError] = useState(""),
    [logs, setLogs] = useState<{ name: string; text: string }[] | null>(null);
  async function refresh() {
    try {
      setInfo(await api<SystemInfo>("/api/system"));
      setError("");
    } catch (e) {
      setError(message(e, english));
    }
  }
  useEffect(() => {
    refresh();
    const timer = setInterval(() => {
      if (!document.hidden) refresh();
    }, 15000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="system-page">
      <header className="page-heading">
        <h1>{t("系统", "System")}</h1>
        <button onClick={refresh}>
          <RefreshCw size={17} />
          {t("刷新", "Refresh")}
        </button>
        {info && (
          <small className="muted">
            {t("最后更新", "Updated")}{" "}
            {new Date(info.updated_at * 1000).toLocaleTimeString()}
          </small>
        )}
      </header>
      {error && <p className="error">{error}</p>}
      {!info ? (
        <div className="empty">
          {t("正在连接本地服务…", "Connecting to the local service…")}
        </div>
      ) : (
        <>
          <div className="system-columns">
            <section className="panel">
              <h2>
                <Server size={20} />
                {t("服务", "Services")}
              </h2>
              <dl className="system-rows">
                <dt>{t("网页服务", "Web service")}</dt>
                <dd>
                  <span className="status succeeded">
                    <i />
                    {t("已就绪", "Ready")}
                  </span>
                </dd>
                <dt>{t("推理引擎", "Inference engine")}</dt>
                <dd>
                  <span
                    className={`status ${info.backend ? "succeeded" : "failed"}`}
                  >
                    <i />
                    {info.backend
                      ? t("已就绪", "Ready")
                      : t("未连接", "Disconnected")}
                  </span>
                </dd>
                <dt>{t("任务队列", "Task queue")}</dt>
                <dd>
                  {info.running
                    ? t("正在生成", "Generating")
                    : t("空闲", "Idle")}{" "}
                  · {info.queue} {t("等待", "waiting")}
                </dd>
                <dt>{t("监听地址", "Listening address")}</dt>
                <dd className="mono">{info.bind}</dd>
                <dt>{t("服务版本", "Version")}</dt>
                <dd className="mono">{info.version}</dd>
              </dl>
            </section>
            <section className="panel">
              <h2>
                <Cpu size={20} />
                {t("硬件", "Hardware")}
              </h2>
              <dl className="system-rows">
                <dt>GPU</dt>
                <dd>{info.gpu?.name || t("不可用", "Unavailable")}</dd>
                <dt>{t("系统内存", "System memory")}</dt>
                <dd>
                  {size(info.memory.total)} · {size(info.memory.available)}{" "}
                  {t("可用", "available")}
                </dd>
                <dt>{t("显存使用", "GPU memory")}</dt>
                <dd>
                  {info.gpu ? (
                    <>
                      <div className="resource-bar">
                        <span
                          style={{
                            width: `${(info.gpu.used_mib / info.gpu.total_mib) * 100}%`,
                          }}
                        />
                      </div>
                      <span className="mono">
                        {(info.gpu.used_mib / 1024).toFixed(1)} /{" "}
                        {(info.gpu.total_mib / 1024).toFixed(1)} GiB
                      </span>
                    </>
                  ) : (
                    "—"
                  )}
                </dd>
                <dt>{t("磁盘可用", "Free disk")}</dt>
                <dd className="mono">{size(info.disk.free)}</dd>
              </dl>
            </section>
          </div>
          <StorageMaintenance
            onCleanup={onCleanup}
            onManageTasks={onManageTasks}
            onRefresh={onRefreshStorage}
            revision={storageRevision}
            english={english}
          />
          <section className="panel models">
            <h2>{t("本地模型", "Local models")}</h2>
            <table>
              <thead>
                <tr>
                  <th>{t("模型", "Model")}</th>
                  <th>{t("用途", "Purpose")}</th>
                  <th>{t("状态", "Status")}</th>
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    "FL2VA INT8",
                    t("文字与首帧生成", "Text and first-frame generation"),
                    info.models.t2v && info.models.i2v,
                  ],
                  [
                    "Ref2VA INT8",
                    t("参考图生成", "Reference generation"),
                    info.models.r2v,
                  ],
                  ["Qwen3-VL", t("文字编码", "Text encoding"), info.models.t2v],
                  [
                    "Video & Audio VAE",
                    t("音画解码", "Video and audio decoding"),
                    info.models.t2v,
                  ],
                ].map(([name, purpose, ready]) => (
                  <tr key={String(name)}>
                    <td>{name}</td>
                    <td>{purpose}</td>
                    <td>
                      <span
                        className={`status ${ready ? "succeeded" : "failed"}`}
                      >
                        <i />
                        {ready
                          ? t("已就绪", "Ready")
                          : t("未就绪", "Not ready")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <div className="system-columns">
            <section className="panel">
              <h2>{t("运行目录", "Runtime directories")}</h2>
              <dl className="system-rows">
                <dt className="mono">data/</dt>
                <dd>{t("任务与素材", "Tasks and inputs")}</dd>
                <dt className="mono">tmp/</dt>
                <dd>{t("临时文件", "Temporary files")}</dd>
                <dt className="mono">cache/</dt>
                <dd>{t("可再生缓存", "Regenerable caches")}</dd>
                <dt className="mono">logs/</dt>
                <dd>{t("轮转服务日志", "Rotating service logs")}</dd>
              </dl>
            </section>
            <section className="panel">
              <h2>
                <Activity size={20} />
                {t("最近异常", "Recent errors")}
              </h2>
              {info.recent_errors.length ? (
                <div className="recent-errors">
                  {info.recent_errors.map((e) => (
                    <details key={e.id}>
                      <summary>
                        {e.id.slice(0, 8)} ·{" "}
                        {new Date(e.finished_at).toLocaleString()}
                      </summary>
                      <p className="error">{e.error}</p>
                    </details>
                  ))}
                </div>
              ) : (
                <div className="system-empty">
                  <FileText size={29} />
                  <p>{t("暂无异常", "No recent errors")}</p>
                </div>
              )}
              <div className="actions">
                <button
                  className="accent"
                  onClick={async () => {
                    try {
                      setLogs(await api("/api/logs"));
                    } catch (e) {
                      setError(message(e, english));
                    }
                  }}
                >
                  <FileText size={17} />
                  {t("查看诊断日志", "Diagnostic logs")}
                </button>
              </div>
            </section>
          </div>
        </>
      )}
      {logs && (
        <Modal
          title={t("诊断日志", "Diagnostic logs")}
          onClose={() => setLogs(null)}
          wide
        >
          {logs.map((log) => (
            <section key={log.name}>
              <h3>{log.name}</h3>
              <pre className="log-text">{log.text}</pre>
            </section>
          ))}
        </Modal>
      )}
    </div>
  );
}
