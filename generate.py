from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional

try:
    import requests
except ImportError:  # pragma: no cover - shown to non-technical users at runtime.
    requests = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback loader below still works.
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "input" / "tasks.csv"
OUTPUT_DIR = BASE_DIR / "outputs"
PROMPT_DIR = BASE_DIR / "prompts"

REQUIRED_FIELDS = [
    "task_id",
    "article_topic",
    "target_reader",
    "safe_scene",
    "common_misunderstanding",
    "doctor_viewpoint",
    "forbidden_info",
    "risk_tags",
    "doctor_name",
    "status",
]

REQUIRED_STATEMENTS = [
    "本文由 AI 辅助整理，医生审核后发布。",
    "本文仅作心理健康科普，不替代诊断、治疗或个体化心理咨询。",
]

SKIP_STATUSES = {"skip", "skipped", "done", "finished", "跳过", "不生成", "已完成"}

SYSTEM_MESSAGE = """你是一个谨慎的心理健康科普内容整理助手。
你只帮助医生整理脱敏后的心理健康科普内容。
你不能诊断，不能给药物建议，不能承诺疗效，不能生成真实患者或来访者身份信息。
你必须避免输出任何内部思考、隐藏推理、过程标签或思考过程标题。"""


class UserFacingError(Exception):
    """An error message that can be shown directly to the user."""


class SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def load_env() -> None:
    env_path = BASE_DIR / ".env"
    if load_dotenv is not None:
        load_dotenv(dotenv_path=env_path)
        return

    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_runtime_setting(name: str, default: str = "") -> str:
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()

    try:
        import streamlit as st  # type: ignore

        value = st.secrets.get(name, default)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass

    return default


def get_config() -> Dict[str, str]:
    load_env()

    api_key = get_runtime_setting("DEEPSEEK_API_KEY")
    api_base = get_runtime_setting("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    model = get_runtime_setting("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key or api_key == "your_deepseek_api_key_here":
        raise UserFacingError(
            "没有找到可用的 DEEPSEEK_API_KEY。请打开 .env，"
            "把 DEEPSEEK_API_KEY 后面的占位符替换成你的 DeepSeek API Key。"
        )

    if not api_base:
        raise UserFacingError("DEEPSEEK_API_BASE 不能为空。默认值可以填写：https://api.deepseek.com")

    if not model:
        raise UserFacingError("DEEPSEEK_MODEL 不能为空。默认值可以填写：deepseek-chat")

    return {"api_key": api_key, "api_base": api_base, "model": model}


def read_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.exists():
        raise UserFacingError(f"缺少提示词文件：{path}")
    return path.read_text(encoding="utf-8")


def read_tasks() -> List[Dict[str, str]]:
    if not INPUT_FILE.exists():
        raise UserFacingError(f"没有找到任务表：{INPUT_FILE}")

    with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise UserFacingError("input/tasks.csv 是空文件，请先填写表头和至少一行任务。")

        missing = [field for field in REQUIRED_FIELDS if field not in reader.fieldnames]
        if missing:
            raise UserFacingError("input/tasks.csv 缺少字段：" + "、".join(missing))

        rows = []
        for row in reader:
            normalized = {field: clean_cell(row.get(field, "")) for field in REQUIRED_FIELDS}
            if any(normalized.values()):
                rows.append(normalized)

    return rows


def clean_cell(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\r", "\n").split())


def validate_task(task: Mapping[str, str], row_number: int) -> None:
    if not task.get("task_id"):
        raise UserFacingError(f"第 {row_number} 行缺少 task_id，请先填写任务编号。")
    if not task.get("article_topic"):
        raise UserFacingError(f"任务 {task.get('task_id', row_number)} 缺少 article_topic。")
    if not task.get("safe_scene"):
        raise UserFacingError(
            f"任务 {task.get('task_id', row_number)} 缺少 safe_scene。"
            "请填写脱敏后的科普场景，不要粘贴原始咨询记录。"
        )


def should_skip(task: Mapping[str, str]) -> bool:
    return task.get("status", "").strip().lower() in SKIP_STATUSES


def is_doctor_approved(status: str) -> bool:
    value = status.strip().lower()
    if not value:
        return False

    blockers = ["未", "待", "需修改", "不通过", "禁止", "skip", "skipped"]
    if any(blocker in value for blocker in blockers):
        return False

    approvers = ["通过", "已审核", "approved", "approve", "ok"]
    return any(approver in value for approver in approvers)


def task_id_to_filename(task_id: str) -> str:
    safe_id = re.sub(r'[\\/:*?"<>|]+', "_", task_id).strip()
    return safe_id or "未命名任务"


def render_task_table(task: Mapping[str, str]) -> str:
    labels = [
        ("task_id", "任务编号"),
        ("article_topic", "文章主题"),
        ("target_reader", "目标读者"),
        ("safe_scene", "脱敏科普场景"),
        ("common_misunderstanding", "常见误区"),
        ("doctor_viewpoint", "医生观点"),
        ("forbidden_info", "禁止写入的信息"),
        ("risk_tags", "风险标签"),
        ("doctor_name", "医生署名"),
        ("status", "当前状态"),
    ]
    lines = ["| 字段 | 内容 |", "|---|---|"]
    for key, label in labels:
        value = task.get(key, "").strip() or "未填写"
        value = value.replace("|", "｜")
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


def render_prompt(template: str, task: Mapping[str, str], **extra: str) -> str:
    values = SafeFormatDict(task)
    values.update(extra)
    values["task_table"] = render_task_table(task)
    return template.format_map(values)


def call_deepseek(config: Mapping[str, str], user_prompt: str, temperature: float = 0.4) -> str:
    if requests is None:
        raise UserFacingError("缺少 Python 依赖 requests。请先运行：pip install -r requirements.txt")

    endpoint = config["api_base"].rstrip("/") + "/chat/completions"
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=120)
    except requests.exceptions.Timeout as exc:
        raise UserFacingError("调用 DeepSeek 超时，请稍后重试，或检查网络连接。") from exc
    except requests.exceptions.RequestException as exc:
        raise UserFacingError(f"调用 DeepSeek 失败，请检查网络和 API 配置。错误信息：{exc}") from exc

    if response.status_code >= 400:
        raise UserFacingError(build_api_error_message(response))

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise UserFacingError("DeepSeek 返回内容不是可解析的 JSON，请稍后重试。") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise UserFacingError("DeepSeek 返回格式异常，未找到生成内容。") from exc

    if not isinstance(content, str) or not content.strip():
        raise UserFacingError("DeepSeek 返回了空内容，请稍后重试。")

    return sanitize_model_text(content)


def build_api_error_message(response) -> str:
    detail = response.text
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                detail = error.get("message") or detail
            elif isinstance(error, str):
                detail = error
    except json.JSONDecodeError:
        pass

    if response.status_code == 401:
        return "DeepSeek 鉴权失败，请检查 .env 里的 DEEPSEEK_API_KEY 是否正确。"
    if response.status_code == 429:
        return "DeepSeek 请求过于频繁或额度不足，请稍后重试，或检查账户额度。"
    return f"DeepSeek 接口返回错误 HTTP {response.status_code}：{detail}"


def sanitize_model_text(text: str) -> str:
    cleaned = re.sub(r"<think\b[^>]*>.*?(?:</think>|$)", "", text, flags=re.IGNORECASE | re.DOTALL)
    forbidden_markers = ["<think>", "</think>", "Thinking Process", "推理过程", "思考过程"]
    block_markers = ["thinking process", "推理过程", "思考过程"]
    kept_lines = []
    skipping_block = False
    for line in cleaned.splitlines():
        normalized = line.lower()
        if any(marker in normalized for marker in block_markers):
            skipping_block = True
            continue
        if skipping_block:
            if not line.strip():
                skipping_block = False
            continue
        if any(marker.lower() in normalized for marker in forbidden_markers):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def ensure_required_statements(article: str) -> str:
    result = article.rstrip()
    missing = [statement for statement in REQUIRED_STATEMENTS if statement not in result]
    if missing:
        result += "\n\n"
        result += "\n".join(missing)
    return result.strip()


def ensure_teleclaw_boundary(task_package: str, doctor_approved: bool) -> str:
    gate_status = "医生已审核通过，执行前仍需医生最终确认。" if doctor_approved else "医生尚未审核通过，当前任务包禁止执行。"
    boundary = f"""

## TeleClaw 执行边界确认
- 当前门禁：{gate_status}
- TeleClaw 只允许创建并保存微信公众号草稿。
- TeleClaw 严禁发布、发表、群发。
- TeleClaw 严禁点击任何最终发布、确认发布、群发确认按钮。
- 最终发布必须由医生本人手动完成。
""".strip()

    if "TeleClaw 执行边界确认" in task_package:
        return task_package.strip()
    return task_package.rstrip() + "\n\n" + boundary


def assemble_package(
    task: Mapping[str, str],
    article: str,
    risk_review: str,
    teleclaw_package: str,
    doctor_approved: bool,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    teleclaw_status = (
        "可在医生最终确认后创建公众号草稿"
        if doctor_approved
        else "待医生审核，禁止执行 TeleClaw 创建草稿"
    )

    reminders = "\n".join(
        [
            "- 不处理原始心理咨询记录。",
            "- 不存储真实患者或来访者身份信息。",
            "- AI 不做诊断，不给药物建议，不承诺疗效。",
            "- TeleClaw 只允许创建公众号草稿，不允许发布、发表、群发。",
            "- 医生必须审核文章初稿和风险审核结果，确认通过后再进入草稿创建环节。",
            "- 最终发布必须由医生本人手动完成。",
        ]
    )

    return f"""# {task.get("task_id", "未命名任务")} 完整交付包

【状态】
- 生成状态：成功
- 任务编号：{task.get("task_id", "")}
- 文章主题：{task.get("article_topic", "")}
- 医生署名：{task.get("doctor_name", "")}
- 任务表状态：{task.get("status", "") or "未填写"}
- 生成时间：{generated_at}
- TeleClaw 状态：{teleclaw_status}

【文章初稿】

{article}

【风险审核结果】

{risk_review}

【TeleClaw任务包】

{teleclaw_package}

【提醒】

{reminders}
"""


def assemble_failure_package(task: Mapping[str, str], error_message: str) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""# {task.get("task_id", "失败任务")} 完整交付包

【状态】
- 生成状态：失败
- 任务编号：{task.get("task_id", "") or "未填写"}
- 文章主题：{task.get("article_topic", "") or "未填写"}
- 生成时间：{generated_at}
- 错误提示：{error_message}

【文章初稿】

生成失败，未得到文章初稿。

【风险审核结果】

生成失败，未得到风险审核结果。

【TeleClaw任务包】

生成失败，未得到 TeleClaw 任务包。不得执行任何公众号后台操作。

【提醒】

- 请先修复上面的错误提示，再重新运行。
- 不要把原始心理咨询记录或真实患者、来访者身份信息填入任务表。
- TeleClaw 只允许创建公众号草稿，不允许发布、发表、群发。
"""


def write_package(task_id: str, content: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{task_id_to_filename(task_id)}_完整交付包.md"
    output_path = OUTPUT_DIR / filename
    output_path.write_text(content, encoding="utf-8")
    return output_path


def process_task(config: Mapping[str, str], task: Mapping[str, str], row_number: int) -> Path:
    validate_task(task, row_number)

    doctor_approved = is_doctor_approved(task.get("status", ""))
    doctor_status = task.get("status", "") or "未填写"
    teleclaw_gate = (
        "医生已审核通过。TeleClaw 仍然只能创建并保存公众号草稿，不得发布。"
        if doctor_approved
        else "医生尚未审核通过。当前任务包只能用于医生审核，禁止交给 TeleClaw 执行。"
    )

    article_template = read_prompt("article_prompt.txt")
    risk_template = read_prompt("risk_review_prompt.txt")
    teleclaw_template = read_prompt("teleclaw_prompt.txt")

    article_prompt = render_prompt(article_template, task)
    article = call_deepseek(config, article_prompt, temperature=0.5)
    article = ensure_required_statements(article)

    risk_prompt = render_prompt(risk_template, task, article_draft=article)
    risk_review = call_deepseek(config, risk_prompt, temperature=0.2)

    teleclaw_prompt = render_prompt(
        teleclaw_template,
        task,
        article_draft=article,
        risk_review=risk_review,
        doctor_approval_status=doctor_status,
        teleclaw_execution_gate=teleclaw_gate,
    )
    teleclaw_package = call_deepseek(config, teleclaw_prompt, temperature=0.2)
    teleclaw_package = ensure_teleclaw_boundary(teleclaw_package, doctor_approved)

    full_package = assemble_package(task, article, risk_review, teleclaw_package, doctor_approved)
    return write_package(task["task_id"], full_package)


def run() -> int:
    try:
        tasks = read_tasks()
        if not tasks:
            raise UserFacingError("input/tasks.csv 里没有可生成的任务，请至少填写一行。")

        config = get_config()

        total = len(tasks)
        success_count = 0
        failed_count = 0
        skipped_count = 0

        print(f"读取到 {total} 条任务，开始生成...")

        for index, task in enumerate(tasks, start=1):
            task_id = task.get("task_id") or f"row_{index}"
            if should_skip(task):
                skipped_count += 1
                print(f"- 跳过 {task_id}：状态为 {task.get('status')}")
                continue

            print(f"- 正在生成 {task_id}：{task.get('article_topic', '未填写主题')}")
            try:
                output_path = process_task(config, task, index + 1)
                success_count += 1
                print(f"  已保存：{output_path}")
            except Exception as exc:  # Keep each task failure visible and recoverable.
                failed_count += 1
                message = str(exc) or exc.__class__.__name__
                failure_path = write_package(task_id, assemble_failure_package(task, message))
                print(f"  生成失败：{message}")
                print(f"  失败说明已保存：{failure_path}")

        print("")
        print(f"完成：成功 {success_count} 条，失败 {failed_count} 条，跳过 {skipped_count} 条。")
        print(f"输出文件夹：{OUTPUT_DIR}")
        return 0 if failed_count == 0 else 1

    except UserFacingError as exc:
        print("")
        print(f"生成失败：{exc}")
        print("")
        return 1


if __name__ == "__main__":
    sys.exit(run())
