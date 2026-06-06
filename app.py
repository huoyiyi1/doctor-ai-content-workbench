from __future__ import annotations

import csv
import json
import re
import sqlite3
from textwrap import dedent
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

from generate import (
    BASE_DIR,
    INPUT_FILE,
    UserFacingError,
    call_deepseek,
    clean_cell,
    get_config,
    get_runtime_setting,
    read_prompt,
    sanitize_model_text,
    task_id_to_filename,
)


DB_PATH = BASE_DIR / "data" / "tasks.db"
OUTPUT_DIR = BASE_DIR / "outputs"
RAPHAEL_URL = "https://publish.raphael.app"
PRODUCT_NAME = "医生公众号 AI 内容工作台"
PAGES = ["新建文章页", "任务列表页", "任务详情 / 编辑页", "排版发布页"]
PAGE_KEYS = {
    "新建文章页": "new",
    "任务列表页": "list",
    "任务详情 / 编辑页": "detail",
    "排版发布页": "publish",
}
KEY_TO_PAGE = {value: key for key, value in PAGE_KEYS.items()}

STATUSES = [
    "待输入",
    "已生成",
    "待修改",
    "待审核",
    "审核通过",
    "排版中",
    "已复制到 Raphael",
    "已粘贴公众号",
    "已发布",
]

OLD_STATUS_MAP = {
    "pending_input": "待输入",
    "ai_generated": "已生成",
    "doctor_review_pending": "待审核",
    "approved": "审核通过",
    "teleclaw_ready": "排版中",
    "draft_created": "已粘贴公众号",
    "rejected": "待修改",
}

TASK_FIELDS = [
    "task_id",
    "article_topic",
    "target_reader",
    "doctor_name",
    "safe_scene",
    "common_misunderstanding",
    "doctor_viewpoint",
    "forbidden_info",
    "risk_tags",
    "writing_style",
    "article_length",
    "image_style",
    "layout_style",
]

TEXT_COLUMNS = {
    "task_id": "TEXT NOT NULL UNIQUE",
    "article_topic": "TEXT NOT NULL DEFAULT ''",
    "target_reader": "TEXT NOT NULL DEFAULT ''",
    "doctor_name": "TEXT NOT NULL DEFAULT ''",
    "safe_scene": "TEXT NOT NULL DEFAULT ''",
    "common_misunderstanding": "TEXT NOT NULL DEFAULT ''",
    "doctor_viewpoint": "TEXT NOT NULL DEFAULT ''",
    "forbidden_info": "TEXT NOT NULL DEFAULT ''",
    "risk_tags": "TEXT NOT NULL DEFAULT ''",
    "writing_style": "TEXT NOT NULL DEFAULT '温和科普'",
    "article_length": "TEXT NOT NULL DEFAULT '中等1200字'",
    "image_style": "TEXT NOT NULL DEFAULT '温暖治愈'",
    "layout_style": "TEXT NOT NULL DEFAULT '温暖治愈'",
    "status": "TEXT NOT NULL DEFAULT '待输入'",
    "title": "TEXT NOT NULL DEFAULT ''",
    "digest": "TEXT NOT NULL DEFAULT ''",
    "cover_image_prompt": "TEXT NOT NULL DEFAULT ''",
    "markdown": "TEXT NOT NULL DEFAULT ''",
    "original_markdown": "TEXT NOT NULL DEFAULT ''",
    "polished_markdown": "TEXT NOT NULL DEFAULT ''",
    "image_prompts": "TEXT NOT NULL DEFAULT '[]'",
    "risk_level": "TEXT NOT NULL DEFAULT ''",
    "risk_report": "TEXT NOT NULL DEFAULT ''",
    "doctor_review_note": "TEXT NOT NULL DEFAULT ''",
    "rewrite_instruction": "TEXT NOT NULL DEFAULT ''",
    "change_summary": "TEXT NOT NULL DEFAULT ''",
    "output_path": "TEXT NOT NULL DEFAULT ''",
    "copied_to_raphael_at": "TEXT NOT NULL DEFAULT ''",
    "pasted_wechat_at": "TEXT NOT NULL DEFAULT ''",
    "published_at": "TEXT NOT NULL DEFAULT ''",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
}

WRITING_STYLES = ["温和科普", "专业稳重", "公众号故事感", "短平快科普"]
ARTICLE_LENGTHS = ["短文800字", "中等1200字", "长文1800字"]
IMAGE_STYLES = ["温暖治愈", "简洁医学科普", "插画风", "真实生活感", "极简封面"]
LAYOUT_STYLES = ["温暖治愈", "专业医学科普", "极简杂志感", "公众号故事感", "小红书轻科普"]
DISCLAIMER_AI = "本文由 AI 辅助整理，医生审核后发布。"
DISCLAIMER_HEALTH = "本文仅作心理健康科普，不替代诊断、治疗或个体化心理咨询。"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_query_param(name: str) -> str:
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


def page_href(page: str, task_id: str = "") -> str:
    params = [f"page={PAGE_KEYS.get(page, 'list')}"]
    if task_id:
        params.append(f"task_id={quote(task_id)}")
    return "?" + "&".join(params)


def go_to_page(page: str, task_id: str = "") -> None:
    st.session_state["page"] = page
    st.query_params["page"] = PAGE_KEYS.get(page, "list")
    if task_id:
        st.query_params["task_id"] = task_id
    elif "task_id" in st.query_params:
        del st.query_params["task_id"]


def set_flash(message: str, level: str = "success") -> None:
    st.session_state["flash_message"] = {"message": message, "level": level}


def render_flash() -> None:
    flash = st.session_state.pop("flash_message", None)
    if not flash:
        return
    message = flash.get("message", "")
    level = flash.get("level", "success")
    if level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    elif level == "info":
        st.info(message)
    else:
        st.success(message)


def render_top_nav(current_page: str) -> None:
    nav_links = "\n".join(
        f'<a class="module-nav-link {"active" if page == current_page else ""}" href="{page_href(page)}" target="_self">{("当前｜" if page == current_page else "")}{page}</a>'
        for page in PAGES
    )
    st.markdown(
        dedent("""
        <style>
        div[data-testid="stButton"] > button {
            min-height: 48px;
            border-radius: 10px;
            font-weight: 650;
        }
        .module-current {
            margin: 0.25rem 0 0.75rem;
            color: #4b5563;
            font-size: 0.98rem;
            font-weight: 650;
        }
        .module-nav {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.2rem 0 1.2rem;
        }
        .module-nav-link,
        .page-action-link {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 48px;
            padding: 0.7rem 0.9rem;
            border: 1px solid #d7dde5;
            border-radius: 12px;
            background: #ffffff;
            color: #1f2937 !important;
            text-decoration: none !important;
            font-weight: 700;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        .module-nav-link:hover,
        .page-action-link:hover {
            border-color: #9aa8bb;
            background: #f8fafc;
        }
        .module-nav-link.active,
        .page-action-link.primary {
            border-color: #263244;
            background: #263244;
            color: #ffffff !important;
        }
        .page-action-link {
            width: fit-content;
            min-width: 180px;
            margin: 0.25rem 0 0.75rem;
        }
        @media (max-width: 760px) {
            .module-nav {
                grid-template-columns: 1fr 1fr;
            }
        }
        </style>
        """).strip(),
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="module-current">当前模块：{current_page}</div>'
        f'<div class="module-nav">{nav_links}</div>',
        unsafe_allow_html=True,
    )
    st.divider()


def render_page_link_button(label: str, page: str, task_id: str = "", primary: bool = False) -> None:
    class_name = "page-action-link primary" if primary else "page-action-link"
    st.markdown(
        f'<a class="{class_name}" href="{page_href(page, task_id)}" target="_self">{label}</a>',
        unsafe_allow_html=True,
    )


def redirect_to_page(page: str, task_id: str = "") -> None:
    href = page_href(page, task_id)
    components.html(
        f"""
        <script>
        const targetUrl = new URL({json.dumps(href)}, window.parent.location.href).toString();
        window.parent.history.replaceState(null, "", targetUrl);
        window.parent.location.reload();
        </script>
        """,
        height=0,
    )
    st.stop()


class DbConn:
    def __init__(self):
        self.database_url = get_runtime_setting("DATABASE_URL")
        self.kind = "postgres" if self.database_url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self.conn = None

    def __enter__(self):
        if self.kind == "postgres":
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise UserFacingError("缺少 Postgres 依赖，请先安装 requirements.txt。") from exc
            self.conn = psycopg.connect(self.database_url, row_factory=dict_row)
        else:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.conn is None:
            return
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    def execute(self, sql: str, params: Iterable = ()):
        if self.conn is None:
            raise RuntimeError("Database connection is not open.")
        if self.kind == "postgres":
            sql = sql.replace("?", "%s")
        return self.conn.execute(sql, tuple(params))

    def commit(self) -> None:
        if self.conn is not None:
            self.conn.commit()


def get_conn() -> DbConn:
    return DbConn()


def first_value(row) -> int:
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def row_keys(row) -> List[str]:
    if isinstance(row, dict):
        return list(row.keys())
    return list(row.keys())


def init_db() -> None:
    with get_conn() as conn:
        if conn.kind == "postgres":
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE
                )
                """
            )
            existing = {
                row["column_name"]
                for row in conn.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'tasks'
                    """
                ).fetchall()
            }
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE
                )
                """
            )
            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
        for column, definition in TEXT_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")
        conn.commit()
    migrate_existing_data()


def migrate_existing_data() -> None:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks").fetchall()
        for row in rows:
            updates: Dict[str, str] = {}
            status = row["status"] or "待输入"
            if status in OLD_STATUS_MAP:
                updates["status"] = OLD_STATUS_MAP[status]
            elif status not in STATUSES:
                updates["status"] = "待输入"

            keys = row_keys(row)
            if not row["markdown"] and "article_draft" in keys and row["article_draft"]:
                updates["markdown"] = row["article_draft"]
            if not row["risk_report"] and "risk_review" in keys and row["risk_review"]:
                updates["risk_report"] = row["risk_review"]
            markdown_value = updates.get("markdown") or row["markdown"] or ""
            if not row["original_markdown"] and markdown_value:
                updates["original_markdown"] = markdown_value
            if not row["writing_style"]:
                updates["writing_style"] = "温和科普"
            if not row["article_length"]:
                updates["article_length"] = "中等1200字"
            if not row["image_style"]:
                updates["image_style"] = "温暖治愈"
            if not row["layout_style"]:
                updates["layout_style"] = "温暖治愈"
            if updates:
                assignments = ", ".join(f"{key} = ?" for key in updates)
                conn.execute(
                    f"UPDATE tasks SET {assignments}, updated_at = ? WHERE task_id = ?",
                    list(updates.values()) + [now_text(), row["task_id"]],
                )
        conn.commit()


def seed_from_csv_if_empty() -> None:
    if not INPUT_FILE.exists():
        return
    with get_conn() as conn:
        count = first_value(conn.execute("SELECT COUNT(*) AS count FROM tasks").fetchone())
        if count:
            return

    with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            task = {field: clean_cell(row.get(field, "")) for field in TASK_FIELDS}
            if not task["task_id"] or not task["article_topic"]:
                continue
            task["writing_style"] = task.get("writing_style") or "温和科普"
            task["article_length"] = task.get("article_length") or "中等1200字"
            task["image_style"] = task.get("image_style") or "温暖治愈"
            task["layout_style"] = task.get("layout_style") or "温暖治愈"
            create_task(task)


def row_to_dict(row: sqlite3.Row) -> Dict[str, str]:
    if isinstance(row, dict):
        return row
    return {key: row[key] for key in row.keys()}


def list_tasks() -> List[Dict[str, str]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC, id DESC").fetchall()
    return [row_to_dict(row) for row in rows]


def get_task(task_id: str) -> Optional[Dict[str, str]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    return row_to_dict(row) if row else None


def update_task(task_id: str, updates: Mapping[str, str]) -> None:
    if not updates:
        return
    allowed = set(TEXT_COLUMNS.keys()) - {"task_id", "created_at"}
    clean_updates = {key: value for key, value in updates.items() if key in allowed}
    clean_updates["updated_at"] = now_text()
    assignments = ", ".join(f"{key} = ?" for key in clean_updates)
    values = list(clean_updates.values()) + [task_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {assignments} WHERE task_id = ?", values)
        conn.commit()


def delete_task(task_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        conn.commit()
    if st.session_state.get("selected_task_id") == task_id:
        st.session_state.pop("selected_task_id", None)
    if st.session_state.get("selected_publish_task_id") == task_id:
        st.session_state.pop("selected_publish_task_id", None)


def option_index(options: List[str], value: str, default: int = 0) -> int:
    return options.index(value) if value in options else default


def save_task_input_edits(task_id: str, values: Mapping[str, str]) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    cleaned = {field: clean_cell(values.get(field, "")) for field in TASK_FIELDS if field != "task_id"}
    cleaned["writing_style"] = cleaned["writing_style"] or "温和科普"
    cleaned["article_length"] = cleaned["article_length"] or "中等1200字"
    cleaned["image_style"] = cleaned["image_style"] or "温暖治愈"
    cleaned["layout_style"] = cleaned["layout_style"] or "温暖治愈"
    if not cleaned["article_topic"]:
        raise UserFacingError("文章主题不能为空。")
    if not cleaned["safe_scene"]:
        raise UserFacingError("脱敏场景不能为空，且不能粘贴原始心理咨询记录。")
    update_task(task_id, cleaned)


def create_task(task: Mapping[str, str]) -> None:
    values = {field: clean_cell(task.get(field, "")) for field in TASK_FIELDS}
    values["writing_style"] = values["writing_style"] or "温和科普"
    values["article_length"] = values["article_length"] or "中等1200字"
    values["image_style"] = values["image_style"] or "温暖治愈"
    values["layout_style"] = values["layout_style"] or "温暖治愈"
    if not values["task_id"]:
        values["task_id"] = "article_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    if not values["article_topic"]:
        raise UserFacingError("请填写文章主题。")
    if not values["safe_scene"]:
        raise UserFacingError("请填写脱敏场景，不要粘贴原始心理咨询记录。")

    timestamp = now_text()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, article_topic, target_reader, doctor_name, safe_scene,
                common_misunderstanding, doctor_viewpoint, forbidden_info, risk_tags,
                writing_style, article_length, image_style, layout_style, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '待输入', ?, ?)
            """,
            (
                values["task_id"],
                values["article_topic"],
                values["target_reader"],
                values["doctor_name"],
                values["safe_scene"],
                values["common_misunderstanding"],
                values["doctor_viewpoint"],
                values["forbidden_info"],
                values["risk_tags"],
                values["writing_style"],
                values["article_length"],
                values["image_style"],
                values["layout_style"],
                timestamp,
                timestamp,
            ),
        )
        conn.commit()


def render_template(template: str, values: Mapping[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value or "")
    return result


def extract_json_object(text: str) -> Dict:
    cleaned = sanitize_model_text(text).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise UserFacingError("DeepSeek 没有返回可解析的 JSON，请重试。")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise UserFacingError("DeepSeek 返回的 JSON 格式不完整，请重试。") from exc
    if not isinstance(data, dict):
        raise UserFacingError("DeepSeek 返回的不是 JSON 对象，请重试。")
    return data


def normalize_image_prompts(raw_prompts, cover_prompt: str) -> List[Dict[str, str]]:
    prompts: List[Dict[str, str]] = []
    if cover_prompt:
        prompts.append({"position": "封面图", "prompt": clean_cell(cover_prompt)})
    if isinstance(raw_prompts, list):
        for index, item in enumerate(raw_prompts, start=1):
            if isinstance(item, dict):
                position = clean_cell(str(item.get("position", ""))) or f"正文配图 {index}"
                prompt = clean_cell(str(item.get("prompt", "")))
            else:
                position = f"正文配图 {index}"
                prompt = clean_cell(str(item))
            if not prompt:
                continue
            if position == "封面图" and any(p["position"] == "封面图" for p in prompts):
                continue
            prompts.append({"position": position, "prompt": prompt})
    return prompts


def quote_block(position: str, prompt: str) -> str:
    return f"> 【图片提示词｜{position}】\n> {prompt}"


def replace_image_prompt_blocks(markdown: str, image_prompts: List[Dict[str, str]]) -> str:
    prompt_by_position = {
        item.get("position", ""): item.get("prompt", "")
        for item in image_prompts
        if item.get("position") and item.get("prompt")
    }
    if not prompt_by_position:
        return markdown

    marker_pattern = re.compile(r"^>\s*【图片提示词｜(.+?)】\s*$")
    lines = markdown.splitlines()
    output: List[str] = []
    index = 0
    while index < len(lines):
        match = marker_pattern.match(lines[index].strip())
        if match and match.group(1) in prompt_by_position:
            position = match.group(1)
            output.extend(quote_block(position, prompt_by_position[position]).splitlines())
            index += 1
            while index < len(lines):
                stripped = lines[index].strip()
                if not stripped or marker_pattern.match(stripped) or not lines[index].lstrip().startswith(">"):
                    break
                index += 1
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output)


def ensure_markdown_requirements(markdown: str, cover_prompt: str, image_prompts: List[Dict[str, str]]) -> str:
    text = sanitize_model_text(markdown).strip()
    if not text:
        text = "请在这里补充公众号正文。"

    missing_blocks = []
    if cover_prompt and "【图片提示词｜封面图】" not in text:
        missing_blocks.append(quote_block("封面图", cover_prompt))
    for item in image_prompts:
        position = item.get("position", "")
        prompt = item.get("prompt", "")
        if not position or not prompt:
            continue
        marker = f"【图片提示词｜{position}】"
        if marker not in text:
            missing_blocks.append(quote_block(position, prompt))
    if missing_blocks:
        text = "\n\n".join(missing_blocks) + "\n\n" + text

    if DISCLAIMER_AI not in text:
        text = text.rstrip() + "\n\n" + DISCLAIMER_AI
    if DISCLAIMER_HEALTH not in text:
        text = text.rstrip() + "\n" + DISCLAIMER_HEALTH
    return text.strip()


def task_prompt_values(task: Mapping[str, str]) -> Dict[str, str]:
    return {field: task.get(field, "") or "" for field in TASK_FIELDS}


def generate_article(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    config = get_config()
    prompt = render_template(read_prompt("article_prompt.txt"), task_prompt_values(task))
    data = extract_json_object(call_deepseek(config, prompt, temperature=0.5))

    title = sanitize_model_text(str(data.get("title", ""))).strip()
    digest = sanitize_model_text(str(data.get("digest", ""))).strip()
    cover_prompt = sanitize_model_text(str(data.get("cover_image_prompt", ""))).strip()
    image_prompts = normalize_image_prompts(data.get("image_prompts", []), cover_prompt)
    markdown = ensure_markdown_requirements(str(data.get("markdown", "")), cover_prompt, image_prompts)

    if not title:
        raise UserFacingError("DeepSeek 没有返回文章标题，请重试。")
    if not markdown:
        raise UserFacingError("DeepSeek 没有返回正文 Markdown，请重试。")

    update_task(
        task_id,
        {
            "title": title,
            "digest": digest,
            "cover_image_prompt": cover_prompt,
            "markdown": markdown,
            "original_markdown": markdown,
            "polished_markdown": "",
            "image_prompts": json.dumps(image_prompts, ensure_ascii=False, indent=2),
            "risk_level": sanitize_model_text(str(data.get("risk_level", ""))).strip(),
            "risk_report": sanitize_model_text(str(data.get("risk_report", ""))).strip(),
            "doctor_review_note": sanitize_model_text(str(data.get("doctor_review_note", ""))).strip(),
            "change_summary": "",
            "status": "已生成",
        },
    )
    export_markdown(task_id)


def optimize_article(task_id: str, instruction: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    if not instruction.strip():
        raise UserFacingError("请先填写修改意见。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("请先生成文案。")

    config = get_config()
    prompt = render_template(
        read_prompt("rewrite_prompt.txt"),
        {
            "title": task["title"],
            "digest": task["digest"],
            "markdown": source_markdown,
            "rewrite_instruction": instruction,
        },
    )
    data = extract_json_object(call_deepseek(config, prompt, temperature=0.35))
    image_prompts = load_image_prompts(task)
    markdown = ensure_markdown_requirements(
        str(data.get("markdown", "")) or source_markdown,
        task["cover_image_prompt"],
        image_prompts,
    )
    update_task(
        task_id,
        {
            "title": sanitize_model_text(str(data.get("title", task["title"]))).strip(),
            "digest": sanitize_model_text(str(data.get("digest", task["digest"]))).strip(),
            "markdown": markdown,
            "original_markdown": markdown,
            "polished_markdown": "",
            "rewrite_instruction": instruction,
            "change_summary": sanitize_model_text(str(data.get("change_summary", ""))).strip(),
            "status": "待修改",
        },
    )
    export_markdown(task_id)


def simple_regenerate(task_id: str, prompt_name: str, expected_keys: List[str]) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("请先生成文案。")
    config = get_config()
    prompt_values = task_prompt_values(task)
    prompt_values.update(
        {
            "title": task["title"],
            "digest": task["digest"],
            "markdown": source_markdown,
            "cover_image_prompt": task["cover_image_prompt"],
            "image_prompts": task["image_prompts"],
        }
    )
    prompt = render_template(read_prompt(prompt_name), prompt_values)
    if prompt_name == "title_prompt.txt":
        prompt += f"\n\n本次重新生成编号：{now_text()}。请生成一个和当前标题不完全相同的新标题。"
    elif prompt_name == "digest_prompt.txt":
        prompt += f"\n\n本次重新生成编号：{now_text()}。请生成一个和当前摘要不完全相同的新摘要。"
    elif prompt_name == "image_prompt.txt":
        prompt += f"\n\n本次重新生成编号：{now_text()}。请生成一组和当前图片提示词不完全相同的新提示词。"
    data = extract_json_object(call_deepseek(config, prompt, temperature=0.45))
    updates = {"status": "待修改"}
    for key in expected_keys:
        if key in data and isinstance(data[key], str):
            updates[key] = sanitize_model_text(data[key]).strip()
    if "image_prompts" in expected_keys or "cover_image_prompt" in expected_keys:
        cover_prompt = updates.get("cover_image_prompt", task["cover_image_prompt"])
        image_prompts = normalize_image_prompts(data.get("image_prompts", []), cover_prompt)
        if not image_prompts:
            raise UserFacingError("DeepSeek 没有返回新的图片提示词，请重试。")
        raw_markdown = str(data.get("markdown", "")) or source_markdown
        refreshed_markdown = replace_image_prompt_blocks(raw_markdown, image_prompts)
        updates["cover_image_prompt"] = cover_prompt
        updates["image_prompts"] = json.dumps(image_prompts, ensure_ascii=False, indent=2)
        updates["markdown"] = ensure_markdown_requirements(
            refreshed_markdown,
            cover_prompt,
            image_prompts,
        )
        updates["original_markdown"] = updates["markdown"]
        updates["polished_markdown"] = ""
    update_task(task_id, updates)
    export_markdown(task_id)


def load_image_prompts(task: Mapping[str, str]) -> List[Dict[str, str]]:
    try:
        data = json.loads(task.get("image_prompts", "[]") or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [
        {"position": str(item.get("position", "")), "prompt": str(item.get("prompt", ""))}
        for item in data
        if isinstance(item, dict)
    ]


def save_manual_edits(task_id: str, title: str, digest: str, markdown: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    image_prompts = load_image_prompts(task)
    safe_markdown = ensure_markdown_requirements(markdown, task["cover_image_prompt"], image_prompts)
    status = task["status"]
    if status in {"审核通过", "排版中", "已复制到 Raphael", "已粘贴公众号", "已发布"}:
        status = "待修改"
    elif status == "待审核":
        status = "待修改"
    update_task(
        task_id,
        {
            "title": title,
            "digest": digest,
            "markdown": safe_markdown,
            "original_markdown": safe_markdown,
            "polished_markdown": "",
            "status": status,
        },
    )
    export_markdown(task_id)


def enhance_layout(task_id: str, force: bool = False) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("请先生成正文 Markdown。")
    if task.get("polished_markdown") and not force:
        return

    config = get_config()
    prompt = render_template(
        read_prompt("layout_enhance_prompt.txt"),
        {
            "layout_style": task.get("layout_style", "温暖治愈"),
            "original_markdown": source_markdown,
        },
    )
    polished = call_deepseek(config, prompt, temperature=0.35)
    polished = ensure_markdown_requirements(polished, task["cover_image_prompt"], load_image_prompts(task))
    if not polished:
        raise UserFacingError("DeepSeek 没有返回美化后的 Markdown，请重试。")
    update_task(task_id, {"polished_markdown": polished})
    export_markdown(task_id)


def restore_original_markdown(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("当前没有原始 Markdown 可恢复。")
    update_task(task_id, {"markdown": source_markdown, "polished_markdown": ""})
    export_markdown(task_id)


def submit_doctor_review(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    if not task["title"] or not (task.get("original_markdown") or task.get("markdown")):
        raise UserFacingError("请先生成并检查文章内容。")
    update_task(task_id, {"status": "待审核"})
    export_markdown(task_id)


def approve_and_enter_publish(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    if task["status"] not in {"待审核", "审核通过"}:
        raise UserFacingError("只有提交医生审核后的任务，才能进入排版发布页。")
    update_task(task_id, {"status": "排版中"})
    st.session_state["selected_publish_task_id"] = task_id
    go_to_page("排版发布页", task_id=task_id)
    export_markdown(task_id)


def mark_status(task_id: str, status: str, time_field: str = "") -> None:
    updates = {"status": status}
    if time_field:
        updates[time_field] = now_text()
    update_task(task_id, updates)
    export_markdown(task_id)


def final_markdown(task: Mapping[str, str]) -> str:
    title = task["title"].strip()
    body = (
        task.get("polished_markdown")
        or task.get("original_markdown")
        or task.get("markdown")
        or ""
    ).strip()
    if title and not body.startswith("# "):
        return f"# {title}\n\n{body}"
    return body


def export_markdown(task_id: str) -> Path:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到要导出的任务。")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_prompts = load_image_prompts(task)
    image_prompt_text = "\n".join(
        f"- {item['position']}：{item['prompt']}" for item in image_prompts
    ) or "暂无"
    content = f"""# {task['task_id']} 完整交付包

【状态】
- 产品名称：{PRODUCT_NAME}
- 任务编号：{task['task_id']}
- 当前状态：{task['status']}
- 文章主题：{task['article_topic']}
- 医生署名：{task['doctor_name']}
- 风险等级：{task['risk_level'] or '未生成'}
- 排版风格：{task.get('layout_style') or '温暖治愈'}
- 更新时间：{task['updated_at'] or now_text()}

【标题】
{task['title'] or '未生成'}

【摘要】
{task['digest'] or '未生成'}

【封面图提示词】
{task['cover_image_prompt'] or '未生成'}

【正文 Markdown】

{final_markdown(task) or '未生成'}

【原始 Markdown】

{task.get('original_markdown') or task.get('markdown') or '未生成'}

【美化 Markdown】

{task.get('polished_markdown') or '未生成'}

【图片提示词列表】
{image_prompt_text}

【风险审核报告】
{task['risk_report'] or '未生成'}

【医生审核提醒】
{task['doctor_review_note'] or '未生成'}

【提醒】
- 不处理原始心理咨询记录。
- 不使用真实来访者故事。
- AI 不做诊断，不给药物建议，不承诺疗效。
- 未经医生审核通过，不进入排版发布页。
- 第一版不调用 GPT Image API，只生成图片提示词。
- Raphael 仅用于公众号排版预览，最终发布必须由医生人工完成。
"""
    output_path = OUTPUT_DIR / f"{task_id_to_filename(task['task_id'])}_完整交付包.md"
    output_path.write_text(content, encoding="utf-8")
    update_task(task_id, {"output_path": str(output_path)})
    return output_path


def render_copy_button(text: str, label: str, copied_label: str) -> None:
    payload = json.dumps(text or "", ensure_ascii=False)
    element_id = re.sub(r"[^a-zA-Z0-9_]", "_", label) + "_" + str(abs(hash(payload)) % 1000000)
    components.html(
        f"""
        <style>
        .copy-action-wrap {{
            display: flex;
            align-items: center;
            gap: 10px;
            min-height: 58px;
            padding: 0 0 10px;
            box-sizing: border-box;
        }}
        .copy-action-button {{
            min-height: 48px;
            width: 100%;
            padding: 0.7rem 0.9rem;
            border: 1px solid #d7dde5;
            border-radius: 10px;
            background: #ffffff;
            color: #1f2937;
            cursor: pointer;
            font-size: 16px;
            font-weight: 650;
            line-height: 1.2;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }}
        .copy-action-button:hover {{
            border-color: #9aa8bb;
            background: #f8fafc;
        }}
        .copy-action-status {{
            min-width: 8em;
            color: #2e7d32;
            font-size: 14px;
            white-space: nowrap;
        }}
        </style>
        <div class="copy-action-wrap">
        <button
          id="{element_id}_button"
          class="copy-action-button"
        >
          {label}
        </button>
        <span id="{element_id}_status" class="copy-action-status"></span>
        </div>
        <script>
        const button = document.getElementById("{element_id}_button");
        const status = document.getElementById("{element_id}_status");
        button.addEventListener("click", async () => {{
          try {{
            await navigator.clipboard.writeText({payload});
            status.textContent = "{copied_label}";
          }} catch (error) {{
            status.textContent = "复制失败，请手动复制下方文本";
            status.style.color = "#b00020";
          }}
        }});
        </script>
        """,
        height=72,
    )


def run_action(label: str, action, *args, button_type: str = "secondary", key: Optional[str] = None) -> None:
    button_key = key or f"action_{label}_{'_'.join(str(arg) for arg in args)}"
    if st.button(label, type=button_type, key=button_key):
        progress = st.empty()
        try:
            progress.info(f"正在{label}，请稍等...")
            action(*args)
            progress.empty()
            set_flash("完成。")
            st.rerun()
            st.stop()
        except Exception as exc:
            progress.empty()
            st.error(str(exc))


def show_boundary_notice() -> None:
    st.info(
        "边界：只处理脱敏科普卡；不使用真实来访者故事；AI 不诊断、不给药、不承诺疗效；"
        "未审核通过不进入排版发布页；第一版只生成图片提示词，不调用图片 API。"
    )


def render_new_article_page() -> None:
    st.subheader("新建文章页")
    with st.form("new_article_form"):
        default_id = "article_" + datetime.now().strftime("%Y%m%d_%H%M")
        task_id = st.text_input("任务编号", value=default_id)
        article_topic = st.text_input("文章主题 article_topic", placeholder="例：为什么越焦虑越停不下刷手机")
        target_reader = st.text_input("目标读者 target_reader", placeholder="例：经常焦虑、睡前容易刷手机的成年人")
        doctor_name = st.text_input("医生署名 doctor_name", placeholder="例：张医生")
        safe_scene = st.text_area(
            "脱敏场景 safe_scene",
            height=100,
            placeholder="例：一类常见现象：很多人在压力大时会反复刷手机，越刷越累，但又停不下来。不要填写真实个案。",
        )
        common_misunderstanding = st.text_area(
            "常见误区 common_misunderstanding",
            height=80,
            placeholder="例：很多人以为这是自控力差，其实也可能和压力、回避、即时安抚有关。",
        )
        doctor_viewpoint = st.text_area(
            "医生核心观点 doctor_viewpoint",
            height=90,
            placeholder="例：先理解行为背后的情绪功能，再用低压力的小步骤恢复节奏。",
        )
        forbidden_info = st.text_area(
            "禁止出现的信息 forbidden_info",
            value="不要出现真实来访者故事；不要诊断；不要给药物建议；不要承诺疗效。",
            height=80,
        )
        risk_tags = st.text_input("风险标签 risk_tags", value="无")
        writing_style = st.selectbox("文章风格 writing_style", WRITING_STYLES)
        article_length = st.selectbox("文章长度 article_length", ARTICLE_LENGTHS, index=1)
        image_style = st.selectbox("图片风格 image_style", IMAGE_STYLES)
        layout_style = st.selectbox("排版风格 layout_style", LAYOUT_STYLES)
        submitted = st.form_submit_button("保存文章任务", type="primary")

    if submitted:
        try:
            create_task(
                {
                    "task_id": task_id,
                    "article_topic": article_topic,
                    "target_reader": target_reader,
                    "doctor_name": doctor_name,
                    "safe_scene": safe_scene,
                    "common_misunderstanding": common_misunderstanding,
                    "doctor_viewpoint": doctor_viewpoint,
                    "forbidden_info": forbidden_info,
                    "risk_tags": risk_tags,
                    "writing_style": writing_style,
                    "article_length": article_length,
                    "image_style": image_style,
                    "layout_style": layout_style,
                }
            )
            st.session_state["selected_task_id"] = task_id
            go_to_page("任务详情 / 编辑页", task_id=task_id)
            set_flash("文章任务已保存，可以生成文案。")
            st.rerun()
        except sqlite3.IntegrityError:
            st.error("任务编号已存在，请换一个任务编号。")
        except Exception as exc:
            st.error(str(exc))


def render_task_list_page(tasks: List[Dict[str, str]]) -> None:
    st.subheader("任务列表页")
    if not tasks:
        st.warning("还没有任务，请先新建文章。")
        return
    rows = [
        {
            "任务编号": task["task_id"],
            "标题": task["title"] or "未生成",
            "主题": task["article_topic"],
            "医生": task["doctor_name"],
            "状态": task["status"],
            "风险等级": task["risk_level"],
            "更新时间": task["updated_at"],
        }
        for task in tasks
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    task_ids = [task["task_id"] for task in tasks]
    selected_id = st.session_state.get("selected_task_id")
    if selected_id not in task_ids:
        selected_id = task_ids[0]
    if st.session_state.get("list_selected_task_id") not in task_ids:
        st.session_state["list_selected_task_id"] = selected_id

    selected = st.selectbox(
        "选择要管理的任务",
        task_ids,
        format_func=lambda task_id: f"{task_id}｜{get_task(task_id)['article_topic'] if get_task(task_id) else ''}",
        key="list_selected_task_id",
    )
    st.session_state["selected_task_id"] = selected
    if get_query_param("task_id") != selected:
        st.query_params["task_id"] = selected
    selected_task = get_task(selected)
    if selected_task is None:
        st.error("任务不存在。")
        return
    st.info(
        f"当前选中：{selected_task['task_id']}｜{selected_task['article_topic'] or selected_task['title'] or '未命名任务'}"
        f"｜状态：{selected_task['status']}"
    )

    render_page_link_button("打开任务详情 / 编辑页", "任务详情 / 编辑页", task_id=selected, primary=True)

    with st.expander("快速编辑所选任务基础信息", expanded=False):
        with st.form(f"list_edit_form_{selected}"):
            values = render_task_input_fields(selected_task, prefix="list")
            saved = st.form_submit_button("保存基础信息修改", type="primary")
        if saved:
            try:
                save_task_input_edits(selected, values)
                set_flash("基础信息已保存。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with st.expander("删除所选任务", expanded=False):
        st.error("强提示：删除后，整条任务数据将不可找回，包括标题、正文、风险报告、美化 Markdown 和状态记录。")
        st.markdown(f"**即将删除：{selected_task['task_id']}｜{selected_task['article_topic'] or selected_task['title'] or '未命名任务'}**")
        confirm_checkbox = st.checkbox("我理解删除后不可恢复", key=f"delete_confirm_checkbox_{selected}")
        if st.button("删除该任务", key=f"delete_task_{selected}", type="primary"):
            if not confirm_checkbox:
                st.warning("请先勾选“我理解删除后不可恢复”。")
            else:
                delete_task(selected)
                set_flash("任务已删除。")
                st.rerun()


def render_task_input_fields(task: Mapping[str, str], prefix: str) -> Dict[str, str]:
    return {
        "article_topic": st.text_input(
            "文章主题 article_topic",
            value=task["article_topic"],
            placeholder="例：为什么越焦虑越停不下刷手机",
            key=f"{prefix}_article_topic_{task['task_id']}",
        ),
        "target_reader": st.text_input(
            "目标读者 target_reader",
            value=task["target_reader"],
            placeholder="例：经常焦虑、睡前容易刷手机的成年人",
            key=f"{prefix}_target_reader_{task['task_id']}",
        ),
        "doctor_name": st.text_input(
            "医生署名 doctor_name",
            value=task["doctor_name"],
            placeholder="例：张医生",
            key=f"{prefix}_doctor_name_{task['task_id']}",
        ),
        "safe_scene": st.text_area(
            "脱敏场景 safe_scene",
            value=task["safe_scene"],
            placeholder="例：很多人在压力大时会反复刷手机，越刷越累，但又停不下来。不要填写真实个案。",
            height=100,
            key=f"{prefix}_safe_scene_{task['task_id']}",
        ),
        "common_misunderstanding": st.text_area(
            "常见误区 common_misunderstanding",
            value=task["common_misunderstanding"],
            placeholder="例：很多人以为这是自控力差，其实也可能和压力、回避、即时安抚有关。",
            height=80,
            key=f"{prefix}_common_misunderstanding_{task['task_id']}",
        ),
        "doctor_viewpoint": st.text_area(
            "医生核心观点 doctor_viewpoint",
            value=task["doctor_viewpoint"],
            placeholder="例：先理解行为背后的情绪功能，再用低压力的小步骤恢复节奏。",
            height=90,
            key=f"{prefix}_doctor_viewpoint_{task['task_id']}",
        ),
        "forbidden_info": st.text_area(
            "禁止出现的信息 forbidden_info",
            value=task["forbidden_info"] or "不要出现真实来访者故事；不要诊断；不要给药物建议；不要承诺疗效。",
            height=80,
            key=f"{prefix}_forbidden_info_{task['task_id']}",
        ),
        "risk_tags": st.text_input(
            "风险标签 risk_tags",
            value=task["risk_tags"] or "无",
            key=f"{prefix}_risk_tags_{task['task_id']}",
        ),
        "writing_style": st.selectbox(
            "文章风格 writing_style",
            WRITING_STYLES,
            index=option_index(WRITING_STYLES, task["writing_style"]),
            key=f"{prefix}_writing_style_{task['task_id']}",
        ),
        "article_length": st.selectbox(
            "文章长度 article_length",
            ARTICLE_LENGTHS,
            index=option_index(ARTICLE_LENGTHS, task["article_length"], 1),
            key=f"{prefix}_article_length_{task['task_id']}",
        ),
        "image_style": st.selectbox(
            "图片风格 image_style",
            IMAGE_STYLES,
            index=option_index(IMAGE_STYLES, task["image_style"]),
            key=f"{prefix}_image_style_{task['task_id']}",
        ),
        "layout_style": st.selectbox(
            "排版风格 layout_style",
            LAYOUT_STYLES,
            index=option_index(LAYOUT_STYLES, task.get("layout_style", "温暖治愈")),
            key=f"{prefix}_layout_style_{task['task_id']}",
        ),
    }


def render_input_card(task: Mapping[str, str]) -> None:
    with st.expander("脱敏科普卡", expanded=False):
        st.markdown(
            f"""
| 字段 | 内容 |
|---|---|
| 文章主题 | {task['article_topic']} |
| 目标读者 | {task['target_reader']} |
| 医生署名 | {task['doctor_name']} |
| 脱敏场景 | {task['safe_scene']} |
| 常见误区 | {task['common_misunderstanding']} |
| 医生核心观点 | {task['doctor_viewpoint']} |
| 禁止出现的信息 | {task['forbidden_info']} |
| 风险标签 | {task['risk_tags']} |
| 文章风格 | {task['writing_style']} |
| 文章长度 | {task['article_length']} |
| 图片风格 | {task['image_style']} |
| 排版风格 | {task.get('layout_style', '温暖治愈')} |
"""
        )


def render_task_detail_page(tasks: List[Dict[str, str]]) -> None:
    st.subheader("任务详情 / 编辑页")
    if not tasks:
        st.warning("还没有任务，请先新建文章。")
        return
    task_ids = [task["task_id"] for task in tasks]
    selected = st.session_state.get("selected_task_id")
    if selected not in task_ids:
        selected = task_ids[0]
    if st.session_state.get("detail_selected_task_id") not in task_ids:
        st.session_state["detail_selected_task_id"] = selected
    selected = st.selectbox(
        "当前任务",
        task_ids,
        index=task_ids.index(selected),
        key="detail_selected_task_id",
    )
    st.session_state["selected_task_id"] = selected
    if get_query_param("task_id") != selected:
        st.query_params["task_id"] = selected
    task = get_task(selected)
    if task is None:
        st.error("任务不存在。")
        return
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""

    st.caption(f"当前状态：{task['status']}")
    show_boundary_notice()
    render_input_card(task)

    cols = st.columns(5)
    cols[0].metric("风险等级", task["risk_level"] or "未生成")
    cols[1].metric("文章风格", task["writing_style"])
    cols[2].metric("文章长度", task["article_length"])
    cols[3].metric("图片风格", task["image_style"])
    cols[4].metric("排版风格", task.get("layout_style") or "温暖治愈")

    st.markdown("#### 生成操作")
    gen_cols = st.columns(5)
    with gen_cols[0]:
        if task["status"] in {"待输入", "已生成", "待修改", "待审核"}:
            run_action("生成文案", generate_article, task["task_id"], button_type="primary")
    with gen_cols[1]:
        if source_markdown:
            run_action("重新生成标题", simple_regenerate, task["task_id"], "title_prompt.txt", ["title"])
    with gen_cols[2]:
        if source_markdown:
            run_action("重新生成摘要", simple_regenerate, task["task_id"], "digest_prompt.txt", ["digest"])
    with gen_cols[3]:
        if source_markdown:
            run_action(
                "重新生成图片提示词",
                simple_regenerate,
                task["task_id"],
                "image_prompt.txt",
                ["cover_image_prompt", "image_prompts"],
            )
    with gen_cols[4]:
        if source_markdown or task.get("polished_markdown"):
            render_copy_button(final_markdown(task), "复制 Markdown", "已复制 Markdown")

    if not source_markdown:
        st.warning("还没有生成文案。请先点击“生成文案”。")
        return

    st.markdown("#### 可编辑内容")
    edited_title = st.text_input("标题", value=task["title"])
    edited_digest = st.text_area("摘要", value=task["digest"], height=80)
    edited_markdown = st.text_area("原始正文 Markdown", value=source_markdown, height=520)
    if st.button("保存修改", type="primary"):
        try:
            save_manual_edits(task["task_id"], edited_title, edited_digest, edited_markdown)
            set_flash("已保存修改。修改后需要重新提交医生审核。")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.markdown("#### 排版美化")
    layout_cols = st.columns(4)
    with layout_cols[0]:
        run_action("一键美化排版", enhance_layout, task["task_id"], False, button_type="primary")
    with layout_cols[1]:
        run_action("重新生成排版", enhance_layout, task["task_id"], True)
    with layout_cols[2]:
        if task.get("polished_markdown"):
            run_action("恢复原始 Markdown", restore_original_markdown, task["task_id"])
    with layout_cols[3]:
        if task.get("polished_markdown"):
            render_copy_button(final_markdown(task), "复制美化 Markdown", "已复制美化 Markdown")
        else:
            st.button("复制美化 Markdown", disabled=True, help="请先点击“一键美化排版”。")
    if task.get("polished_markdown"):
        st.text_area("美化 Markdown 预览", value=task["polished_markdown"], height=360)
    else:
        st.caption("还没有美化 Markdown。排版发布页会先展示原始 Markdown。")

    st.markdown("#### 修改意见")
    rewrite_instruction = st.text_area("输入修改意见", value=task["rewrite_instruction"], height=100)
    run_action(
        "根据修改意见优化全文",
        optimize_article,
        task["task_id"],
        rewrite_instruction,
        key=f"rewrite_full_{task['task_id']}",
    )
    if task["change_summary"]:
        st.info("本次修改摘要：" + task["change_summary"])

    st.markdown("#### 图片提示词")
    st.text_area("封面图提示词", value=task["cover_image_prompt"], height=100, disabled=True)
    image_prompts = load_image_prompts(task)
    if image_prompts:
        st.dataframe(image_prompts, width="stretch", hide_index=True)

    st.markdown("#### 风险审核报告")
    st.markdown(task["risk_report"] or "暂无风险审核报告。")
    if task["doctor_review_note"]:
        st.warning(task["doctor_review_note"])

    st.markdown("#### 医生审核")
    review_cols = st.columns(2)
    with review_cols[0]:
        if task["status"] in {"已生成", "待修改", "待审核"}:
            run_action("提交医生审核", submit_doctor_review, task["task_id"], button_type="primary")
    with review_cols[1]:
        if task["status"] == "待审核":
            if st.button("审核通过，进入排版", type="primary"):
                try:
                    approve_and_enter_publish(task["task_id"])
                    set_flash("已审核通过，进入排版发布页。")
                    redirect_to_page("排版发布页", task_id=task["task_id"])
                except Exception as exc:
                    st.error(str(exc))
        elif task["status"] in {"排版中", "已复制到 Raphael", "已粘贴公众号", "已发布"}:
            st.success("医生已审核通过，可以进入排版发布页。")
            render_page_link_button("打开排版发布页", "排版发布页", task_id=task["task_id"], primary=True)


def render_publish_page(tasks: List[Dict[str, str]]) -> None:
    st.subheader("排版发布页")
    if not tasks:
        st.warning("还没有任务，请先新建文章。")
        return
    task_ids = [task["task_id"] for task in tasks]
    selected = st.session_state.get("selected_publish_task_id") or st.session_state.get("selected_task_id")
    if selected not in task_ids:
        selected = task_ids[0]
    selected = st.selectbox("选择排版任务", task_ids, index=task_ids.index(selected), key="publish_task_select")
    st.session_state["selected_publish_task_id"] = selected
    task = get_task(selected)
    if task is None:
        st.error("任务不存在。")
        return

    if task["status"] not in {"审核通过", "排版中", "已复制到 Raphael", "已粘贴公众号", "已发布"}:
        st.warning("未审核通过，不能进入排版发布。请先在任务详情 / 编辑页提交医生审核并审核通过。")
        return
    if task["status"] == "审核通过":
        mark_status(task["task_id"], "排版中")
        st.rerun()

    markdown = final_markdown(task)
    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### 最终 Markdown")
        render_copy_button(markdown, "复制 Markdown", "已复制 Markdown")
        st.text_area("Markdown 内容", value=markdown, height=680)
        st.link_button("打开 Raphael（新窗口，推荐）", RAPHAEL_URL)
        st.info("推荐复制 Markdown 后，在新窗口打开 Raphael 使用。右侧内嵌预览可能受第三方 iframe 限制。")
        status_cols = st.columns(3)
        with status_cols[0]:
            run_action("标记已复制到 Raphael", mark_status, task["task_id"], "已复制到 Raphael", "copied_to_raphael_at")
        with status_cols[1]:
            run_action("标记已粘贴公众号", mark_status, task["task_id"], "已粘贴公众号", "pasted_wechat_at")
        with status_cols[2]:
            run_action("标记已发布", mark_status, task["task_id"], "已发布", "published_at")

    with right:
        st.markdown("#### Raphael 排版预览")
        st.warning("如果右侧无法显示，或选择款式、设备预览按钮没有反应，这是 Raphael 在第三方 iframe 中的限制。请点击“打开 Raphael（新窗口，推荐）”使用完整功能。")
        components.iframe(RAPHAEL_URL, height=760, scrolling=True)


def main() -> None:
    st.set_page_config(page_title=PRODUCT_NAME, layout="wide")
    init_db()
    seed_from_csv_if_empty()

    st.title(PRODUCT_NAME)
    st.caption("V1 演示版：脱敏科普卡 → DeepSeek 文案与风控 → 网页编辑优化 → 医生审核 → Raphael 排版预览。")

    query_page = get_query_param("page")
    current_page = KEY_TO_PAGE.get(query_page) or st.session_state.get("page", "任务列表页")
    if current_page not in PAGES:
        current_page = "任务列表页"
    st.session_state["page"] = current_page

    query_task_id = get_query_param("task_id")
    if query_task_id:
        st.session_state["selected_task_id"] = query_task_id
        if current_page == "排版发布页":
            st.session_state["selected_publish_task_id"] = query_task_id

    tasks = list_tasks()
    render_top_nav(current_page)
    render_flash()

    if current_page == "新建文章页":
        render_new_article_page()
    elif current_page == "任务列表页":
        render_task_list_page(tasks)
    elif current_page == "任务详情 / 编辑页":
        render_task_detail_page(tasks)
    elif current_page == "排版发布页":
        render_publish_page(tasks)


if __name__ == "__main__":
    main()
