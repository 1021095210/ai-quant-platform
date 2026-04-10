from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping, Sequence


REQUIRED_SECTIONS: Mapping[str, Sequence[str]] = {
    "产品设计/AI量化交易平台_选题说明.md": (
        "# AI 量化交易平台选题说明",
        "## 一句话定义",
        "## MVP 范围",
        "## 演示闭环",
        "## AI 参与点",
    ),
    "产品设计/AI量化交易平台_设计文档.md": (
        "# AI 量化交易平台设计文档",
        "## 策略 DSL 设计",
        "## 数据流转",
        "## 复盘分析逻辑",
        "## 验收标准",
        "## AI 协作记录",
    ),
    "产品设计/AI量化交易平台_验收演示脚本.md": (
        "# AI 量化交易平台验收演示脚本",
        "## 演示目标",
        "## 演示步骤",
        "## 通过标准",
        "## 风险预案",
    ),
    "产品设计/AI量化交易平台_页面与交互设计.md": (
        "# AI 量化交易平台页面与交互设计",
        "## 信息架构",
        "## 页面 2：策略实验室",
        "## 页面 4：交易复盘页",
        "## 关键页面验收标准",
    ),
    "产品设计/AI量化交易平台_API详细设计.md": (
        "# AI 量化交易平台 API 详细设计",
        "### 长任务与异步约定",
        "## 1. 生成策略",
        "## 6. 运行回测",
        "## 11. 执行复盘分析",
        "## 关键前后端联调顺序",
    ),
    "产品设计/AI量化交易平台_数据库设计.sql": (
        "CREATE TABLE users",
        "CREATE TABLE strategy_projects",
        "CREATE TABLE backtest_runs",
        "CREATE TABLE trade_fills",
        "CREATE TABLE replay_analyses",
    ),
    "产品设计/AI量化交易平台_周一提交版.md": (
        "# AI 量化交易平台周一提交版",
        "## 3. 技术选型与理由",
        "### 3.6 平台化目标与工程边界",
        "## 4. 数据流转（重点）",
        "### 4.5 平台化补充：回测可信度与异步约定",
        "## 5. 业务流转（重点）",
        "## 6. 系统模块划分",
        "## 7. 数据模型设计",
        "### 7.6 平台化补充：可追溯性与数据治理",
        "## 9. 环境搭建",
        "### 10.4 AI 可追溯性",
        "## 17. 选题自问清单",
    ),
    "产品设计/AI量化交易平台_环境搭建.md": (
        "# AI 量化交易平台环境搭建说明",
        "## 技术栈选择",
        "## 环境变量",
        "## Docker Compose 设计",
        "## 数据治理与安全边界",
        "## 环境搭建验收标准",
    ),
    "产品设计/AI量化交易平台_常见问题与避免规则.md": (
        "# AI量化交易平台常见问题与避免规则",
        "## 2. 反复出现的常见问题",
        "### 2.1 前端脚本语法或启动错误导致页面一直加载",
        "### 2.5 交易语义与市场制度不一致",
        "## 3. 每轮开发前自检",
        "## 4. 每轮开发后自检",
        "## 6. 后续维护要求",
    ),
    "产品设计/AI量化交易平台_数据模型设计.md": (
        "# AI 量化交易平台数据模型设计",
        "## 核心实体",
        "## 表设计",
        "## 策略 DSL 的存储结构",
        "## 复盘结果的存储结构",
        "## 可追溯性与版本字段",
        "## 数据模型验收标准",
    ),
    "产品设计/AI量化交易平台_架构与流程图.md": (
        "# AI 量化交易平台架构与流程图",
        "## 1. 总体系统架构",
        "## 2. 自然语言生成策略流程",
        "## 4. 交割单复盘流程",
        "## 6. 业务流程图",
    ),
    "产品设计/AI量化交易平台_AI协作设计记录.md": (
        "# AI 量化交易平台 AI 协作设计记录",
        "## 第一轮：产品构思",
        "## 第三轮：深挖数据流与模块",
        "## 第四轮：让 AI 挑战设计",
        "## 本次 AI 协作的结论",
    ),
    "产品设计/AI量化交易平台_页面原型.html": (
        "<title>AI量化交易平台低保真原型</title>",
        "策略实验室",
        "回测结果",
        "交易复盘",
        "AI 复盘建议",
    ),
    "产品设计/AI量化交易平台_群提交版.md": (
        "# 选题 + 设计文档 + 环境搭建",
        "## 技术选型与理由",
        "## 数据流转（重点）",
        "## 业务流转（重点）",
        "## 系统模块划分",
        "## 数据模型设计",
        "## 环境搭建",
        "## 选题自问清单",
    ),
}


def collect_missing_sections(
    base_dir: Path,
    requirements: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, list[str]]:
    required = requirements or REQUIRED_SECTIONS
    missing: dict[str, list[str]] = {}

    for relative_path, sections in required.items():
        file_path = base_dir / relative_path
        if not file_path.exists():
            missing[relative_path] = ["<missing file>"]
            continue

        content = file_path.read_text(encoding="utf-8")
        absent_sections = [section for section in sections if section not in content]
        if absent_sections:
            missing[relative_path] = absent_sections

    return missing


def format_report(missing: Mapping[str, Sequence[str]]) -> str:
    if not missing:
        return "All required product design documents are present."

    lines = ["Missing required files or sections:"]
    for relative_path, sections in sorted(missing.items()):
        lines.append(f"- {relative_path}")
        for section in sections:
            lines.append(f"  - {section}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the generated product design planning documents."
    )
    parser.add_argument(
        "--base-dir",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Workspace root that contains the 产品设计 directory.",
    )
    args = parser.parse_args()

    missing = collect_missing_sections(args.base_dir)
    report = format_report(missing)
    print(report)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
