import { useEffect, useState } from "react";
import {
  Search,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Download,
  Copy,
  FileJson,
  Film,
} from "lucide-react";
import type { Cleanup, Job } from "./types";
import {
  size,
  message,
  date,
  duration,
  seconds,
  Status,
  terminal,
  Thumb,
  usePreset,
  useText,
} from "./lib";
import { Player } from "./Workbench";
export function History({
  selected,
  onSelect,
  onReuse,
  onCancel,
  onCleanup,
  english,
  revision,
  liveJobs,
}: {
  selected: Job | null;
  onSelect: (j: Job) => void;
  onReuse: (j: Job) => void;
  onCancel: (j: Job) => void;
  onCleanup: (x: Cleanup) => void;
  english: boolean;
  revision: number;
  liveJobs: Job[];
}) {
  const t = useText(),
    preset = usePreset();
  const [items, setItems] = useState<Job[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(0),
    [pageSize, setPageSize] = useState(20),
    [sort, setSort] = useState(() =>
      location.hash.includes("size_desc") ? "size_desc" : "newest",
    ),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState(() =>
      location.hash.includes("terminal") ? "terminal" : "",
    ),
    [mode, setMode] = useState(""),
    [checked, setChecked] = useState<string[]>([]),
    [error, setError] = useState(""),
    [loadedQuery, setLoadedQuery] = useState("");
  const query = JSON.stringify([page, pageSize, sort, search, status, mode]);
  const loading = loadedQuery !== query;
  useEffect(() => {
    setPage(0);
    setChecked([]);
  }, [search, status, mode, sort, pageSize]);
  useEffect(() => {
    setChecked([]);
  }, [page]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          limit: String(pageSize),
          include_storage: "true",
          sort,
          offset: String(page * pageSize),
          search,
        });
        if (status) params.set("status", status);
        if (mode) params.set("mode", mode);
        const r = await fetch(`/api/jobs?${params}`, {
          signal: controller.signal,
        });
        if (!r.ok) throw new Error(t("无法加载任务", "Unable to load tasks"));
        const count = Number(r.headers.get("X-Total-Count"));
        setTotal(count);
        setPage((p) =>
          Math.min(p, Math.max(0, Math.ceil(count / pageSize) - 1)),
        );
        const next: Job[] = await r.json();
        if (controller.signal.aborted) return;
        setItems(next);
        setLoadedQuery(query);
        setChecked((old) =>
          old.filter((id) => next.some((job) => job.id === id)),
        );
        setError("");
      } catch (e) {
        if (!controller.signal.aborted) setError(String(e));
      }
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [page, pageSize, sort, search, status, mode, revision]);
  const rows = (loading ? [] : items).map((j) => ({
    ...j,
    ...liveJobs.find((x) => x.id === j.id),
    storage_bytes: j.storage_bytes,
  }));
  const toggle = (id: string) =>
    setChecked((old) =>
      old.includes(id) ? old.filter((x) => x !== id) : [...old, id],
    );
  return (
    <div className="history-page">
      <section className="history-list panel">
        <h1>{t("任务库", "Task library")}</h1>
        <div className="filter-bar">
          <label className="search">
            <Search size={18} />
            <input
              aria-label={t("搜索描述", "Search descriptions")}
              placeholder={t("搜索描述", "Search descriptions")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <select
            aria-label={t("状态筛选", "Filter status")}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">{t("全部状态", "All statuses")}</option>
            <option value="terminal">
              {t("已结束（可删除）", "Finished (deletable)")}
            </option>
            <option value="succeeded">{t("已完成", "Complete")}</option>
            <option value="running">{t("生成中", "Running")}</option>
            <option value="queued">{t("排队中", "Queued")}</option>
            <option value="failed">{t("失败", "Failed")}</option>
            <option value="cancelled">{t("已取消", "Cancelled")}</option>
          </select>
          <select
            aria-label={t("方式筛选", "Filter mode")}
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="">{t("全部方式", "All modes")}</option>
            <option value="t2v">{t("文字生成", "Text")}</option>
            <option value="i2v">{t("首帧生成", "First frame")}</option>
            <option value="r2v">{t("参考生成", "Reference")}</option>
          </select>
          <select
            aria-label={t("排序", "Sort")}
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="newest">{t("最新创建", "Newest first")}</option>
            <option value="oldest">{t("最早创建", "Oldest first")}</option>
            <option value="size_desc">
              {t("占用从大到小", "Largest files first")}
            </option>
          </select>
        </div>
        {checked.length > 0 && (
          <div className="batch-bar" role="status">
            <span>
              {t(
                `已选 ${checked.length} 个任务`,
                `${checked.length} tasks selected`,
              )}{" "}
              · {t("预计释放", "Estimated space")}{" "}
              <b>
                {size(
                  rows
                    .filter((j) => checked.includes(j.id))
                    .reduce((n, j) => n + (j.storage_bytes || 0), 0),
                )}
              </b>
            </span>
            <button onClick={() => setChecked([])}>
              {t("取消选择", "Clear selection")}
            </button>
            <button
              className="danger"
              onClick={() => onCleanup({ job_ids: checked, kinds: [] })}
            >
              <Trash2 size={17} />
              {t("删除任务及文件", "Delete tasks and files")}
            </button>
          </div>
        )}
        {error && <p className="error">{error}</p>}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label={t(
                      "选择当前页已结束任务",
                      "Select finished tasks on this page",
                    )}
                    disabled={loading || !rows.some(terminal)}
                    checked={
                      rows.some(terminal) &&
                      rows.filter(terminal).every((j) => checked.includes(j.id))
                    }
                    onChange={(e) =>
                      setChecked(
                        e.target.checked
                          ? rows.filter(terminal).map((j) => j.id)
                          : [],
                      )
                    }
                  />
                </th>
                <th>{t("视频", "Video")}</th>
                <th>{t("状态", "Status")}</th>
                <th>{t("时长", "Duration")}</th>
                <th>{t("画质", "Quality")}</th>
                <th>{t("占用", "Storage")}</th>
                <th>{t("创建时间", "Created")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((job) => (
                <tr
                  className={selected?.id === job.id ? "selected" : ""}
                  key={job.id}
                >
                  <td>
                    <input
                      type="checkbox"
                      aria-label={
                        t("选择任务", "Select task") + " " + job.id.slice(0, 8)
                      }
                      disabled={!terminal(job)}
                      checked={checked.includes(job.id)}
                      onChange={() => toggle(job.id)}
                    />
                  </td>
                  <td>
                    <button className="task-link" onClick={() => onSelect(job)}>
                      <Thumb job={job} />
                      <span>
                        {job.prompt}
                        <small>{job.id.slice(0, 8)}</small>
                      </span>
                    </button>
                  </td>
                  <td>
                    <Status value={job.status} />
                  </td>
                  <td className="mono">{seconds(job.duration_seconds)}s</td>
                  <td>{preset(job.preset)}</td>
                  <td className="mono nowrap">
                    {size(job.storage_bytes ?? NaN)}
                  </td>
                  <td className="mono nowrap">
                    {date(job.created_at, english)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && !error && (
            <div className="empty">
              <Film size={35} />
              <p>
                {loading
                  ? t("正在加载任务…", "Loading tasks…")
                  : t("没有匹配的任务", "No matching tasks")}
              </p>
            </div>
          )}
        </div>
        <footer className="pagination">
          <span>
            {t(`共 ${total} 个任务`, `${total} tasks`)}
            {checked.length > 0 &&
              ` · ${checked.length} ${t("已选", "selected")}`}
          </span>
          <select
            aria-label={t("每页数量", "Rows per page")}
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
          >
            {[20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {t(`每页 ${n} 条`, `${n} / page`)}
              </option>
            ))}
          </select>
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            aria-label={t("上一页", "Previous page")}
          >
            <ChevronLeft size={18} />
          </button>
          <span className="page-number">{page + 1}</span>
          <button
            disabled={(page + 1) * pageSize >= total}
            onClick={() => setPage((p) => p + 1)}
            aria-label={t("下一页", "Next page")}
          >
            <ChevronRight size={18} />
          </button>
        </footer>
      </section>
      <section className="history-detail panel">
        {selected ? (
          <>
            <header>
              <h2>{t("任务详情", "Task details")}</h2>
              <Status value={selected.status} />
            </header>
            {selected.status === "succeeded" ? (
              <Player job={selected} key={selected.id} />
            ) : (
              <div className="detail-empty">
                <Film size={45} />
                <p>{t("任务尚无视频结果", "No video result yet")}</p>
              </div>
            )}
            <h3>{t("任务信息", "Task information")}</h3>
            <dl className="properties">
              <dt>{t("分辨率", "Resolution")}</dt>
              <dd>
                {selected.width} × {selected.height}
              </dd>
              <dt>{t("时长", "Duration")}</dt>
              <dd>{seconds(selected.duration_seconds)}s</dd>
              <dt>{t("帧率", "Frame rate")}</dt>
              <dd>{selected.fps}fps</dd>
              <dt>{t("种子", "Seed")}</dt>
              <dd>{selected.seed}</dd>
              <dt>{t("耗时", "Elapsed")}</dt>
              <dd>{duration(selected.metrics.elapsed_seconds || 0)}</dd>
              <dt>{t("创建时间", "Created")}</dt>
              <dd>{date(selected.created_at, english)}</dd>
            </dl>
            <details className="advanced">
              <summary>
                {t("画面与声音描述", "Scene and sound descriptions")}
              </summary>
              <p className="description">{selected.prompt}</p>
              <p className="muted description">{selected.soundscape || "—"}</p>
              <p className="muted description">
                {selected.prompt_format === "guided"
                  ? t("背景配乐：", "Background score: ") +
                    (selected.music || t("无", "None"))
                  : t(
                      "以上为保存的输入，实际声音设置以最终提示词为准。",
                      "Saved inputs are shown above; the final prompt determines the actual sound settings.",
                    )}
              </p>
              {selected.reference_descriptions?.map(
                (text, i) =>
                  text && (
                    <p className="description" key={i}>
                      {`<Subject ${i + 1}>`} · {text}
                    </p>
                  ),
              )}
            </details>
            <details className="advanced final-prompt">
              <summary>{t("最终提示词", "Final prompt")}</summary>
              <p className="muted">
                {selected.prompt_template_version ||
                  t("旧版任务 · 原始快照", "Legacy task · original snapshot")}
              </p>
              <label className="field">
                <span>{t("实际提交内容", "Content sent to the model")}</span>
                <textarea
                  readOnly
                  rows={12}
                  value={selected.effective_prompt || selected.prompt}
                />
              </label>
              {selected.prompt_warnings?.map((warning) => (
                <p key={warning} className="warning">
                  {message(warning, english)}
                </p>
              ))}
            </details>
            {selected.error && <p className="error">{selected.error}</p>}
            <div className="detail-actions">
              {selected.status === "succeeded" && (
                <a
                  className="button accent"
                  href={`/api/jobs/${selected.id}/video?download=true`}
                >
                  <Download size={17} />
                  {t("下载 MP4", "Download MP4")}
                </a>
              )}
              <button onClick={() => onReuse(selected)}>
                <Copy size={17} />
                {t("复用参数", "Reuse settings")}
              </button>
              <a
                className="text-button"
                href={`/api/jobs/${selected.id}`}
                target="_blank"
                rel="noreferrer"
              >
                <FileJson size={17} />
                {t("查看参数", "Parameters")}
              </a>
              {terminal(selected) ? (
                <button
                  className="danger"
                  onClick={() =>
                    onCleanup({ job_ids: [selected.id], kinds: [] })
                  }
                >
                  <Trash2 size={16} />
                  {t("删除任务及文件", "Delete task and files")}
                </button>
              ) : (
                <button
                  className="danger"
                  disabled={selected.cancel_requested}
                  onClick={() => onCancel(selected)}
                >
                  {t("取消任务", "Cancel task")}
                </button>
              )}
            </div>
          </>
        ) : (
          <div className="empty">
            <Film size={40} />
            <p>{t("选择任务查看详情", "Select a task to see its details")}</p>
          </div>
        )}
      </section>
    </div>
  );
}
