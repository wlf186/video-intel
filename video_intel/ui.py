import html

import gradio as gr

from .service import INPUT, MAX_UPLOAD
from .workflows import DEFAULT_PRESET

MODES = {"t2v": "文字生成", "i2v": "首帧图生视频", "r2v": "外观参考生成"}
STATUSES = {
    "queued": "排队中",
    "running": "生成中",
    "succeeded": "完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def build_ui(service):
    def history():
        return [
            [
                x["id"],
                x["created_at"][5:16].replace("T", " "),
                MODES[x["mode"]],
                STATUSES[x["status"]],
                x["prompt"][:45],
            ]
            for x in service.list()
        ]

    def submit(prompt, mode, preset, seed, soundscape, files):
        try:
            contents = []
            for path in files or []:
                with open(path, "rb") as source:
                    contents.append(source.read(MAX_UPLOAD + 1))
            job = service.submit(
                prompt,
                mode,
                preset,
                -1 if seed is None else int(seed),
                soundscape,
                contents,
            )
        except ValueError as error:
            raise gr.Error(str(error)) from error
        return (
            job["id"],
            "任务已加入本地队列。",
            None,
            "",
            history(),
            [str(INPUT / x) for x in job["images"]],
        )

    def poll(job_id, rendered):
        rows = history()
        if not job_id:
            state = service.health()
            if not all(state["models"].values()):
                message = "本地模型准备中，下载和校验完成后自动开始生成。"
            elif not state["backend"]:
                message = "正在连接本地推理引擎，连接后自动开始生成。"
            else:
                message = "本地引擎就绪，可以提交任务。"
            return message, gr.skip(), rendered, rows
        try:
            job = service.get(job_id)
        except KeyError:
            return "任务不存在。", gr.skip(), rendered, rows
        elapsed = job["metrics"].get("elapsed_seconds", 0)
        text = (
            f"**{STATUSES[job['status']]}** · {job['stage']}\n\n"
            f"{job['width']} × {job['height']} · 约 5.17 秒 · 24fps · 种子 `{job['seed']}`\n\n"
            f"生成进度 {job['progress']:.0f}% · 已用时 {elapsed:.0f} 秒"
        )
        if job["error"]:
            text += "\n\n" + html.escape(job["error"])
        if job["status"] == "succeeded":
            text += f"\n\n[下载 MP4](/api/jobs/{job_id}/video?download=true) · [查看生成参数](/api/jobs/{job_id})"
        if job["status"] == "succeeded":
            output = job["video_path"] if rendered != job_id else gr.skip()
            return text, output, job_id, rows
        return text, None, "", rows

    def cancel(job_id):
        if not job_id:
            return "请先提交任务或从历史记录中选择任务。"
        job = service.cancel(job_id)
        if job["status"] == "cancelled":
            return "任务已取消。"
        if job["status"] in {"succeeded", "failed"}:
            return "任务已经结束。"
        return "已请求取消；正在计算的步骤结束后会释放资源。"

    def select_history(event: gr.SelectData):
        job_id = event.row_value[0]
        job = service.get(job_id)
        return job_id, [str(INPUT / x) for x in job["images"]]

    def load_latest():
        for job in service.list():
            if job["status"] == "succeeded":
                return job["id"], [str(INPUT / x) for x in job["images"]]
        return "", []

    def change_mode(mode):
        return gr.update(visible=mode != "t2v", value=None)

    with gr.Blocks(title="Video Intel · 本地视频生成", analytics_enabled=False) as demo:
        gr.Markdown(
            "# Video Intel\n### MiniMax H3 · 本地音画生成\n用文字构想一个镜头，或附上图片。画面与声音在这台机器上生成。"
        )
        rendered = gr.State("")
        with gr.Row():
            with gr.Column(scale=5):
                mode = gr.Radio(
                    [(v, k) for k, v in MODES.items()], value="t2v", label="生成方式"
                )
                prompt = gr.Textbox(
                    label="画面描述",
                    lines=7,
                    placeholder="描述主体、场景、动作和镜头运动。参考模式可使用 <Subject 1> 指代第一张图的主体。",
                )
                files = gr.File(
                    label="附图 · PNG / JPEG / WebP，每张不超过 15MB",
                    file_count="multiple",
                    file_types=[".png", ".jpg", ".jpeg", ".webp"],
                    type="filepath",
                    visible=False,
                )
                soundscape = gr.Textbox(
                    label="声音描述",
                    lines=2,
                    placeholder="例如：雨落在屋檐上，远处有轻微鸟鸣，没有对白和音乐。",
                )
                with gr.Row():
                    preset = gr.Dropdown(
                        [
                            ("预览 · 608 × 352", "preview"),
                            ("标准 · 864 × 480", "standard"),
                            ("原生 · 1344 × 768", "native"),
                        ],
                        value=DEFAULT_PRESET,
                        label="画质",
                        min_width=220,
                    )
                    seed = gr.Number(
                        value=-1,
                        precision=0,
                        minimum=-1,
                        maximum=4294967295,
                        label="随机种子（-1 为随机）",
                        min_width=200,
                    )
                gr.Markdown(
                    "每段约 **5 秒**，含立体声音轨。**本机生成参考耗时：预览 1–2 分钟，标准约 4 分钟，原生约 16–18 分钟。** 首帧图片按目标画布居中裁剪，提交后可在右侧查看。"
                )
                generate = gr.Button("生成视频", variant="primary")
                gr.Examples(
                    [
                        [
                            "A cinematic close-up of a small red toy car rolling slowly across a wet stone path in a lush garden. Raindrops ripple in shallow puddles. The camera tracks gently alongside the car. Soft overcast light, realistic textures, a single continuous shot.",
                            "Gentle rainfall, water drops hitting stone, and a faint rolling sound. No music or dialogue.",
                        ],
                        [
                            "清晨，一只小鸟停在花园的木栏杆上，轻轻转头，然后振翅飞向树梢。镜头缓慢跟随，温暖的阳光穿过叶片，写实电影风格，单个连续镜头。",
                            "清晰的鸟鸣、轻微振翅声和树叶沙沙声，没有音乐和对白。",
                        ],
                    ],
                    inputs=[prompt, soundscape],
                    label="试试这些描述",
                )
            with gr.Column(scale=5):
                video = gr.Video(label="生成结果", interactive=False, autoplay=False)
                status = gr.Markdown("正在连接本地引擎…")
                job_id = gr.Textbox(label="任务 ID", interactive=False)
                cancel_button = gr.Button("取消当前任务")
                gallery = gr.Gallery(
                    label="本次采用的图片",
                    columns=3,
                    height=200,
                    interactive=False,
                    object_fit="contain",
                )
        gr.Markdown("## 最近任务\n点击一行查看结果。记录和文件保存在本机。")
        table = gr.Dataframe(
            headers=["任务 ID", "UTC 时间", "方式", "状态", "描述"],
            datatype=["str"] * 5,
            interactive=False,
            wrap=True,
        )
        gr.Markdown("[API 文档](/docs) · [服务状态](/api/health)")
        timer = gr.Timer(2)
        generate.click(
            submit,
            inputs=[prompt, mode, preset, seed, soundscape, files],
            outputs=[job_id, status, video, rendered, table, gallery],
            api_name=False,
        )
        timer.tick(
            poll,
            inputs=[job_id, rendered],
            outputs=[status, video, rendered, table],
            api_name=False,
            show_progress="hidden",
        )
        cancel_button.click(cancel, inputs=[job_id], outputs=[status], api_name=False)
        table.select(select_history, outputs=[job_id, gallery], api_name=False)
        mode.change(change_mode, inputs=[mode], outputs=[files], api_name=False)
        demo.load(load_latest, outputs=[job_id, gallery], api_name=False)
    return demo
