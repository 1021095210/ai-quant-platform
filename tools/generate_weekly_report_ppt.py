from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


ROOT = Path("/workspace/ai-quant-platform")
REPORT_DIR = ROOT / "产品设计" / "复盘总结"
ASSET_DIR = REPORT_DIR / "assets" / "weekly-2026-04-03"
OUTPUT = REPORT_DIR / "AI量化交易平台_本周工作汇报_2026-04-03.pptx"

TITLE_COLOR = RGBColor(15, 23, 42)
TEXT_COLOR = RGBColor(51, 65, 85)
ACCENT = RGBColor(14, 116, 144)
ACCENT_2 = RGBColor(16, 185, 129)
BG = RGBColor(246, 248, 252)
PANEL = RGBColor(255, 255, 255)
MUTED = RGBColor(100, 116, 139)


def add_bg(slide):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG


def add_title(slide, title: str, subtitle: str | None = None) -> None:
    title_box = slide.shapes.add_textbox(Inches(0.55), Inches(0.35), Inches(12.0), Inches(0.8))
    frame = title_box.text_frame
    p = frame.paragraphs[0]
    run = p.add_run()
    run.text = title
    run.font.name = "Microsoft YaHei"
    run.font.size = Pt(24)
    run.font.bold = True
    run.font.color.rgb = TITLE_COLOR
    if subtitle:
        sub_box = slide.shapes.add_textbox(Inches(0.58), Inches(0.98), Inches(11.8), Inches(0.45))
        sub = sub_box.text_frame.paragraphs[0]
        r = sub.add_run()
        r.text = subtitle
        r.font.name = "Microsoft YaHei"
        r.font.size = Pt(10.5)
        r.font.color.rgb = MUTED


def add_panel(slide, left, top, width, height, title=None):
    shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = PANEL
    shape.line.color.rgb = RGBColor(226, 232, 240)
    shape.line.width = Pt(1.2)
    if title:
        box = slide.shapes.add_textbox(left + Inches(0.18), top + Inches(0.12), width - Inches(0.3), Inches(0.28))
        p = box.text_frame.paragraphs[0]
        r = p.add_run()
        r.text = title
        r.font.name = "Microsoft YaHei"
        r.font.size = Pt(11.5)
        r.font.bold = True
        r.font.color.rgb = ACCENT
    return shape


def add_bullets(slide, items: list[str], left=0.85, top=1.45, width=11.2, height=5.5, font_size=17):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    frame = box.text_frame
    frame.word_wrap = True
    for idx, item in enumerate(items):
        p = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
        p.text = item
        p.level = 0
        p.space_after = Pt(8)
        p.font.name = "Microsoft YaHei"
        p.font.size = Pt(font_size)
        p.font.color.rgb = TEXT_COLOR
        p.bullet = True


def add_kpi_row(slide, metrics: list[tuple[str, str]]):
    left = 0.6
    top = 1.5
    width = 3.0
    gap = 0.18
    for idx, (label, value) in enumerate(metrics):
        x = Inches(left + idx * (width + gap))
        add_panel(slide, x, Inches(top), Inches(width), Inches(1.5))
        vbox = slide.shapes.add_textbox(x + Inches(0.18), Inches(top + 0.25), Inches(width - 0.3), Inches(0.52))
        vp = vbox.text_frame.paragraphs[0]
        vr = vp.add_run()
        vr.text = value
        vr.font.name = "Microsoft YaHei"
        vr.font.size = Pt(22)
        vr.font.bold = True
        vr.font.color.rgb = ACCENT

        lbox = slide.shapes.add_textbox(x + Inches(0.18), Inches(top + 0.88), Inches(width - 0.3), Inches(0.35))
        lp = lbox.text_frame.paragraphs[0]
        lr = lp.add_run()
        lr.text = label
        lr.font.name = "Microsoft YaHei"
        lr.font.size = Pt(10.5)
        lr.font.color.rgb = MUTED


def add_image_grid(slide, images: list[tuple[str, str]], title: str, subtitle: str):
    add_title(slide, title, subtitle)
    positions = [
        (0.55, 1.35),
        (6.65, 1.35),
        (0.55, 4.1),
        (6.65, 4.1),
    ]
    for (name, caption), (x, y) in zip(images, positions):
        path = ASSET_DIR / name
        add_panel(slide, Inches(x), Inches(y), Inches(5.7), Inches(2.5))
        slide.shapes.add_picture(str(path), Inches(x + 0.08), Inches(y + 0.08), width=Inches(5.54), height=Inches(1.9))
        cbox = slide.shapes.add_textbox(Inches(x + 0.12), Inches(y + 2.03), Inches(5.45), Inches(0.34))
        p = cbox.text_frame.paragraphs[0]
        r = p.add_run()
        r.text = caption
        r.font.name = "Microsoft YaHei"
        r.font.size = Pt(10.5)
        r.font.bold = True
        r.font.color.rgb = TITLE_COLOR


def add_two_column(slide, title: str, left_title: str, left_items: list[str], right_title: str, right_items: list[str]):
    add_title(slide, title)
    add_panel(slide, Inches(0.55), Inches(1.35), Inches(5.8), Inches(5.8), left_title)
    add_panel(slide, Inches(6.65), Inches(1.35), Inches(5.8), Inches(5.8), right_title)
    add_bullets(slide, left_items, left=0.85, top=1.8, width=5.1, height=5.0, font_size=14)
    add_bullets(slide, right_items, left=6.95, top=1.8, width=5.1, height=5.0, font_size=14)


def add_cover(slide):
    add_bg(slide)
    band = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, 0, 0, Inches(13.333), Inches(1.3))
    band.fill.solid()
    band.fill.fore_color.rgb = RGBColor(15, 23, 42)
    band.line.fill.background()

    title = slide.shapes.add_textbox(Inches(0.75), Inches(1.6), Inches(11.8), Inches(1.1))
    p = title.text_frame.paragraphs[0]
    r = p.add_run()
    r.text = "AI量化交易平台本周工作汇报"
    r.font.name = "Microsoft YaHei"
    r.font.size = Pt(28)
    r.font.bold = True
    r.font.color.rgb = TITLE_COLOR

    sub = slide.shapes.add_textbox(Inches(0.78), Inches(2.55), Inches(10.6), Inches(0.6))
    sp = sub.text_frame.paragraphs[0]
    sr = sp.add_run()
    sr.text = "从新环境恢复到可运行平台的完整推进 | 2026-03-30 至 2026-04-03"
    sr.font.name = "Microsoft YaHei"
    sr.font.size = Pt(14)
    sr.font.color.rgb = MUTED

    add_panel(slide, Inches(0.75), Inches(3.35), Inches(5.4), Inches(2.55), "本周结论")
    add_bullets(
        slide,
        [
            "已完成从私有仓库恢复、环境搭建到平台运行验证的完整闭环。",
            "用户端、回测端、复盘端、导师端、助手端、管理员端均已落地到代码与页面。",
            "测试、预检、接力文档、模块文档与常见问题机制已收口。",
        ],
        left=1.0,
        top=3.75,
        width=4.9,
        height=1.9,
        font_size=14,
    )
    slide.shapes.add_picture(str(ASSET_DIR / "workspace.png"), Inches(6.45), Inches(1.55), width=Inches(6.1), height=Inches(4.45))


def add_title_bullet_slide(prs, title, subtitle, bullets, metrics=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)
    add_title(slide, title, subtitle)
    if metrics:
        add_kpi_row(slide, metrics)
        add_bullets(slide, bullets, left=0.85, top=3.1, width=11.3, height=3.5, font_size=15)
    else:
        add_bullets(slide, bullets)
    return slide


def build_presentation() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    cover = prs.slides.add_slide(prs.slide_layouts[6])
    add_cover(cover)

    add_title_bullet_slide(
        prs,
        "本周目标与结果",
        "本周已经完成从环境恢复到平台主链路跑通的收口",
        [
            "恢复 GitHub 私有仓库，完成 `.venv`、依赖安装、配置补齐、测试验证与服务启动。",
            "把冻结稿中的平台契约、数据库边界、任务模型、数据快照等设计落到实际代码。",
            "逐步完成认证、用户工作台、策略工坊、指标设置、规则模块、回测中心、交易复盘、金融导师、金融助手、管理员后台。",
            "形成可接力开发的主文档、模块文档、工作简报和常见问题机制。",
        ],
        metrics=[("汇报周期", "5 天"), ("当前全量测试", "134"), ("主要页面", "12+"), ("研究工作流", "6")],
    )

    add_title_bullet_slide(
        prs,
        "从零恢复到平台跑通的完整流程",
        "本周不是单点修补，而是按顺序把平台从空环境恢复到可持续开发状态",
        [
            "恢复仓库与访问凭据：解决私有仓库拉取、`gh` 认证与 GitHub 持久同步问题。",
            "环境搭建：创建虚拟环境、安装 API 依赖、准备 `.env`、启动本地服务并校验 `healthz`。",
            "平台底座：统一 API envelope、错误码、`request_id`、`config_revision` 和任务状态机。",
            "业务落地：完成用户体系、策略 / 回测 / 复盘 / 教学 / 研究协作 / 管理后台的逐步实现。",
            "流程收口：补齐测试、外部访问、部署基线、发布前预检和接力规则。",
        ],
    )

    add_two_column(
        prs.slides.add_slide(prs.slide_layouts[6]),
        "阶段性里程碑",
        "2026-04-01",
        [
            "完成仓库恢复、环境搭建、测试验证、服务启动。",
            "完成平台公共契约、数据库边界和 `data_snapshot_ref` 第一阶段。",
            "完成认证、用户工作台、管理员后台与多市场策略语义基线。",
        ],
        "2026-04-02 ~ 2026-04-03",
        [
            "完成回测配置对象化、可信度说明、执行规则和回测对比层。",
            "完成交易复盘多源导入、长文字识别、截图 OCR 第一阶段。",
            "完成金融导师 LLM 接入、金融助手第一阶段、应用日志后台与模块化接力文档。",
        ],
    )
    add_bg(prs.slides[-1])

    add_two_column(
        prs.slides.add_slide(prs.slide_layouts[6]),
        "当前平台能力总览",
        "用户侧能力",
        [
            "首页、登录 / 注册、用户工作台",
            "策略工坊、指标设置、规则模块",
            "回测中心、交易复盘",
            "金融导师、金融助手",
        ],
        "平台侧能力",
        [
            "管理员工作台、用户管理、安全事件、应用日志",
            "API envelope、错误码、`request_id`、`config_revision`",
            "`data_snapshot_ref`、发布前预检、Docker / Compose 基线",
            "主接力文档 + 模块文档 + 常见问题机制",
        ],
    )
    add_bg(prs.slides[-1])

    add_two_column(
        prs.slides.add_slide(prs.slide_layouts[6]),
        "核心架构与技术选型",
        "技术栈",
        [
            "前端：FastAPI 托管的 HTML + Vanilla JavaScript + CSS",
            "后端：Python 3.11 + FastAPI + Uvicorn + SQLAlchemy",
            "数据层：业务 SQLite / PostgreSQL，市场缓存 SQLite，Redis / MinIO 基线",
            "AI：金融导师 + 金融助手，共用 OpenAI 兼容 LLM 链路",
        ],
        "平台架构结论",
        [
            "选择轻量多页面架构，保证快速交付与低环境复杂度。",
            "先打稳业务契约、数据快照、回测配置与权限边界，再迭代更深研究能力。",
            "部署上已具备容器化和外部依赖联调基础，可继续迈向正式公网发布。",
        ],
    )
    add_bg(prs.slides[-1])

    add_two_column(
        prs.slides.add_slide(prs.slide_layouts[6]),
        "数据流与业务流",
        "数据流",
        [
            "策略描述 -> DSL / Python 策略骨架 -> 保存项目版本",
            "发起回测 -> 冻结 backtest_config / config_revision -> 绑定 data_snapshot_ref -> 返回结果与对比",
            "导入交割单 / 截图 / 手动录入 -> 结构化交易记录 -> 复盘总结与建议",
        ],
        "业务流",
        [
            "首页进入 -> 登录 / 注册 -> 用户工作台",
            "策略工坊生成策略 -> 保存项目 -> 去回测中心运行回测",
            "交易复盘导入真实交易 -> 生成复盘结果 -> 追问金融导师或进入金融助手继续研究",
        ],
    )
    add_bg(prs.slides[-1])

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)
    add_image_grid(
        slide,
        [
            ("home.png", "首页：平台公开入口"),
            ("workspace.png", "用户工作台：研究中枢"),
            ("strategy.png", "策略工坊：多市场 / 多周期策略生成"),
            ("backtests.png", "回测中心：配置、曲线、历史、对比"),
        ],
        "页面成果展示一",
        "平台已形成从公开入口到研究主链路的完整页面结构",
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)
    add_image_grid(
        slide,
        [
            ("replay.png", "交易复盘：多源导入与智能识别"),
            ("mentor.png", "金融导师：教学、解释与追问"),
            ("assistant.png", "金融助手：机构研究协作台"),
            ("admin.png", "管理后台：用户、安全与日志治理"),
        ],
        "页面成果展示二",
        "本周新增的复盘、导师、助手与后台能力",
    )

    add_title_bullet_slide(
        prs,
        "本周重点能力落地",
        "本周不是单一功能开发，而是形成了六条主线能力",
        [
            "回测主线：回测配置对象化、可信度说明、结算规则与市场约束、回测对比层。",
            "复盘主线：CSV / 截图 / 手动录入、多源导入、长文字规则识别、OCR 第一阶段。",
            "教学主线：金融导师支持首次提问与继续追问，且已接入真实 LLM 回答。",
            "研究主线：金融助手第一阶段支持市场地图、公司深研、多空辩论、风险委员会等工作流。",
            "治理主线：管理员后台可查看用户、安全、任务、应用日志与用户报错。",
        ],
    )

    add_title_bullet_slide(
        prs,
        "测试、验证与部署收口",
        "本周已经形成真实可运行与可发布前检查的基线",
        [
            "全量单测通过：`134` 个测试 `OK`。",
            "已覆盖静态资源语法检查、关键页面浏览器验证、外部访问验证、部署预检与依赖联调。",
            "已打通 PostgreSQL / Redis / MinIO 外部依赖联调。",
            "已形成 Dockerfile、Compose 模板、生产 Cookie 与环境配置基线。",
        ],
        metrics=[("全量测试", "134 OK"), ("健康检查", "通过"), ("外部依赖", "3 类"), ("部署文档", "已收口")],
    )

    add_title_bullet_slide(
        prs,
        "接力机制与过程治理",
        "这周另一项关键成果，是把‘能继续开发’本身变成平台流程的一部分",
        [
            "主接力文档继续保留为单文件入口，新 Agent 只读一份文件也能恢复项目。",
            "具体功能状态拆到模块文件，后续 Agent 能直接定位到对应模块继续开发。",
            "常见问题文件已沉淀高频问题，减少反复返工和重复指出同类缺陷。",
            "每轮开发结束都同步 GitHub、接力文档、模块文档和工作简报。",
        ],
    )

    add_two_column(
        prs.slides.add_slide(prs.slide_layouts[6]),
        "本周问题与处理方式",
        "已解决的问题",
        [
            "私有仓库认证与 `gh` 环境恢复。",
            "普通 `git push` 不稳定，改为 GitHub API fallback 保证远端同步。",
            "临时外链频繁失效，改成‘验证后再发链接’。",
            "前端脚本缓存与语法错误，增加版本号与静态资源检查。",
            "导师回答机械重复，已接入真实 LLM 回答链路。",
        ],
        "当前仍需继续关注",
        [
            "外部访问仍主要依赖临时隧道，不是正式长期域名。",
            "多市场数据能力仍以 A 股日线为主，需要继续扩展。",
            "OCR 与长文字识别还需增强更多券商版式与更多市场语义。",
            "金融助手仍在第一阶段，尚未深度绑定当前策略、回测、复盘上下文。",
        ],
    )
    add_bg(prs.slides[-1])

    add_title_bullet_slide(
        prs,
        "下周建议推进重点",
        "当前阶段重点已经不是从零搭建，而是把已有能力做深、做稳、做成正式产品",
        [
            "金融助手第二阶段：接入当前页面上下文，输出正式研究纪要 / 投委会材料。",
            "交易复盘继续增强：OCR 识别买卖价格、手续费、数量；长文字规则支持更多市场与更多卖出条件。",
            "正式部署准备：固定公网入口、正式域名与 HTTPS、生产运维与监控。",
            "继续按真人用户习惯优化页面节奏、按钮引导和模块说明。",
        ],
    )

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_bg(slide)
    add_panel(slide, Inches(0.7), Inches(1.3), Inches(11.9), Inches(4.8))
    title_box = slide.shapes.add_textbox(Inches(1.0), Inches(1.75), Inches(11.0), Inches(0.6))
    p = title_box.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "本周已完成从“设计稿 + 空环境”到“可运行、可测试、可接力平台”的跨越"
    r.font.name = "Microsoft YaHei"
    r.font.size = Pt(20)
    r.font.bold = True
    r.font.color.rgb = TITLE_COLOR
    add_bullets(
        slide,
        [
            "平台已形成研究、回测、复盘、教学、研究协作、治理后台六条主线。",
            "开发流程已同时具备代码、测试、部署基线、文档接力与问题治理能力。",
            "下一阶段重点是正式发布能力与更深的研究智能化，而不是重新从零搭建。",
        ],
        left=1.25,
        top=2.55,
        width=10.8,
        height=2.2,
        font_size=16,
    )
    foot = slide.shapes.add_textbox(Inches(0.85), Inches(6.45), Inches(11.8), Inches(0.3))
    fp = foot.text_frame.paragraphs[0]
    fp.alignment = PP_ALIGN.RIGHT
    fr = fp.add_run()
    fr.text = "AI量化交易平台周报 | 2026-04-03"
    fr.font.name = "Microsoft YaHei"
    fr.font.size = Pt(9.5)
    fr.font.color.rgb = MUTED

    prs.save(str(OUTPUT))
    return OUTPUT


if __name__ == "__main__":
    out = build_presentation()
    print(out)
