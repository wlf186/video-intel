import { useEffect, useRef, useState } from "react";
import { api, message, useText } from "./lib";
import { promptFields, type Draft } from "./promptState";
import type { PromptPreview } from "./types";

export function PromptEditor({
  draft,
  change,
  imageCount,
  english,
}: {
  draft: Draft;
  change: (values: Partial<Draft>) => void;
  imageCount: number;
  english: boolean;
}) {
  const t = useText();
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<{
    key: string;
    data: PromptPreview;
  } | null>(null);
  const [failure, setFailure] = useState<{ key: string; text: string } | null>(
    null,
  );
  const [copied, setCopied] = useState("");
  const mainRef = useRef<HTMLTextAreaElement>(null);
  const raw = draft.prompt_format === "raw";
  const invalidMusic =
    !raw && draft.music_mode === "custom" && !draft.music.trim();
  const previewIssue = invalidMusic
    ? t("请填写自定义配乐描述。", "Enter a custom score description.")
    : !(raw ? draft.raw_prompt : draft.prompt).trim()
      ? t("请先填写描述。", "Enter a description first.")
      : draft.mode !== "t2v" && !imageCount && !draft.source_job_id
        ? t(
            "请先上传此模式需要的图片。",
            "Upload the images required for this mode first.",
          )
        : "";
  const request = JSON.stringify({
    ...promptFields(draft),
    image_count: draft.source_job_id ? 0 : imageCount,
    source_job_id: draft.source_job_id,
  });
  const preview = result?.key === request ? result.data : null;
  const error = failure?.key === request ? failure.text : "";
  const active = open || raw;
  useEffect(() => {
    if (!active || previewIssue) return;
    setCopied("");
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setResult(null);
      setFailure(null);
      api<PromptPreview>("/api/prompts/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: request,
        signal: controller.signal,
      })
        .then((data) => {
          if (!controller.signal.aborted) setResult({ key: request, data });
        })
        .catch((err) => {
          if (!controller.signal.aborted) {
            setResult(null);
            setFailure({ key: request, text: message(err, english) });
          }
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [active, request, previewIssue, english]);

  function insertSubject(index: number) {
    const input = mainRef.current;
    const start = input?.selectionStart ?? draft.prompt.length;
    const end = input?.selectionEnd ?? start;
    const tag = `<Subject ${index + 1}>`;
    change({
      prompt: draft.prompt.slice(0, start) + tag + draft.prompt.slice(end),
    });
    requestAnimationFrame(() => {
      input?.focus();
      input?.setSelectionRange(start + tag.length, start + tag.length);
    });
  }

  async function copy() {
    if (!preview) return;
    try {
      await navigator.clipboard.writeText(preview.effective_prompt);
      setCopied(t("已复制", "Copied"));
    } catch {
      setCopied(
        t(
          "请在预览框中选择文本并复制。",
          "Select the preview text to copy it manually.",
        ),
      );
    }
  }

  return (
    <section
      className="prompt-editor"
      aria-label={t("提示词编辑", "Prompt editor")}
    >
      {raw ? (
        <>
          <div className="prompt-toolbar">
            <strong>{t("完整提示词编辑", "Complete prompt editor")}</strong>
            <button
              type="button"
              onClick={() => change({ prompt_format: "guided" })}
            >
              {t("返回描述表单", "Return to description form")}
            </button>
          </div>
          <p className="muted prompt-help">
            {t(
              "按原文提交。分项声音、配乐和主体说明不参与提交；返回表单可继续编辑之前的描述，完整提示词草稿会保留。",
              "Submitted unchanged. Separate sound, music and subject settings are not used. Returning restores the previous form; this complete prompt draft is retained.",
            )}
          </p>
          <label className="field">
            <span>
              {t("完整提示词", "Complete prompt")}
              <small>{draft.raw_prompt.length} / 40000</small>
            </span>
            <textarea
              required
              rows={12}
              maxLength={40000}
              value={draft.raw_prompt}
              onChange={(event) =>
                change({
                  raw_prompt: event.target.value,
                  raw_initialized: true,
                })
              }
            />
          </label>
        </>
      ) : (
        <>
          <label className="field">
            <span>
              {t("画面、动作与对白", "Scene, action and dialogue")}
              <small>{draft.prompt.length} / 16000</small>
            </span>
            <textarea
              ref={mainRef}
              required
              maxLength={16000}
              rows={6}
              value={draft.prompt}
              onChange={(event) => change({ prompt: event.target.value })}
              placeholder={t(
                "描述镜头、动作、对白，以及与动作同步的声音…",
                "Describe shots, action, dialogue and synchronized sounds…",
              )}
            />
          </label>
          <p className="muted prompt-help">
            {t(
              "对白、歌唱和现场音乐跟随动作写在这里。背景配乐在声音设置中填写。仅本地整理格式，不自动翻译；推荐英文正文，台词及画面文字保留原语言。",
              "Keep dialogue, singing and in-scene music with the action. Set background score below. Local formatting only, without translation; English prose is recommended, preserving dialogue and visible text in their original language.",
            )}
          </p>
          <button
            className="text-button"
            type="button"
            onClick={() =>
              change({ prompt_format: "raw", raw_initialized: true })
            }
          >
            {t("粘贴完整提示词", "Paste a complete prompt")}
          </button>
          {draft.mode === "r2v" && imageCount > 0 && (
            <div className="reference-descriptions">
              {Array.from({ length: imageCount }, (_, index) => (
                <div key={index} className="reference-description">
                  <button
                    type="button"
                    onClick={() => insertSubject(index)}
                    title={t("插入到主描述", "Insert into description")}
                  >
                    {t(`图片 ${index + 1}`, `Image ${index + 1}`)} ·{" "}
                    {`<Subject ${index + 1}>`}
                  </button>
                  <label className="field">
                    <span>
                      {t(
                        `主体 ${index + 1} 说明（可选）`,
                        `Subject ${index + 1} description (optional)`,
                      )}
                    </span>
                    <textarea
                      rows={2}
                      maxLength={1000}
                      value={draft.reference_descriptions[index] || ""}
                      placeholder={t(
                        "例如：人物，保留面容、发型和服装",
                        "E.g. the person; preserve their face, hair and clothing",
                      )}
                      onChange={(event) =>
                        change({
                          reference_descriptions: Array.from(
                            { length: imageCount },
                            (_, i) =>
                              i === index
                                ? event.target.value
                                : draft.reference_descriptions[i] || "",
                          ),
                        })
                      }
                    />
                  </label>
                </div>
              ))}
            </div>
          )}
          <details className="advanced sound-settings">
            <summary>
              {t("声音设置", "Sound settings")}
              <span className="sound-summary">
                {draft.soundscape.trim()
                  ? t("自定义环境声", "Custom ambience")
                  : t("自然环境声", "Natural ambience")}{" "}
                ·{" "}
                {draft.music_mode === "none"
                  ? t("无配乐", "No score")
                  : t("自定义配乐", "Custom score")}
              </span>
            </summary>
            <label className="field">
              <span>
                {t("环境声与动作音效", "Ambience and physical sound effects")}
                <small>{draft.soundscape.length} / 4000</small>
              </span>
              <textarea
                rows={3}
                maxLength={4000}
                value={draft.soundscape}
                onChange={(event) => change({ soundscape: event.target.value })}
                placeholder={t(
                  "例如：轻微风声、篮球落地声、衣物摩擦声。留空使用自然环境声。",
                  "E.g. light wind, basketball bounces and clothing rustle. Leave blank for natural ambience.",
                )}
              />
            </label>
            <label className="field">
              <span>{t("背景配乐", "Background score")}</span>
              <select
                aria-label={t("背景配乐", "Background score")}
                value={draft.music_mode}
                onChange={(event) =>
                  change({
                    music_mode: event.target.value as Draft["music_mode"],
                  })
                }
              >
                <option value="none">{t("无", "None")}</option>
                <option value="custom">{t("自定义", "Custom")}</option>
              </select>
            </label>
            {draft.music_mode === "custom" && (
              <label className="field">
                <span>
                  {t("配乐描述", "Score description")}
                  <small>{draft.music.length} / 4000</small>
                </span>
                <textarea
                  required
                  rows={3}
                  maxLength={4000}
                  value={draft.music}
                  onChange={(event) => change({ music: event.target.value })}
                  placeholder={t(
                    "例如：缓慢、稀疏的钢琴音符，结尾逐渐淡出。",
                    "E.g. sparse piano notes at a slow tempo, fading out at the end.",
                  )}
                />
              </label>
            )}
          </details>
        </>
      )}
      <details
        className="advanced final-prompt"
        open={open}
        onToggle={(event) => {
          setOpen(event.currentTarget.open);
          setCopied("");
        }}
      >
        <summary>{t("最终提示词", "Final prompt")}</summary>
        {previewIssue ? (
          <p className="muted">{previewIssue}</p>
        ) : error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : preview ? (
          <>
            <label className="field">
              <span>{t("实际提交内容", "Content sent to the model")}</span>
              <textarea readOnly rows={10} value={preview.effective_prompt} />
            </label>
            <div className="prompt-toolbar">
              <button type="button" onClick={copy}>
                {t("复制提示词", "Copy prompt")}
              </button>
              {!raw && (
                <button
                  type="button"
                  disabled={
                    !draft.raw_initialized &&
                    preview.effective_prompt.length > 40000
                  }
                  onClick={() =>
                    change({
                      prompt_format: "raw",
                      raw_initialized: true,
                      raw_prompt: draft.raw_initialized
                        ? draft.raw_prompt
                        : preview.effective_prompt,
                    })
                  }
                >
                  {draft.raw_initialized
                    ? t("继续编辑完整提示词", "Resume complete prompt")
                    : t("编辑完整提示词", "Edit complete prompt")}
                </button>
              )}
              {!raw && draft.raw_initialized && (
                <button
                  type="button"
                  disabled={preview.effective_prompt.length > 40000}
                  onClick={() =>
                    change({
                      prompt_format: "raw",
                      raw_initialized: true,
                      raw_prompt: preview.effective_prompt,
                    })
                  }
                >
                  {t(
                    "用当前预览更新完整草稿",
                    "Replace complete draft with preview",
                  )}
                </button>
              )}
            </div>
            {!raw && preview.effective_prompt.length > 40000 && (
              <p className="muted">
                {t(
                  "合并后超过完整编辑的 40000 字符上限，请先缩短描述。",
                  "The combined prompt exceeds the 40000-character editor limit; shorten the descriptions first.",
                )}
              </p>
            )}
            <small className="muted">
              {preview.prompt_template_version} ·{" "}
              {preview.effective_prompt.length} {t("字符", "characters")}
            </small>
            {copied && <p role="status">{copied}</p>}
          </>
        ) : (
          <p role="status">{t("正在整理预览…", "Preparing preview…")}</p>
        )}
      </details>
      {(open || raw) && preview && preview.prompt_warnings.length > 0 && (
        <div className="warning prompt-warnings" role="status">
          {preview.prompt_warnings.map((warning) => (
            <p key={warning}>{message(warning, english)}</p>
          ))}
        </div>
      )}
    </section>
  );
}
