import { useCallback, useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  History as HistoryIcon,
  AlertTriangle,
  Info,
  Activity,
  BookOpen,
  Menu,
  X,
  Trash2,
  RefreshCw,
  CheckCircle,
  ShieldCheck,
} from "lucide-react";
import { Workbench, initialDraft, type Draft } from "./Workbench";
import { readPromptDraft, draftFromJob } from "./promptState";
import { History } from "./History";
import { SystemPage } from "./SystemPage";
import type {
  Capabilities,
  Cleanup,
  CleanupPreview,
  CleanupResult,
  Job,
  Page,
} from "./types";
import {
  api,
  jsonBody,
  LocaleContext,
  message,
  Modal,
  size,
  terminal,
} from "./lib";
function readDraft(): Draft {
  try {
    return readPromptDraft(
      JSON.parse(sessionStorage.getItem("sv:draft") || "{}"),
    );
  } catch {
    return initialDraft;
  }
}
function readPage(): Page {
  const hash = location.hash.slice(1);
  if (hash === "storage") {
    history.replaceState(null, "", "#system/storage");
    return "system";
  }
  const page = hash.split(/[/?]/)[0];
  return ["workbench", "history", "system"].includes(page)
    ? (page as Page)
    : "workbench";
}
export default function App() {
  const [english, setEnglish] = useState(
      () => localStorage.getItem("sv:language") === "en",
    ),
    [page, setPage] = useState<Page>(readPage),
    [files, setFiles] = useState<File[]>([]),
    [flashKind, setFlashKind] = useState<"info" | "success" | "warning">(
      "info",
    ),
    [retry, setRetry] = useState<Cleanup | null>(null),
    [draft, setDraft] = useState<Draft>(readDraft),
    [caps, setCaps] = useState<Capabilities | null>(null),
    [jobs, setJobs] = useState<Job[]>([]),
    [selected, setSelected] = useState<Job | null>(null),
    [connected, setConnected] = useState(true),
    [ready, setReady] = useState(false),
    [revision, setRevision] = useState(0),
    [storageRevision, setStorageRevision] = useState(0),
    [flash, setFlash] = useState(""),
    [menu, setMenu] = useState(false),
    [cleanup, setCleanup] = useState<{
      request: Cleanup;
      preview: CleanupPreview;
    } | null>(null),
    [cleaning, setCleaning] = useState(false);
  const removed = useRef(new Set<string>());
  const t = (zh: string, en: string) => (english ? en : zh);
  const refresh = useCallback(async () => {
    try {
      const [latest, running, queued] = await Promise.all([
        api<Job[]>("/api/jobs?limit=100"),
        api<Job[]>("/api/jobs?status=running"),
        api<Job[]>("/api/jobs?status=queued"),
      ]);
      const all = Array.from(
        new Map(
          [...latest, ...running, ...queued].map((j) => [j.id, j]),
        ).values(),
      ).sort((a, b) => b.created_at.localeCompare(a.created_at));
      setJobs(all);
      setSelected((previous) => {
        const remembered = previous?.id || localStorage.getItem("sv:selected");
        if (remembered && removed.current.has(remembered)) return null;
        return (
          all.find((j) => j.id === remembered) ||
          previous ||
          all.find((j) => j.status === "succeeded") ||
          all[0] ||
          null
        );
      });
    } catch (e) {
      setFlash(message(e));
    }
  }, []);
  useEffect(() => {
    api<Capabilities>("/api/capabilities")
      .then(setCaps)
      .catch((e) => setFlash(message(e)));
    refresh();
    const health = () =>
      api<{ status: string }>("/api/health")
        .then((h) => setReady(h.status === "ready"))
        .catch(() => setReady(false));
    health();
    const timer = setInterval(() => {
      if (!document.hidden) health();
    }, 30000);
    const events = new EventSource("/api/events");
    events.onopen = () => setConnected(true);
    events.onerror = () => setConnected(false);
    events.addEventListener("connected", () => {
      setConnected(true);
      refresh();
    });
    const update = (event: MessageEvent) => {
      const job = JSON.parse(event.data) as Job;
      setJobs((old) => {
        const map = new Map(old.map((j) => [j.id, j]));
        map.set(job.id, job);
        return Array.from(map.values()).sort((a, b) =>
          b.created_at.localeCompare(a.created_at),
        );
      });
      setSelected((old) => (old?.id === job.id ? job : old));
      if (event.type === "job") {
        setRevision((r) => r + 1);
        if (terminal(job)) setStorageRevision((r) => r + 1);
      }
    };
    events.addEventListener("job", update as EventListener);
    events.addEventListener("progress", update as EventListener);
    events.addEventListener("storage", (event) => {
      const result = JSON.parse((event as MessageEvent).data) as CleanupResult;
      result.deleted.forEach((x) => removed.current.add(x.id));
      refresh();
      setRevision((r) => r + 1);
      setStorageRevision((r) => r + 1);
    });
    events.addEventListener("reset", () => {
      refresh();
      setRevision((r) => r + 1);
    });
    return () => {
      events.close();
      clearInterval(timer);
    };
  }, [refresh]);
  useEffect(() => {
    const save = () => {
      try {
        sessionStorage.setItem("sv:draft", JSON.stringify(draft));
      } catch {}
    };
    const timer = setTimeout(save, 400);
    window.addEventListener("pagehide", save);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("pagehide", save);
    };
  }, [draft]);
  useEffect(() => {
    document.documentElement.lang = english ? "en" : "zh-CN";
    localStorage.setItem("sv:language", english ? "en" : "zh");
    document.title = `${{ workbench: t("生成工作台", "Generate"), history: t("任务库", "Task library"), system: t("系统", "System") }[page]} · Sandevistan Video`;
  }, [english, page]);
  useEffect(() => {
    if (selected) localStorage.setItem("sv:selected", selected.id);
  }, [selected?.id]);
  useEffect(() => {
    const handler = () => setPage(readPage());
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  function navigate(
    p: Page | "system/storage" | "history?status=terminal&sort=size_desc",
  ) {
    setPage(
      p.startsWith("system")
        ? "system"
        : p.startsWith("history")
          ? "history"
          : "workbench",
    );
    location.hash = p;
    setMenu(false);
    window.scrollTo(0, 0);
  }
  const manageTasks = () => navigate("history?status=terminal&sort=size_desc");
  useEffect(() => {
    const source = draft.source_job_id;
    if (!source || draft.source_image_count) return;
    const controller = new AbortController();
    api<Job>(`/api/jobs/${source}`, { signal: controller.signal })
      .then((job) => {
        if (!controller.signal.aborted)
          setDraft((current) =>
            current.source_job_id === source
              ? { ...current, source_image_count: job.images.length }
              : current,
          );
      })
      .catch(() => {
        /* Submission reports missing source tasks through the existing error flow. */
      });
    return () => controller.abort();
  }, [draft.source_job_id, draft.source_image_count]);
  function reuse(job: Job) {
    setFiles([]);
    setFlashKind("info");
    setRetry(null);
    setDraft(draftFromJob(job));
    navigate("workbench");
    setFlash(
      t(
        job.prompt_template_version
          ? "已复用参数，可修改后生成新任务。"
          : "已沿用旧任务的最终提示词；返回描述表单可使用新版模板。",
        job.prompt_template_version
          ? "Settings reused. Edit them to create a new task."
          : "The legacy task's final prompt is preserved. Return to the description form to use the new template.",
      ),
    );
  }
  async function cancel(job: Job) {
    try {
      const result = await api<Job>(`/api/jobs/${job.id}/cancel`, {
        method: "POST",
      });
      setSelected((old) => (old?.id === job.id ? result : old));
      refresh();
    } catch (e) {
      setFlashKind("warning");
      setFlash(message(e, english));
    }
  }
  async function preview(request: Cleanup) {
    try {
      const result = await api<CleanupPreview>(
        "/api/storage/cleanup/preview",
        jsonBody(request),
      );
      setCleanup({ request, preview: result });
    } catch (e) {
      setFlashKind("warning");
      setFlash(message(e, english));
    }
  }
  async function confirmCleanup() {
    if (!cleanup) return;
    setCleaning(true);
    setRetry(null);
    try {
      const result = await api<CleanupResult>(
        "/api/storage/cleanup",
        jsonBody(cleanup.request),
      );
      setCleanup(null);
      const issues = [...result.failed, ...result.skipped];
      setFlashKind(issues.length ? "warning" : "success");
      if (issues.length) {
        const ids = new Set(issues.map((x) => x.id));
        setRetry({
          job_ids: cleanup.request.job_ids.filter((id) => ids.has(id)),
          kinds: cleanup.request.kinds.filter((id) => ids.has(id)),
        });
      }
      const deleted = new Set(result.deleted.map((x) => x.id));
      deleted.forEach((id) => removed.current.add(id));
      setFlash(
        t(
          `${issues.length ? (result.deleted.length ? "部分完成" : "未完成") : "清理完成"}，已释放 ${size(result.reclaimed_bytes)}。`,
          `${issues.length ? (result.deleted.length ? "Partially completed" : "Not completed") : "Cleanup complete"}. Freed ${size(result.reclaimed_bytes)}. `,
        ) +
          [...result.failed, ...result.skipped]
            .map((x) => x.id.slice(0, 8) + ": " + message(x.reason, english))
            .join("；"),
      );
      await refresh();
      setSelected((old) => (old && deleted.has(old.id) ? null : old));
      setRevision((r) => r + 1);
      setStorageRevision((r) => r + 1);
    } catch (e) {
      setFlashKind("warning");
      setFlash(message(e, english));
    } finally {
      setCleaning(false);
    }
  }
  const tabs = [
    [
      "workbench",
      Clapperboard,
      t("生成工作台", "Generate"),
      t("生成", "Generate"),
    ],
    [
      "history",
      HistoryIcon,
      t("任务库", "Task library"),
      t("任务库", "Library"),
    ],
    ["system", Activity, t("系统", "System"), t("系统", "System")],
  ] as const;
  return (
    <LocaleContext.Provider value={{ english, setEnglish }}>
      <div className="app-shell">
        <a className="skip-link" href="#main-content">
          {t("跳到主要内容", "Skip to content")}
        </a>
        <header className="app-header">
          <button className="brand" onClick={() => navigate("workbench")}>
            <img src="/logo.png" alt="" />
            <span>Sandevistan Video</span>
          </button>
          <nav
            className="desktop-nav"
            aria-label={t("主导航", "Main navigation")}
          >
            {tabs.map(([id, Icon, label]) => (
              <button
                key={id}
                className={page === id ? "active" : ""}
                onClick={() => navigate(id)}
                aria-current={page === id ? "page" : undefined}
              >
                <Icon size={21} />
                {label}
              </button>
            ))}
          </nav>
          <div className="header-actions">
            <select
              aria-label={t("界面语言", "Interface language")}
              value={english ? "en" : "zh"}
              onChange={(e) => setEnglish(e.target.value === "en")}
            >
              <option value="zh">简体中文</option>
              <option value="en">English</option>
            </select>
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="docs-link"
            >
              <BookOpen size={18} />
              <span>{t("API 文档", "API docs")}</span>
            </a>
            <button
              className="mobile-menu icon-button"
              onClick={() => setMenu(!menu)}
              aria-label={t("菜单", "Menu")}
              aria-expanded={menu}
            >
              {menu ? <X /> : <Menu />}
            </button>
          </div>
        </header>
        {menu && (
          <div className="menu-popover">
            <label>
              {t("界面语言", "Language")}
              <select
                value={english ? "en" : "zh"}
                onChange={(e) => setEnglish(e.target.value === "en")}
              >
                <option value="zh">简体中文</option>
                <option value="en">English</option>
              </select>
            </label>
            <a href="/docs" target="_blank" rel="noreferrer">
              API {t("文档", "docs")}
            </a>
          </div>
        )}
        {!connected && (
          <div className="connection-banner" role="status">
            <RefreshCw size={16} />
            {t(
              "连接暂时中断，任务仍在服务器运行。正在重新连接…",
              "Connection interrupted. Tasks continue on the server. Reconnecting…",
            )}
          </div>
        )}
        {flash && (
          <div
            className={`notice ${flashKind}`}
            role={flashKind === "warning" ? "alert" : "status"}
          >
            {flashKind === "success" ? (
              <CheckCircle size={17} />
            ) : flashKind === "warning" ? (
              <AlertTriangle size={17} />
            ) : (
              <Info size={17} />
            )}
            <span>{flash}</span>
            {retry && (
              <button onClick={() => preview(retry)}>
                {t("重试未完成项", "Retry unfinished items")}
              </button>
            )}
            <button
              className="icon-button"
              aria-label={t("关闭提示", "Dismiss")}
              onClick={() => {
                setFlash("");
                setRetry(null);
              }}
            >
              <X size={16} />
            </button>
          </div>
        )}
        <main id="main-content">
          {page === "workbench" && (
            <Workbench
              draft={draft}
              setDraft={(next) => {
                if (
                  next.mode !== draft.mode ||
                  (next.source_job_id &&
                    next.source_job_id !== draft.source_job_id)
                )
                  setFiles([]);
                setDraft(next);
              }}
              files={files}
              setFiles={setFiles}
              onManageTasks={manageTasks}
              onStorage={() => navigate("system/storage")}
              caps={caps}
              selected={selected}
              jobs={jobs}
              onSelect={setSelected}
              onSubmit={(job) => {
                setSelected(job);
                refresh();
                setRevision((r) => r + 1);
              }}
              onReuse={reuse}
              onCancel={cancel}
              onHistory={() => navigate("history")}
              english={english}
            />
          )}{" "}
          {page === "history" && (
            <History
              selected={selected}
              onSelect={setSelected}
              onReuse={reuse}
              onCancel={cancel}
              onCleanup={preview}
              english={english}
              revision={revision}
              liveJobs={jobs}
            />
          )}{" "}
          {page === "system" && (
            <SystemPage
              onCleanup={preview}
              onManageTasks={manageTasks}
              onRefreshStorage={() => setRevision((r) => r + 1)}
              storageRevision={storageRevision}
              english={english}
            />
          )}
        </main>
        <footer className="app-footer">
          <span>
            <i className={ready ? "ready" : ""} />
            {t("本地引擎", "Local engine")}{" "}
            <b>{ready ? t("已就绪", "Ready") : t("连接中", "Connecting")}</b>
          </span>
          <span>{t("单任务运行", "Single-task execution")}</span>
          <span className="mono">20820</span>
          <span className="footer-right">
            <ShieldCheck size={14} />
            {t("本地音画生成", "Local video + audio")}
          </span>
        </footer>
        <nav
          className="bottom-nav"
          aria-label={t("移动导航", "Mobile navigation")}
        >
          {tabs.map(([id, Icon, , label]) => (
            <button
              key={id}
              className={page === id ? "active" : ""}
              onClick={() => navigate(id)}
              aria-current={page === id ? "page" : undefined}
            >
              <Icon size={23} />
              {label}
            </button>
          ))}
        </nav>
        {cleanup && (
          <Modal
            title={
              cleanup.request.job_ids.length
                ? t(
                    `删除 ${cleanup.request.job_ids.length} 个任务及文件？`,
                    `Delete ${cleanup.request.job_ids.length} tasks and files?`,
                  )
                : t("确认存储维护", "Confirm storage maintenance")
            }
            onClose={() => {
              if (!cleaning) setCleanup(null);
            }}
          >
            <div className="confirm-space">
              <Trash2 size={32} />
              <span>
                {t("预计释放", "Estimated space")}
                <strong>{size(cleanup.preview.estimated_bytes)}</strong>
              </span>
            </div>
            <p>
              {cleanup.request.job_ids.length
                ? t(
                    "将永久删除所选任务的素材、视频和记录。此操作不可恢复。",
                    "Permanently delete selected inputs, videos and records. This cannot be undone.",
                  )
                : t(
                    "仅清理所选类别的可删除文件，正式结果和模型受到保护。",
                    "Only eligible files in the selected categories will be removed. Final results and models are protected.",
                  )}
            </p>
            {cleanup.request.kinds.length > 0 && (
              <p className="muted">
                {t("本次范围：", "Scope: ")}
                {cleanup.request.kinds
                  .map(
                    (kind) =>
                      ({
                        residual: t(
                          "已结束任务的多余文件",
                          "Finished-task leftovers",
                        ),
                        temporary: t(
                          "空闲时的临时文件",
                          "Temporary files while idle",
                        ),
                        cache: t("可再生缓存", "Regenerable caches"),
                        logs: t("归档日志", "Archived logs"),
                        database: t("数据库压缩", "Database compaction"),
                      })[kind],
                  )
                  .join(" · ")}
              </p>
            )}
            {cleanup.request.kinds.includes("database") && (
              <p className="muted">
                {t(
                  "数据库压缩会重写数据库，仅在需要回收空间时使用。",
                  "Compaction rewrites the database. Use it only when you need to reclaim space.",
                )}
              </p>
            )}
            {cleanup.preview.skipped.length > 0 && (
              <div className="warning">
                {cleanup.preview.skipped.map((x) => (
                  <p key={x.id}>
                    {x.id.slice(0, 8)} · {message(x.reason, english)}
                  </p>
                ))}
              </div>
            )}
            <div className="modal-actions">
              <button disabled={cleaning} onClick={() => setCleanup(null)}>
                {t("返回", "Back")}
              </button>
              <button
                className="danger"
                disabled={cleaning || cleanup.preview.items.length === 0}
                onClick={confirmCleanup}
              >
                <Trash2 size={17} />
                {cleaning
                  ? t("清理中…", "Cleaning…")
                  : cleanup.request.job_ids.length
                    ? t("删除任务及文件", "Delete tasks and files")
                    : t("确认清理", "Confirm cleanup")}
              </button>
            </div>
          </Modal>
        )}
      </div>
    </LocaleContext.Provider>
  );
}
