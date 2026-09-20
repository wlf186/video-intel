"""Local H3 prompt formatting. No translation or semantic rewriting is performed."""

import re

TEMPLATE_VERSION = "h3-structured-v1"
FIRST_FRAME = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced."
)
BASE_FIELDS = (
    "integrated_multimodal_description",
    "overall_soundscape",
    "non_diegetic_music",
)
REFERENCE_FIELDS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
HEADINGS = re.compile(
    r"^[ \t]*(" + "|".join(dict.fromkeys(BASE_FIELDS + REFERENCE_FIELDS)) + r"):",
    re.MULTILINE,
)


def compile_prompt(
    prompt,
    soundscape="",
    mode="t2v",
    count=0,
    *,
    prompt_format="auto",
    music="",
    reference_descriptions=(),
):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(
            "请输入 1–16000 字符的描述 / Prompt must contain 1–16000 characters"
        )
    if mode not in {"t2v", "i2v", "r2v"}:
        raise ValueError("不支持的生成模式 / Invalid generation mode")
    if prompt_format not in {"auto", "guided", "raw"}:
        raise ValueError("提示词格式无效 / Invalid prompt format")
    if type(count) is not int or not (
        (mode == "t2v" and count == 0)
        or (mode == "i2v" and count == 1)
        or (mode == "r2v" and 1 <= count <= 3)
    ):
        raise ValueError(
            "图片数量不正确：首帧 1 张，参考图 1–3 张 / Invalid image count"
        )
    for value in (soundscape, music):
        if not isinstance(value, str) or len(value) > 4000:
            raise ValueError(
                "声音或配乐描述不能超过 4000 字符 / Sound or music exceeds 4000 characters"
            )
    if (
        not isinstance(reference_descriptions, (list, tuple))
        or any(
            not isinstance(value, str) or len(value) > 1000
            for value in reference_descriptions
        )
        or len(reference_descriptions) > 3
    ):
        raise ValueError(
            "主体说明最多 3 项，每项最多 1000 字符 / Up to 3 subject descriptions, 1000 characters each"
        )

    headings = [match.group(1) for match in HEADINGS.finditer(prompt)]
    resolved = prompt_format
    if resolved == "auto":
        resolved = (
            "raw"
            if any(
                name in headings
                for name in (
                    "detailed_description",
                    "integrated_multimodal_description",
                )
            )
            else "guided"
        )
    limit = 40000 if resolved == "raw" else 16000
    if len(prompt) > limit:
        raise ValueError(
            f"提示词不能超过 {limit} 字符 / Prompt exceeds {limit} characters"
        )
    warnings = []
    if resolved == "raw":
        if soundscape.strip() or music.strip() or any(reference_descriptions):
            warnings.append(
                "完整提示词优先，分项声音、配乐和主体说明未合并 / Complete prompt takes precedence; separate sound, music and subject descriptions were not merged"
            )
        required = REFERENCE_FIELDS if mode == "r2v" else BASE_FIELDS
        missing = [field for field in required if field not in headings]
        if missing:
            warnings.append(
                "缺少推荐段落："
                + ", ".join(missing)
                + " / Missing recommended sections: "
                + ", ".join(missing)
            )
        if [name for name in headings if name in required] != list(required):
            warnings.append(
                "段落顺序、重复项或模式与推荐格式不一致 / Section order, duplicates or mode differ from the recommended format"
            )
        other_main = (
            "integrated_multimodal_description"
            if mode == "r2v"
            else "detailed_description"
        )
        if other_main in headings:
            warnings.append(
                "主描述段落与当前生成模式不匹配 / Main description section does not match the generation mode"
            )
        if mode == "i2v" and FIRST_FRAME not in prompt:
            warnings.append(
                "请确认完整提示词包含首帧在 0 秒的对齐说明 / Check that the complete prompt aligns the first frame at 0 seconds"
            )
        effective = prompt
    else:
        if headings:
            warnings.append(
                "主描述包含结构化段落，建议改用完整提示词编辑 / Structured sections detected; consider the complete prompt editor"
            )
        if reference_descriptions and (
            mode != "r2v" or len(reference_descriptions) != count
        ):
            raise ValueError(
                "主体说明必须按参考图数量和顺序提供 / Subject descriptions must match reference image count and order"
            )
        body = prompt.strip()
        if not re.search(r"\[Shot\s+1\]", body):
            body = "[Shot 1] " + body
        sound = (
            soundscape.strip()
            or "Natural ambient sound and physical sound effects synchronized with the described actions."
        )
        score = music.strip() or "N/A"
        if mode == "r2v":
            descriptions = reference_descriptions or [""] * count
            definitions = []
            retention = []
            for index, description in enumerate(descriptions, 1):
                subject = f"<Subject {index}>"
                definitions.append(
                    f"{subject} is the main visible subject in <Picture {index}>. "
                    + (description.strip() or "Preserve its distinctive appearance.")
                )
                retention.append(
                    f"{subject}: fully_preserved - Preserve the referenced identity and defining visual features "
                    "while following the actions and setting in detailed_description."
                )
            subjects = ", ".join(f"<Subject {i}>" for i in range(1, count + 1))
            fields = {
                "subject_definitions": "\n".join(definitions),
                "summary": f"[reference generation] Generate the described audiovisual scene using {subjects} from the reference images.",
                "retention_analysis": "\n".join(retention),
                "detailed_description": body,
                "overall_soundscape": sound,
                "non_diegetic_music": score,
            }
        else:
            fields = dict(zip(BASE_FIELDS, (body, sound, score)))
        effective = "\n\n".join(f"{key}:\n{value}" for key, value in fields.items())
        if mode == "i2v":
            effective = FIRST_FRAME + "\n\n" + effective

    invalid_pictures = sorted(
        {int(n) for n in re.findall(r"<Picture (\d+)>", effective)}
        - set(range(1, count + 1))
    )
    if invalid_pictures:
        warnings.append(
            "引用了未提供的图片："
            + ", ".join(map(str, invalid_pictures))
            + " / References unavailable pictures: "
            + ", ".join(map(str, invalid_pictures))
        )
    if mode == "r2v":
        parts = re.split(r"^[ \t]*summary:", effective, maxsplit=1, flags=re.MULTILINE)
        defined = (
            set(re.findall(r"<Subject (\d+)>", parts[0]))
            if "subject_definitions" in effective
            else set()
        )
        used = set(re.findall(r"<Subject (\d+)>", effective))
        if used - defined:
            warnings.append(
                "部分主体没有定义："
                + ", ".join(sorted(used - defined))
                + " / Some subjects are undefined: "
                + ", ".join(sorted(used - defined))
            )
    return {
        "effective_prompt": effective,
        "prompt_format": resolved,
        "prompt_template_version": TEMPLATE_VERSION,
        "prompt_warnings": warnings,
    }
