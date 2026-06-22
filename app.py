from __future__ import annotations

import base64
import csv
import json
import re
import sqlite3
from html import escape
from textwrap import dedent
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote, urlparse

import streamlit as st
import streamlit.components.v1 as components

from generate import (
    BASE_DIR,
    INPUT_FILE,
    UserFacingError,
    call_deepseek,
    clean_cell,
    get_config,
    load_env,
    get_runtime_setting,
    read_prompt,
    render_task_table,
    sanitize_model_text,
    task_id_to_filename,
)
from orm_models import (
    create_knowledge_base as orm_create_knowledge_base,
    create_generated_image,
    create_knowledge_content,
    create_revision_history,
    create_topic_history,
    delete_generated_image,
    delete_knowledge_base as orm_delete_knowledge_base,
    delete_knowledge_content,
    get_app_settings_map,
    get_article_draft_by_legacy_task,
    get_generated_image,
    get_knowledge_base as orm_get_knowledge_base,
    get_knowledge_content,
    init_orm_database,
    list_generated_images,
    list_knowledge_bases,
    list_knowledge_contents,
    list_topic_history,
    list_tags,
    replace_generated_images,
    update_generated_image,
    update_knowledge_base as orm_update_knowledge_base,
    update_knowledge_content,
    update_topic_history_generated_article,
    upsert_article_draft_from_legacy_task,
)
from services.image_generation.provider_factory import get_image_generation_provider
from services.image_storage.provider_factory import get_image_storage_provider


load_env()

DB_PATH = BASE_DIR / "data" / "tasks.db"
OUTPUT_DIR = BASE_DIR / "outputs"
IMAGE_OUTPUT_DIR = OUTPUT_DIR / "images"
RAPHAEL_URL = "https://publish.raphael.app"
PRODUCT_NAME = "公众号内容自动生成工作台"
NAV_PAGES = [
    "内容工作台",
    "知识库",
    "计划生成",
    "历史稿件",
    "设置",
]
HIDDEN_PAGES = [
    "新建文章页",
    "直接生成一篇",
    "基于知识库生成",
    "新增今日素材",
    "任务详情 / 编辑页",
    "文章详情 / 审核页",
    "任务列表页",
    "排版发布页",
    "知识库详情 / 管理",
    "新增 / 编辑知识页",
    "每周计划详情页",
    "每周内容计划页",
]
PAGES = NAV_PAGES + HIDDEN_PAGES
PAGE_KEYS = {
    "内容工作台": "home",
    "知识库": "knowledge",
    "计划生成": "plan",
    "历史稿件": "history",
    "设置": "settings",
    "新建文章页": "new",
    "直接生成一篇": "new",
    "基于知识库生成": "knowledge_generate",
    "新增今日素材": "material_new",
    "任务列表页": "list",
    "任务详情 / 编辑页": "detail",
    "文章详情 / 审核页": "detail",
    "排版发布页": "publish",
    "知识库管理页": "knowledge_legacy",
    "知识库详情 / 管理": "knowledge_detail",
    "新增 / 编辑知识页": "knowledge_edit",
    "每周内容计划页": "weekly_legacy",
    "每周计划详情页": "计划生成",
    "计划生成详情": "weekly_detail",
}
PAGE_PARENT = {
    "新建文章页": "内容工作台",
    "直接生成一篇": "内容工作台",
    "基于知识库生成": "知识库",
    "新增今日素材": "知识库",
    "任务详情 / 编辑页": "历史稿件",
    "文章详情 / 审核页": "历史稿件",
    "任务列表页": "历史稿件",
    "排版发布页": "历史稿件",
    "知识库管理页": "知识库",
    "知识库详情 / 管理": "知识库",
    "新增 / 编辑知识页": "知识库",
    "每周内容计划页": "计划生成",
    "每周计划详情页": "weekly_detail",
    "计划生成详情": "计划生成",
}
KEY_TO_PAGE = {value: key for key, value in PAGE_KEYS.items()}
KEY_TO_PAGE.update(
    {
        "new": "新建文章页",
        "detail": "任务详情 / 编辑页",
        "knowledge_edit": "新增 / 编辑知识页",
        "weekly_detail": "每周计划详情页",
        "weekly": "每周内容计划页",
        "list": "任务列表页",
        "publish": "排版发布页",
    }
)

STATUSES = [
    "待输入",
    "已生成",
    "已生成，待审核",
    "待修改",
    "需修改",
    "重新生成中",
    "待审核",
    "审核通过",
    "排版中",
    "已发布",
    "已废弃",
]
RUNNING_WEEKLY_STATUSES = {"生成选题中", "生成文章中"}

OLD_STATUS_MAP = {
    "pending_input": "待输入",
    "ai_generated": "已生成",
    "doctor_review_pending": "待审核",
    "approved": "审核通过",
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
    "retrieved_knowledge": "TEXT NOT NULL DEFAULT ''",
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

KNOWLEDGE_TYPES = {
    "doctor_style": "医生风格",
    "topic_material": "选题素材",
    "reference": "参考资料",
    "compliance": "合规规则",
    "history_article": "历史文章",
}

KNOWLEDGE_COLUMNS = {
    "title": "TEXT NOT NULL DEFAULT ''",
    "content": "TEXT NOT NULL DEFAULT ''",
    "type": "TEXT NOT NULL DEFAULT 'topic_material'",
    "tags": "TEXT NOT NULL DEFAULT ''",
    "enabled": "INTEGER NOT NULL DEFAULT 1",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
}

WEEKLY_PLAN_COLUMNS = {
    "plan_name": "TEXT NOT NULL DEFAULT '每周内容计划'",
    "week_start_date": "TEXT NOT NULL DEFAULT ''",
    "article_count": "INTEGER NOT NULL DEFAULT 3",
    "weekly_focus": "TEXT NOT NULL DEFAULT ''",
    "selected_tags": "TEXT NOT NULL DEFAULT ''",
    "knowledge_base_id": "INTEGER NOT NULL DEFAULT 0",
    "generation_mode": "TEXT NOT NULL DEFAULT 'AI 自动推荐选题'",
    "writing_style": "TEXT NOT NULL DEFAULT '温和科普'",
    "article_length": "TEXT NOT NULL DEFAULT '中等1200字'",
    "generate_time": "TEXT NOT NULL DEFAULT '09:00'",
    "after_generate_status": "TEXT NOT NULL DEFAULT '已生成，待审核'",
    "enabled": "INTEGER NOT NULL DEFAULT 1",
    "status": "TEXT NOT NULL DEFAULT '待生成选题'",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
}

WEEKLY_TOPIC_COLUMNS = {
    "weekly_plan_id": "INTEGER NOT NULL DEFAULT 0",
    "title": "TEXT NOT NULL DEFAULT ''",
    "target_reader": "TEXT NOT NULL DEFAULT ''",
    "core_viewpoint": "TEXT NOT NULL DEFAULT ''",
    "article_angle": "TEXT NOT NULL DEFAULT ''",
    "risk_tags": "TEXT NOT NULL DEFAULT ''",
    "reason": "TEXT NOT NULL DEFAULT ''",
    "generated_article_task_id": "TEXT NOT NULL DEFAULT ''",
    "topic_history_id": "INTEGER NOT NULL DEFAULT 0",
    "status": "TEXT NOT NULL DEFAULT '待生成文章'",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
}

WRITING_STYLES = ["温和科普", "专业稳重", "公众号故事感", "短平快科普"]
ARTICLE_LENGTHS = ["短文800字", "中等1200字", "长文1800字", "深度3000字", "最长4000字"]
IMAGE_STYLES = ["温暖治愈", "简洁医学科普", "插画风", "真实生活感", "极简封面"]
LAYOUT_STYLES = ["温暖治愈", "专业医学科普", "极简杂志感", "公众号故事感", "小红书轻科普"]
IMAGE_ASPECT_RATIOS = ["2.35:1", "16:9", "4:3", "3:4", "1:1"]
IMAGE_STYLE_PRESETS = ["温和治愈插画", "简洁专业封面", "生活场景摄影感", "抽象情绪视觉", "轻杂志风封面", "摄影级写实", "3D 渲染", "极简扁平插画"]
IMAGE_INSERT_POSITIONS = ["cover_only", "after_intro", "after_heading_1", "after_heading_2", "before_ending", "custom", "not_inserted"]
IMAGE_INSERT_LABELS = {
    "cover_only": "仅作为封面",
    "after_intro": "开头段落后",
    "after_heading_1": "第一个小标题后",
    "after_heading_2": "第二个小标题后",
    "before_ending": "结尾前",
    "custom": "自定义位置",
    "not_inserted": "不插入正文",
}
IMAGE_STATUS_LABELS = {
    "prompt_ready": "提示词已准备",
    "not_inserted": "未插入正文",
    "inserted": "已插入正文",
    "generation_pending": "等待生成",
    "generated_local": "已有本地图片",
    "uploaded_public": "已有可访问链接",
    "manual_url": "已填写图片链接",
    "selected": "已选用",
    "failed": "失败",
    "disabled": "不使用",
}
IMAGE_PLACEHOLDER_RE = re.compile(r"\{\{\s*image\s*:\s*([a-zA-Z0-9_\-]+)\s*\}\}")
DEFAULT_NEGATIVE_PROMPT = "真实患者形象、病历、诊断书、药物、医院病床、自伤、自杀、血腥、恐怖、大段文字、可识别身份信息、夸张疗效暗示、低清晰度"
DISCLAIMER_AI = "本文由 AI 辅助整理，审核后发布。"
DISCLAIMER_HEALTH = "本文仅作科普参考，不替代专业诊断、治疗或个体化咨询建议。"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_query_param(name: str) -> str:
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


def page_href(page: str, task_id: str = "", knowledge_id: str = "", plan_id: str = "") -> str:
    params = [f"page={PAGE_KEYS.get(page, 'home')}"]
    if task_id:
        params.append(f"task_id={quote(task_id)}")
    if knowledge_id:
        params.append(f"knowledge_id={quote(str(knowledge_id))}")
    if plan_id:
        params.append(f"plan_id={quote(str(plan_id))}")
    return "?" + "&".join(params)


def go_to_page(page: str, task_id: str = "", knowledge_id: str = "", plan_id: str = "") -> None:
    st.session_state["page"] = page
    st.query_params["page"] = PAGE_KEYS.get(page, "home")
    id_params = {
        "task_id": task_id,
        "knowledge_id": str(knowledge_id) if knowledge_id else "",
        "plan_id": str(plan_id) if plan_id else "",
    }
    for param_name, param_value in id_params.items():
        if param_value:
            st.query_params[param_name] = param_value
        elif param_name in st.query_params:
            del st.query_params[param_name]


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


def start_active_operation(operation_type: str, target_id: object, label: str) -> None:
    st.session_state["active_operation"] = {
        "operation_type": operation_type,
        "target_id": str(target_id),
        "label": label,
        "started_at": now_text(),
    }


def clear_active_operation() -> None:
    st.session_state.pop("active_operation", None)


def reset_weekly_plan_running_state(plan_id: int) -> None:
    plan = get_weekly_plan(plan_id)
    if plan is None:
        return
    topics = list_weekly_topics(plan_id)
    generated_count = len([topic for topic in topics if topic.get("generated_article_task_id")])
    if generated_count:
        status = f"已停止，已生成{generated_count}篇"
    elif topics:
        status = "已生成选题"
    else:
        status = "已停止，可重新生成"
    update_weekly_plan(plan_id, {"status": status})


def render_active_operation_recovery() -> None:
    operation = st.session_state.get("active_operation")
    if not operation:
        return
    label = operation.get("label", "生成任务")
    started_at = operation.get("started_at", "")
    st.warning(
        f"{label}可能仍停留在运行状态。"
        "如果你刚刚点击了右上角 Stop，或页面一直显示正在生成，可以先恢复页面状态，再重新点击生成。"
        + (f" 开始时间：{started_at}" if started_at else "")
    )
    cols = st.columns([1, 1, 3])
    with cols[0]:
        if st.button("停止并恢复页面", type="primary", use_container_width=True, key="recover_active_operation"):
            operation_type = operation.get("operation_type", "")
            target_id = operation.get("target_id", "")
            if operation_type == "weekly_plan" and str(target_id).isdigit():
                reset_weekly_plan_running_state(int(target_id))
            clear_active_operation()
            set_flash("已恢复页面状态，可以重新生成。")
            st.rerun()
    with cols[1]:
        if st.button("隐藏提示", use_container_width=True, key="hide_active_operation"):
            clear_active_operation()
            st.rerun()


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
        .publish-cta-card {
            margin: 0.9rem 0 0.35rem;
            padding: 1rem 1.1rem;
            border: 1px solid #d7dde5;
            border-radius: 14px;
            background: #ffffff;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }
        .publish-cta-title {
            margin-bottom: 0.25rem;
            color: #111827;
            font-size: 1.05rem;
            font-weight: 800;
        }
        .publish-cta-desc {
            margin-bottom: 0.75rem;
            color: #64748b;
            font-size: 0.92rem;
            line-height: 1.55;
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


def render_sidebar_nav(current_page: str) -> None:
    active_page = PAGE_PARENT.get(current_page, current_page)
    st.markdown(
        dedent(
            """
            <style>
            div[data-testid="stSidebar"] {
                border-right: 1px solid #e5e7eb;
            }
            div[data-testid="stSidebar"] div[data-testid="stButton"] > button {
                min-height: 46px;
                border-radius: 12px;
                justify-content: flex-start;
                font-weight: 700;
            }
            .workspace-hero {
                padding: 0.2rem 0 0.9rem;
            }
            .workspace-subtitle {
                color: #64748b;
                font-size: 1rem;
                margin-top: -0.4rem;
            }
            .entry-card {
                height: 250px;
                box-sizing: border-box;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                padding: 1.15rem;
                border: 1px solid #334155;
                border-radius: 16px;
                background: rgba(255, 255, 255, 0.02);
                box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
            }
            .entry-card.recommended {
                border-color: #3b82f6;
                background: rgba(59, 130, 246, 0.16);
                box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08);
            }
            .entry-top {
                min-height: 168px;
            }
            .entry-badge-row {
                height: 28px;
                margin-bottom: 0.35rem;
            }
            .entry-badge {
                display: inline-block;
                padding: 0.18rem 0.55rem;
                border-radius: 999px;
                background: #2563eb;
                color: #ffffff;
                font-size: 0.78rem;
                font-weight: 700;
            }
            .entry-title {
                font-size: 1.45rem;
                line-height: 1.25;
                font-weight: 800;
                margin-bottom: 0.65rem;
                color: inherit;
            }
            .entry-desc {
                color: #94a3b8;
                line-height: 1.6;
                font-size: 0.96rem;
            }
            .entry-button {
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 44px;
                width: 100%;
                border: 1px solid #475569;
                border-radius: 10px;
                color: inherit !important;
                text-decoration: none !important;
                font-weight: 750;
                background: rgba(15, 23, 42, 0.16);
            }
            .entry-button:hover {
                border-color: #94a3b8;
                background: rgba(148, 163, 184, 0.12);
            }
            .entry-button.primary {
                border-color: #fb7185;
                background: #e45d73;
                color: #ffffff !important;
            }
            div[data-testid="stMetric"] {
                overflow: hidden;
            }
            div[data-testid="stMetricLabel"] p {
                font-size: 0.82rem !important;
                line-height: 1.25 !important;
                color: #cbd5e1 !important;
            }
            div[data-testid="stMetricValue"] {
                font-size: 1.08rem !important;
                line-height: 1.35 !important;
                white-space: normal !important;
                overflow-wrap: anywhere !important;
                word-break: break-word !important;
            }
            .compact-info-grid {
                display: grid;
                gap: 0.65rem;
                margin: 0.6rem 0 0.9rem;
            }
            .compact-info-grid.cols-2 {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .compact-info-grid.cols-3 {
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }
            .compact-info-grid.cols-4 {
                grid-template-columns: repeat(4, minmax(0, 1fr));
            }
            .compact-info-grid.cols-5 {
                grid-template-columns: repeat(5, minmax(0, 1fr));
            }
            .compact-info-item {
                min-height: 58px;
                padding: 0.55rem 0.65rem;
                border: 1px solid rgba(148, 163, 184, 0.28);
                border-radius: 10px;
                background: rgba(15, 23, 42, 0.16);
                box-sizing: border-box;
            }
            .compact-info-label {
                margin-bottom: 0.28rem;
                color: #cbd5e1;
                font-size: 0.78rem;
                line-height: 1.2;
                font-weight: 650;
            }
            .compact-info-value {
                color: inherit;
                font-size: 0.96rem;
                line-height: 1.35;
                font-weight: 650;
                overflow-wrap: anywhere;
                word-break: break-word;
            }
            .image-chip-row {
                display: flex;
                flex-wrap: wrap;
                gap: 0.4rem;
                margin: 0.35rem 0 0.55rem;
            }
            .image-chip {
                display: inline-flex;
                align-items: center;
                max-width: 100%;
                padding: 0.22rem 0.48rem;
                border: 1px solid rgba(148, 163, 184, 0.35);
                border-radius: 999px;
                background: rgba(15, 23, 42, 0.12);
                font-size: 0.78rem;
                line-height: 1.25;
                color: inherit;
                overflow-wrap: anywhere;
            }
            .image-purpose {
                margin: 0.25rem 0 0.5rem;
                font-size: 0.86rem;
                line-height: 1.5;
                color: #64748b;
            }
            .image-thumb {
                width: 100%;
                height: 150px;
                border-radius: 12px;
                border: 1px solid rgba(148, 163, 184, 0.25);
                object-fit: cover;
                object-position: center;
                display: block;
                background: #f8fafc;
            }
            .image-thumb-empty {
                height: 92px;
                border-radius: 12px;
                border: 1px dashed rgba(148, 163, 184, 0.45);
                display: flex;
                align-items: center;
                justify-content: center;
                color: #64748b;
                background: #f8fafc;
                font-size: 0.9rem;
            }
            @media (max-width: 900px) {
                .entry-card {
                    height: auto;
                    min-height: 230px;
                }
                .entry-top {
                    min-height: 0;
                }
                .compact-info-grid.cols-4,
                .compact-info-grid.cols-5 {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
            }
            .soft-section-title {
                font-size: 1.15rem;
                font-weight: 800;
                margin: 1.5rem 0 0.7rem;
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )
    with st.sidebar:
        st.markdown(f"### {PRODUCT_NAME}")
        st.caption("清晰生成、审核、排版公众号内容")
        st.divider()
        for page in NAV_PAGES:
            if st.button(
                page,
                type="primary" if page == active_page else "secondary",
                use_container_width=True,
                key=f"nav_{page}",
            ):
                go_to_page(page)
                st.rerun()
        if current_page not in NAV_PAGES:
            st.divider()
            st.caption(f"当前流程：{current_page}")


def render_compact_info_grid(items: Sequence[tuple[str, object]], columns: int = 3) -> None:
    safe_columns = max(1, min(columns, 5))
    cells = []
    for label, value in items:
        cells.append(
            "<div class=\"compact-info-item\">"
            f"<div class=\"compact-info-label\">{escape(str(label))}</div>"
            f"<div class=\"compact-info-value\">{escape(str(value or '暂无'))}</div>"
            "</div>"
        )
    st.markdown(
        f"<div class=\"compact-info-grid cols-{safe_columns}\">{''.join(cells)}</div>",
        unsafe_allow_html=True,
    )


def render_page_link_button(
    label: str,
    page: str,
    task_id: str = "",
    knowledge_id: str = "",
    plan_id: str = "",
    primary: bool = False,
) -> None:
    class_name = "page-action-link primary" if primary else "page-action-link"
    st.markdown(
        f'<a class="{class_name}" href="{page_href(page, task_id=task_id, knowledge_id=knowledge_id, plan_id=plan_id)}" target="_self">{label}</a>',
        unsafe_allow_html=True,
    )


def render_publish_preview_card(task_id: str, enabled: bool) -> None:
    st.markdown(
        """
        <div class="publish-cta-card">
          <div class="publish-cta-title">站内排版预览</div>
          <div class="publish-cta-desc">审核通过后，可以在站内查看最终 Markdown、复制图文版内容，并打开 Raphael 做公众号排版预览。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if enabled:
        render_page_link_button("进入站内排版预览", "排版发布页", task_id=task_id, primary=True)
    else:
        st.button("进入站内排版预览", disabled=True, help="审核通过后才能进入排版预览。", use_container_width=True)


def redirect_to_page(page: str, task_id: str = "", knowledge_id: str = "", plan_id: str = "") -> None:
    href = page_href(page, task_id=task_id, knowledge_id=knowledge_id, plan_id=plan_id)
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


def get_existing_columns(conn: DbConn, table_name: str) -> set[str]:
    if conn.kind == "postgres":
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ?
            """,
            (table_name,),
        ).fetchall()
        return {row["column_name"] for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def ensure_columns(conn: DbConn, table_name: str, columns: Mapping[str, str]) -> None:
    existing = get_existing_columns(conn, table_name)
    for column, definition in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id SERIAL PRIMARY KEY
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weekly_plans (
                    id SERIAL PRIMARY KEY
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weekly_topics (
                    id SERIAL PRIMARY KEY
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weekly_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weekly_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                )
                """
            )
        ensure_columns(conn, "tasks", TEXT_COLUMNS)
        ensure_columns(conn, "knowledge_items", KNOWLEDGE_COLUMNS)
        ensure_columns(conn, "weekly_plans", WEEKLY_PLAN_COLUMNS)
        ensure_columns(conn, "weekly_topics", WEEKLY_TOPIC_COLUMNS)
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


def create_task(task: Mapping[str, str]) -> str:
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
    return values["task_id"]


def parse_tags(text: str) -> List[str]:
    tags = [part.strip() for part in re.split(r"[,，;；、\s]+", text or "") if part.strip()]
    result: List[str] = []
    for tag in tags:
        if tag not in result:
            result.append(tag)
    return result


def join_tags(tags: Sequence[str]) -> str:
    return "、".join(tag.strip() for tag in tags if tag and tag.strip())


def normalize_material_tags(raw_tags, existing_tag_names: Sequence[str]) -> List[str]:
    existing = [tag.strip() for tag in existing_tag_names if tag.strip()]
    existing_set = set(existing)
    if isinstance(raw_tags, str):
        candidates = parse_tags(raw_tags)
    elif isinstance(raw_tags, list):
        candidates = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    else:
        candidates = []

    normalized: List[str] = []
    new_count = 0
    for tag in candidates:
        tag = re.sub(r"\s+", "", tag)[:8]
        if not tag or tag in normalized:
            continue
        if tag in existing_set:
            normalized.append(tag)
        elif new_count < 2:
            normalized.append(tag)
            new_count += 1
        if len(normalized) >= 5:
            break
    return normalized


def type_label(type_value: str) -> str:
    return KNOWLEDGE_TYPES.get(type_value, type_value or "未分类")


def insert_row(conn: DbConn, table_name: str, values: Mapping[str, object]) -> int:
    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    if conn.kind == "postgres":
        row = conn.execute(
            f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders}) RETURNING id",
            [values[column] for column in columns],
        ).fetchone()
        return int(row["id"])
    cursor = conn.execute(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
        [values[column] for column in columns],
    )
    return int(cursor.lastrowid)


def update_row(table_name: str, row_id: int, updates: Mapping[str, object], allowed_columns: set[str]) -> None:
    clean_updates = {key: value for key, value in updates.items() if key in allowed_columns}
    if not clean_updates:
        return
    clean_updates["updated_at"] = now_text()
    assignments = ", ".join(f"{key} = ?" for key in clean_updates)
    values = list(clean_updates.values()) + [row_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE {table_name} SET {assignments} WHERE id = ?", values)
        conn.commit()


def list_knowledge_items(
    type_filter: str = "全部",
    tag_query: str = "",
    enabled_filter: str = "全部",
) -> List[Dict[str, str]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM knowledge_items ORDER BY updated_at DESC, id DESC").fetchall()
    items = [row_to_dict(row) for row in rows]
    if type_filter != "全部":
        items = [item for item in items if item.get("type") == type_filter]
    query_tags = parse_tags(tag_query)
    if query_tags:
        items = [
            item
            for item in items
            if set(query_tags).intersection(parse_tags(item.get("tags", "")))
            or any(tag in item.get("title", "") or tag in item.get("content", "") for tag in query_tags)
        ]
    if enabled_filter == "仅启用":
        items = [item for item in items if int(item.get("enabled") or 0) == 1]
    elif enabled_filter == "仅停用":
        items = [item for item in items if int(item.get("enabled") or 0) == 0]
    return items


def get_knowledge_item(knowledge_id: int) -> Optional[Dict[str, str]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (knowledge_id,)).fetchone()
    return row_to_dict(row) if row else None


def create_knowledge_item(values: Mapping[str, object]) -> int:
    title = clean_cell(str(values.get("title", "")))
    content = str(values.get("content", "")).strip()
    if not title:
        raise UserFacingError("请填写知识标题。")
    if not content:
        raise UserFacingError("请填写知识内容。")
    type_value = str(values.get("type", "topic_material"))
    if type_value not in KNOWLEDGE_TYPES:
        type_value = "topic_material"
    timestamp = now_text()
    with get_conn() as conn:
        item_id = insert_row(
            conn,
            "knowledge_items",
            {
                "title": title,
                "content": sanitize_model_text(content),
                "type": type_value,
                "tags": clean_cell(str(values.get("tags", ""))),
                "enabled": 1 if values.get("enabled", True) else 0,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        conn.commit()
    return item_id


def update_knowledge_item(knowledge_id: int, values: Mapping[str, object]) -> None:
    if get_knowledge_item(knowledge_id) is None:
        raise UserFacingError("没有找到知识条目。")
    title = clean_cell(str(values.get("title", "")))
    content = str(values.get("content", "")).strip()
    if not title:
        raise UserFacingError("请填写知识标题。")
    if not content:
        raise UserFacingError("请填写知识内容。")
    type_value = str(values.get("type", "topic_material"))
    if type_value not in KNOWLEDGE_TYPES:
        type_value = "topic_material"
    update_row(
        "knowledge_items",
        knowledge_id,
        {
            "title": title,
            "content": sanitize_model_text(content),
            "type": type_value,
            "tags": clean_cell(str(values.get("tags", ""))),
            "enabled": 1 if values.get("enabled", True) else 0,
        },
        set(KNOWLEDGE_COLUMNS.keys()),
    )


def delete_knowledge_item(knowledge_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM knowledge_items WHERE id = ?", (knowledge_id,))
        conn.commit()
    if st.session_state.get("selected_knowledge_id") == knowledge_id:
        st.session_state.pop("selected_knowledge_id", None)


def set_knowledge_enabled(knowledge_id: int, enabled: bool) -> None:
    update_row("knowledge_items", knowledge_id, {"enabled": 1 if enabled else 0}, set(KNOWLEDGE_COLUMNS.keys()))


def all_knowledge_tags() -> List[str]:
    tags: List[str] = []
    for item in list_knowledge_items():
        for tag in parse_tags(item.get("tags", "")):
            if tag not in tags:
                tags.append(tag)
    return sorted(tags)


def truncate_text(text: str, limit: int = 1200) -> str:
    clean = sanitize_model_text(text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def format_knowledge_items(items: List[Dict[str, str]], limit_per_item: int = 1200) -> str:
    if not items:
        return "暂无匹配知识库内容。"
    blocks = []
    for index, item in enumerate(items, start=1):
        blocks.append(
            "\n".join(
                [
                    f"【知识 {index}】{item.get('title', '未命名')}",
                    f"类型：{type_label(item.get('type', ''))}",
                    f"标签：{item.get('tags', '') or '无'}",
                    "内容：",
                    truncate_text(item.get("content", ""), limit_per_item),
                ]
            )
        )
    return "\n\n".join(blocks)


def format_orm_knowledge_items(items: Sequence[object], limit_per_item: int = 900) -> str:
    if not items:
        return "暂无匹配知识库内容。"
    blocks = []
    for index, item in enumerate(items, start=1):
        title = getattr(item, "title", "未命名")
        tags = getattr(item, "tags", "") or "无"
        summary = getattr(item, "summary", "") or ""
        content = getattr(item, "content", "") or ""
        usage_status = getattr(item, "usage_status", "") or "unused"
        blocks.append(
            "\n".join(
                [
                    f"【已收录内容 {index}】{title}",
                    f"标签：{tags}",
                    f"使用状态：{usage_status}",
                    f"摘要：{summary or truncate_text(content, 180)}",
                    "内容：",
                    truncate_text(content, limit_per_item),
                ]
            )
        )
    return "\n\n".join(blocks)


def build_knowledge_context_for_base(knowledge_base_id: int, selected_item_ids: Optional[Sequence[int]] = None) -> str:
    all_items = [item for item in list_knowledge_contents(knowledge_base_id) if bool(getattr(item, "enabled", True))]
    selected_set = set(int(item_id) for item_id in (selected_item_ids or []))
    if selected_set:
        selected_items = [item for item in all_items if int(item.id) in selected_set]
        supporting_items = [item for item in all_items if int(item.id) not in selected_set][:6]
        items = selected_items + supporting_items
    else:
        items = all_items[:12]
    return format_orm_knowledge_items(items)


def build_selected_items_context(selected_item_ids: Sequence[int]) -> str:
    items = []
    for item_id in selected_item_ids:
        item = get_knowledge_content(int(item_id))
        if item is not None:
            items.append(item)
    return format_orm_knowledge_items(items, limit_per_item=1200) if items else "未选择具体内容。"


def build_history_context(knowledge_base_id: Optional[int] = None, limit: int = 60) -> str:
    lines: List[str] = []
    for task in list_tasks()[: min(limit, 40)]:
        title = task.get("title") or task.get("article_topic") or ""
        if not title:
            continue
        lines.append(
            "｜".join(
                [
                    f"历史稿件：{title}",
                    f"核心角度：{truncate_text(task.get('doctor_viewpoint', ''), 80) or '未记录'}",
                    f"状态：{task.get('status', '') or '未记录'}",
                    f"生成时间：{task.get('created_at', '') or task.get('updated_at', '')}",
                ]
            )
        )
    for topic in list_topic_history(limit=limit, knowledge_base_id=knowledge_base_id):
        lines.append(
            "｜".join(
                [
                    f"历史选题：{topic.topic_title}",
                    f"核心角度：{topic.topic_angle or '未记录'}",
                    f"状态：{topic.status}",
                    f"生成时间：{topic.created_at}",
                ]
            )
        )
    return "\n".join(lines[:limit]) if lines else "暂无历史选题或历史稿件。"


def retrieve_knowledge_items(selected_tags: Sequence[str]) -> List[Dict[str, str]]:
    enabled_items = list_knowledge_items(enabled_filter="仅启用")
    base_items = [item for item in enabled_items if item.get("type") in {"doctor_style", "compliance"}]
    selected_set = set(selected_tags)
    material_items = []
    for item in enabled_items:
        if item.get("type") not in {"topic_material", "reference", "history_article"}:
            continue
        item_tags = set(parse_tags(item.get("tags", "")))
        if not selected_set or selected_set.intersection(item_tags):
            material_items.append(item)
    return (base_items + material_items)[:16]


def build_retrieved_knowledge(selected_tags: Sequence[str]) -> str:
    return format_knowledge_items(retrieve_knowledge_items(selected_tags))


def default_knowledge_base_id() -> Optional[int]:
    bases = list_knowledge_bases()
    if not bases:
        return None
    ranked_bases = sorted(
        bases,
        key=lambda base: (len(list_knowledge_contents(base.id)), base.updated_at or ""),
        reverse=True,
    )
    return ranked_bases[0].id if ranked_bases else None


def knowledge_base_name(knowledge_base_id: object) -> str:
    try:
        base_id = int(knowledge_base_id or 0)
    except (TypeError, ValueError):
        base_id = 0
    if not base_id:
        return "未指定知识库"
    base = orm_get_knowledge_base(base_id)
    return base.name if base else "知识库已删除"


def plan_knowledge_base_id(plan: Mapping[str, object]) -> Optional[int]:
    try:
        base_id = int(plan.get("knowledge_base_id") or 0)
    except (TypeError, ValueError):
        base_id = 0
    return base_id or default_knowledge_base_id()


def ensure_weekly_plans_have_knowledge_base() -> None:
    fallback_id = default_knowledge_base_id()
    if not fallback_id:
        return
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, knowledge_base_id
            FROM weekly_plans
            WHERE knowledge_base_id IS NULL OR knowledge_base_id = '' OR knowledge_base_id = 0
            """
        ).fetchall()
    for row in rows:
        update_weekly_plan(int(row["id"]), {"knowledge_base_id": fallback_id})


def build_weekly_plan_knowledge_context(plan: Mapping[str, object]) -> str:
    base_id = plan_knowledge_base_id(plan)
    if base_id:
        return build_knowledge_context_for_base(base_id)
    return build_retrieved_knowledge(parse_tags(str(plan.get("selected_tags", ""))))


def weekly_plan_display_name(plan: Mapping[str, object]) -> str:
    name = str(plan.get("plan_name", "") or "").strip()
    if name:
        return name
    focus = str(plan.get("weekly_focus", "") or "").strip()
    if focus:
        return focus[:18] + ("..." if len(focus) > 18 else "")
    return f"每周内容计划 {plan.get('id', '')}".strip()


def list_weekly_plans() -> List[Dict[str, str]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM weekly_plans ORDER BY week_start_date DESC, updated_at DESC, id DESC").fetchall()
    return [row_to_dict(row) for row in rows]


def get_weekly_plan(plan_id: int) -> Optional[Dict[str, str]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM weekly_plans WHERE id = ?", (plan_id,)).fetchone()
    return row_to_dict(row) if row else None


def list_weekly_topics(plan_id: int) -> List[Dict[str, str]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM weekly_topics WHERE weekly_plan_id = ? ORDER BY id ASC",
            (plan_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_weekly_topic(topic_id: int) -> Optional[Dict[str, str]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM weekly_topics WHERE id = ?", (topic_id,)).fetchone()
    return row_to_dict(row) if row else None


def create_weekly_plan(values: Mapping[str, object]) -> int:
    weekly_focus = clean_cell(str(values.get("weekly_focus", "")))
    if not weekly_focus:
        raise UserFacingError("请填写本周主题方向。")
    article_count = int(values.get("article_count", 3) or 3)
    article_count = max(1, min(article_count, 6))
    try:
        knowledge_base_id = int(values.get("knowledge_base_id") or 0)
    except (TypeError, ValueError):
        knowledge_base_id = 0
    if not knowledge_base_id:
        knowledge_base_id = default_knowledge_base_id() or 0
    timestamp = now_text()
    with get_conn() as conn:
        plan_id = insert_row(
            conn,
            "weekly_plans",
            {
                "plan_name": clean_cell(str(values.get("plan_name", ""))) or "每周内容计划",
                "week_start_date": clean_cell(str(values.get("week_start_date", ""))),
                "article_count": article_count,
                "weekly_focus": weekly_focus,
                "selected_tags": clean_cell(str(values.get("selected_tags", ""))),
                "knowledge_base_id": knowledge_base_id,
                "generation_mode": clean_cell(str(values.get("generation_mode", ""))) or "AI 自动推荐选题",
                "writing_style": clean_cell(str(values.get("writing_style", ""))) or "温和科普",
                "article_length": clean_cell(str(values.get("article_length", ""))) or "中等1200字",
                "generate_time": clean_cell(str(values.get("generate_time", ""))) or "09:00",
                "after_generate_status": clean_cell(str(values.get("after_generate_status", ""))) or "已生成，待审核",
                "enabled": 1 if values.get("enabled", True) else 0,
                "status": clean_cell(str(values.get("status", ""))) or "待生成选题",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        conn.commit()
    return plan_id


def update_weekly_plan(plan_id: int, updates: Mapping[str, object]) -> None:
    update_row("weekly_plans", plan_id, updates, set(WEEKLY_PLAN_COLUMNS.keys()))


def toggle_weekly_plan_enabled(plan_id: int, enabled: bool) -> None:
    update_weekly_plan(
        plan_id,
        {
            "enabled": 1 if enabled else 0,
            "status": "待生成选题" if enabled else "已暂停",
        },
    )


def normalize_weekly_topics(raw_topics, article_count: int) -> List[Dict[str, str]]:
    if not isinstance(raw_topics, list):
        raise UserFacingError("DeepSeek 没有返回 topics 数组，请重试。")
    topics: List[Dict[str, str]] = []
    for item in raw_topics[:article_count]:
        if not isinstance(item, dict):
            continue
        title = sanitize_model_text(str(item.get("title", ""))).strip()
        if not title:
            continue
        raw_risk_tags = item.get("risk_tags", [])
        if isinstance(raw_risk_tags, list):
            risk_tags = join_tags(str(tag) for tag in raw_risk_tags)
        else:
            risk_tags = clean_cell(str(raw_risk_tags))
        topics.append(
            {
                "title": title,
                "target_reader": sanitize_model_text(str(item.get("target_reader", ""))).strip(),
                "core_viewpoint": sanitize_model_text(str(item.get("core_viewpoint", ""))).strip(),
                "article_angle": sanitize_model_text(str(item.get("article_angle", ""))).strip(),
                "risk_tags": risk_tags,
                "reason": sanitize_model_text(str(item.get("reason", ""))).strip(),
            }
        )
    if not topics:
        raise UserFacingError("DeepSeek 没有返回有效选题，请重试。")
    return topics


def store_weekly_topics(plan_id: int, plan: Mapping[str, object], topics: List[Dict[str, str]]) -> None:
    timestamp = now_text()
    base_id = plan_knowledge_base_id(plan)
    stored_topics: List[Dict[str, object]] = []
    with get_conn() as conn:
        conn.execute("DELETE FROM weekly_topics WHERE weekly_plan_id = ?", (plan_id,))
        conn.commit()

    for topic in topics:
        history = create_topic_history(
            topic_title=topic["title"],
            topic_angle=topic["article_angle"],
            knowledge_base_id=base_id,
            referenced_items=json.dumps(
                {
                    "source": "weekly_plan",
                    "plan_id": plan_id,
                    "plan_name": weekly_plan_display_name(plan),
                },
                ensure_ascii=False,
            ),
            status="planned",
        )
        stored_topics.append({**topic, "topic_history_id": history.id})

    with get_conn() as conn:
        for topic in stored_topics:
            insert_row(
                conn,
                "weekly_topics",
                {
                    "weekly_plan_id": plan_id,
                    "title": topic["title"],
                    "target_reader": topic["target_reader"],
                    "core_viewpoint": topic["core_viewpoint"],
                    "article_angle": topic["article_angle"],
                    "risk_tags": topic["risk_tags"],
                    "reason": topic["reason"],
                    "generated_article_task_id": "",
                    "topic_history_id": topic["topic_history_id"],
                    "status": "待生成文章",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
        conn.commit()


def generate_topics_for_weekly_plan(plan_id: int) -> int:
    plan = get_weekly_plan(plan_id)
    if plan is None:
        raise UserFacingError("没有找到每周计划。")
    if int(plan.get("enabled") or 0) != 1:
        raise UserFacingError("这个计划已暂停，请先启用后再生成。")
    effective_base_id = plan_knowledge_base_id(plan)
    if effective_base_id and int(plan.get("knowledge_base_id") or 0) != effective_base_id:
        update_weekly_plan(plan_id, {"knowledge_base_id": effective_base_id})
        plan = get_weekly_plan(plan_id) or plan
    try:
        update_weekly_plan(plan_id, {"status": "生成选题中"})
        retrieved_knowledge = build_weekly_plan_knowledge_context(plan)
        history_context = build_history_context(plan_knowledge_base_id(plan))
        config = get_config()
        prompt = render_template(
            read_prompt("weekly_topics_prompt.txt"),
            {
                "plan_name": weekly_plan_display_name(plan),
                "week_start_date": plan.get("week_start_date", ""),
                "article_count": str(plan.get("article_count", 3)),
                "weekly_focus": plan.get("weekly_focus", ""),
                "selected_tags": plan.get("selected_tags", ""),
                "knowledge_base_name": knowledge_base_name(plan.get("knowledge_base_id")),
                "generation_mode": plan.get("generation_mode", "AI 自动推荐选题"),
                "writing_style": plan.get("writing_style", ""),
                "article_length": plan.get("article_length", ""),
                "retrieved_knowledge": retrieved_knowledge,
                "history_context": history_context,
            },
        )
        data = extract_json_object(call_deepseek(config, prompt, temperature=0.45))
        topics = normalize_weekly_topics(data.get("topics", []), int(plan.get("article_count") or 3))
        store_weekly_topics(plan_id, plan, topics)
        update_weekly_plan(plan_id, {"status": "已生成选题"})
        return plan_id
    except Exception:
        update_weekly_plan(plan_id, {"status": "生成选题失败"})
        raise


def generate_weekly_topics(values: Mapping[str, object]) -> int:
    plan_id = create_weekly_plan({**values, "status": "待生成选题"})
    return generate_topics_for_weekly_plan(plan_id)


def update_weekly_topic(topic_id: int, updates: Mapping[str, object]) -> None:
    update_row("weekly_topics", topic_id, updates, set(WEEKLY_TOPIC_COLUMNS.keys()))


def create_article_from_weekly_topic(topic_id: int) -> str:
    topic = get_weekly_topic(topic_id)
    if topic is None:
        raise UserFacingError("没有找到选题。")
    if topic.get("generated_article_task_id") and get_task(topic["generated_article_task_id"]):
        return topic["generated_article_task_id"]
    plan = get_weekly_plan(int(topic["weekly_plan_id"]))
    if plan is None:
        raise UserFacingError("没有找到每周计划。")
    retrieved_knowledge = build_weekly_plan_knowledge_context(plan)
    settings = get_app_settings_map()
    base_id = plan_knowledge_base_id(plan)
    base_name = knowledge_base_name(base_id)
    task_id = f"weekly_{plan['id']}_{topic['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    create_task(
        {
            "task_id": task_id,
            "article_topic": topic["title"],
            "target_reader": topic["target_reader"],
            "doctor_name": settings.get("ip_name", "") or "审核后署名",
            "safe_scene": (
                f"来自计划「{weekly_plan_display_name(plan)}」的脱敏科普选题：{topic['title']}。\n"
                f"使用知识库：{base_name}。\n"
                f"文章角度：{topic['article_angle']}。\n"
                "不要写成真实来访者故事，不包含任何原始咨询记录。"
            ),
            "common_misunderstanding": "避免把心理困扰简单归因为性格、自控力或道德问题。",
            "doctor_viewpoint": (
                f"{topic['core_viewpoint']}\n\n"
                f"文章切入角度：{topic['article_angle']}"
            ),
            "forbidden_info": "不要出现真实来访者故事；不要诊断；不要给药物建议；不要承诺疗效；不要制造焦虑。",
            "risk_tags": topic["risk_tags"] or "无",
            "writing_style": plan["writing_style"],
            "article_length": plan["article_length"],
            "image_style": "温暖治愈",
            "layout_style": "温暖治愈",
        }
    )
    update_task(task_id, {"retrieved_knowledge": retrieved_knowledge})
    try:
        next_status = plan.get("after_generate_status") or "已生成，待审核"
        generate_article(task_id, next_status=str(next_status))
    except Exception:
        update_weekly_topic(topic_id, {"generated_article_task_id": task_id, "status": "生成文章失败"})
        raise
    update_weekly_topic(topic_id, {"generated_article_task_id": task_id, "status": "已生成文章"})
    task = get_task(task_id)
    if task:
        draft = upsert_article_draft_from_legacy_task(
            legacy_task_id=task_id,
            title=task.get("title") or topic["title"],
            digest=task.get("digest", ""),
            markdown=task.get("original_markdown") or task.get("markdown") or "",
            source_type="weekly_plan",
            knowledge_base_id=base_id,
            referenced_items=json.dumps(
                {
                    "plan_id": plan.get("id"),
                    "plan_name": weekly_plan_display_name(plan),
                    "topic_id": topic.get("id"),
                },
                ensure_ascii=False,
            ),
            risk_level=task.get("risk_level", ""),
            risk_report=task.get("risk_report", ""),
            cover_prompt=task.get("cover_image_prompt", ""),
            duplicate_check_result="来自每周计划选题，已参考历史稿件和历史选题避重。",
            topic_angle=topic.get("article_angle", ""),
            status="doctor_review_pending",
        )
        try:
            topic_history_id = int(topic.get("topic_history_id") or 0)
        except (TypeError, ValueError):
            topic_history_id = 0
        if topic_history_id:
            update_topic_history_generated_article(topic_history_id, draft.id, status="generated")
    return task_id


def batch_create_articles_for_plan(plan_id: int) -> None:
    topics = list_weekly_topics(plan_id)
    if not topics:
        raise UserFacingError("这个计划还没有选题。")
    pending = [topic for topic in topics if not topic.get("generated_article_task_id")]
    if not pending:
        return
    for topic in pending:
        create_article_from_weekly_topic(int(topic["id"]))


def run_weekly_plan_to_articles(plan_id: int) -> None:
    generate_topics_for_weekly_plan(plan_id)
    update_weekly_plan(plan_id, {"status": "生成文章中"})
    batch_create_articles_for_plan(plan_id)
    update_weekly_plan(plan_id, {"status": "已生成文章"})


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


def organize_today_material(raw_material: str, knowledge_base_name: str) -> Dict[str, object]:
    material = sanitize_model_text(raw_material).strip()
    if not material:
        raise UserFacingError("请先粘贴今日内容。")
    if len(material) < 10:
        raise UserFacingError("今日内容太短，请多写一点，方便 AI 整理。")

    settings = get_app_settings_map()
    existing_tag_names = [tag.name for tag in list_tags()]
    prompt = render_template(
        read_prompt("material_organize_prompt.txt"),
        {
            "ip_role": settings.get("ip_role", "心理医生"),
            "existing_tags": join_tags(existing_tag_names) or "暂无已有标签",
            "knowledge_base_name": knowledge_base_name,
            "raw_material": material,
        },
    )
    data = extract_json_object(call_deepseek(get_config(), prompt, temperature=0.25))
    tags = normalize_material_tags(data.get("tags", []), existing_tag_names)
    topic_ideas_raw = data.get("topic_ideas", [])
    if isinstance(topic_ideas_raw, list):
        topic_ideas = [sanitize_model_text(str(item)).strip() for item in topic_ideas_raw if str(item).strip()][:5]
    else:
        topic_ideas = parse_tags(str(topic_ideas_raw))[:5]
    title = sanitize_model_text(str(data.get("title", ""))).strip()
    if not title:
        title = material[:24] + ("..." if len(material) > 24 else "")
    return {
        "title": title,
        "summary": sanitize_model_text(str(data.get("summary", ""))).strip()[:220],
        "core_viewpoint": sanitize_model_text(str(data.get("core_viewpoint", ""))).strip(),
        "tags": tags,
        "topic_ideas": topic_ideas,
        "suggested_knowledge_base": sanitize_model_text(str(data.get("suggested_knowledge_base", knowledge_base_name))).strip(),
        "risk_level": sanitize_model_text(str(data.get("risk_level", "低"))).strip() or "低",
        "raw_material": material,
    }


def normalize_knowledge_topics(raw_topics, article_count: int = 5) -> List[Dict[str, object]]:
    if not isinstance(raw_topics, list):
        raise UserFacingError("DeepSeek 没有返回 topics 数组，请重试。")
    topics: List[Dict[str, object]] = []
    for item in raw_topics[:article_count]:
        if not isinstance(item, dict):
            continue
        title = sanitize_model_text(str(item.get("title", ""))).strip()
        if not title:
            continue
        raw_risk_tags = item.get("risk_tags", [])
        if isinstance(raw_risk_tags, list):
            risk_tags = [sanitize_model_text(str(tag)).strip() for tag in raw_risk_tags if str(tag).strip()]
        else:
            risk_tags = parse_tags(str(raw_risk_tags))
        raw_refs = item.get("referenced_items", [])
        if isinstance(raw_refs, list):
            referenced_items = [sanitize_model_text(str(ref)).strip() for ref in raw_refs if str(ref).strip()]
        else:
            referenced_items = parse_tags(str(raw_refs))
        topics.append(
            {
                "title": title,
                "target_reader": sanitize_model_text(str(item.get("target_reader", ""))).strip(),
                "core_viewpoint": sanitize_model_text(str(item.get("core_viewpoint", ""))).strip(),
                "topic_angle": sanitize_model_text(str(item.get("topic_angle", item.get("article_angle", "")))).strip(),
                "duplicate_check_result": sanitize_model_text(str(item.get("duplicate_check_result", ""))).strip(),
                "referenced_items": referenced_items,
                "risk_tags": risk_tags,
                "reason": sanitize_model_text(str(item.get("reason", ""))).strip(),
            }
        )
    if not topics:
        raise UserFacingError("DeepSeek 没有返回有效选题，请重试。")
    return topics


def generate_knowledge_topics(
    *,
    knowledge_base_id: int,
    generation_mode: str,
    user_topic: str = "",
    target_reader: str = "",
    selected_item_ids: Optional[Sequence[int]] = None,
    writing_style: str = "温和科普",
    article_length: str = "中等1200字",
    article_count: int = 5,
) -> List[Dict[str, object]]:
    base = orm_get_knowledge_base(knowledge_base_id)
    if base is None:
        raise UserFacingError("请先选择知识库。")
    selected_item_ids = [int(item_id) for item_id in (selected_item_ids or [])]
    retrieved_knowledge = build_knowledge_context_for_base(knowledge_base_id, selected_item_ids)
    selected_items_context = build_selected_items_context(selected_item_ids)
    history_context = build_history_context(knowledge_base_id)
    settings = get_app_settings_map()
    prompt = render_template(
        read_prompt("knowledge_topics_prompt.txt"),
        {
            "ip_role": settings.get("ip_role", "心理医生"),
            "generation_mode": generation_mode,
            "knowledge_base_name": base.name,
            "user_topic": sanitize_model_text(user_topic).strip() or "未指定，由 AI 基于知识库推荐",
            "target_reader": sanitize_model_text(target_reader).strip() or settings.get("default_target_reader", "公众号读者"),
            "writing_style": writing_style,
            "article_length": article_length,
            "retrieved_knowledge": retrieved_knowledge,
            "selected_items": selected_items_context,
            "history_context": history_context,
        },
    )
    data = extract_json_object(call_deepseek(get_config(), prompt, temperature=0.45))
    topics = normalize_knowledge_topics(data.get("topics", []), article_count)
    for topic in topics:
        history = create_topic_history(
            topic_title=str(topic["title"]),
            topic_angle=str(topic.get("topic_angle", "")),
            knowledge_base_id=knowledge_base_id,
            referenced_items=json.dumps(topic.get("referenced_items", []), ensure_ascii=False),
            status="suggested",
        )
        topic["topic_history_id"] = history.id
        topic["knowledge_base_id"] = knowledge_base_id
        topic["retrieved_knowledge"] = retrieved_knowledge
    return topics


def create_article_task_from_knowledge_topic(
    *,
    knowledge_base_id: int,
    title: str,
    target_reader: str,
    core_viewpoint: str,
    topic_angle: str,
    risk_tags: object = "",
    referenced_items: Optional[Sequence[str]] = None,
    retrieved_knowledge: str = "",
    duplicate_check_result: str = "",
    writing_style: str = "温和科普",
    article_length: str = "中等1200字",
    image_style: str = "温暖治愈",
    layout_style: str = "温暖治愈",
    topic_history_id: Optional[int] = None,
) -> str:
    base = orm_get_knowledge_base(knowledge_base_id)
    if base is None:
        raise UserFacingError("知识库不存在。")
    settings = get_app_settings_map()
    risk_text = join_tags(risk_tags) if not isinstance(risk_tags, str) else risk_tags
    refs = [str(ref).strip() for ref in (referenced_items or []) if str(ref).strip()]
    topic = sanitize_model_text(title).strip()
    if not topic:
        raise UserFacingError("选题标题不能为空。")
    task_id = f"kb_{knowledge_base_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    knowledge_text = retrieved_knowledge or build_knowledge_context_for_base(knowledge_base_id)
    create_task(
        {
            "task_id": task_id,
            "article_topic": topic,
            "target_reader": target_reader or settings.get("default_target_reader", "公众号读者"),
            "doctor_name": settings.get("ip_name", "") or "审核后署名",
            "safe_scene": (
                f"基于知识库「{base.name}」生成的脱敏科普选题：{topic}。\n"
                f"文章角度：{topic_angle or '围绕主题做通用科普'}。\n"
                "不要写成真实个案，不包含任何原始咨询记录或可识别身份信息。"
            ),
            "common_misunderstanding": "避免简单归因、制造焦虑或使用羞辱性表达。",
            "doctor_viewpoint": (
                f"{core_viewpoint or '基于知识库内容进行温和、专业、可执行的科普。'}\n\n"
                f"文章角度：{topic_angle or '未指定'}\n"
                f"参考内容：{join_tags(refs) or '知识库综合参考'}\n"
                f"重复检查：{duplicate_check_result or '已参考历史标题和角度进行避重'}"
            ),
            "forbidden_info": "不要出现真实故事；不要诊断；不要给药物建议；不要承诺疗效；不要制造焦虑；不要使用可识别身份信息。",
            "risk_tags": risk_text or "无",
            "writing_style": writing_style,
            "article_length": article_length,
            "image_style": image_style or "温暖治愈",
            "layout_style": layout_style or "温暖治愈",
        }
    )
    update_task(task_id, {"retrieved_knowledge": knowledge_text})
    generate_article(task_id, next_status="已生成，待审核")
    task = get_task(task_id)
    if task:
        draft = upsert_article_draft_from_legacy_task(
            legacy_task_id=task_id,
            title=task.get("title") or topic,
            digest=task.get("digest", ""),
            markdown=task.get("original_markdown") or task.get("markdown") or "",
            source_type="knowledge_base",
            knowledge_base_id=knowledge_base_id,
            referenced_items=json.dumps(refs, ensure_ascii=False),
            risk_level=task.get("risk_level", ""),
            risk_report=task.get("risk_report", ""),
            cover_prompt=task.get("cover_image_prompt", ""),
            duplicate_check_result=duplicate_check_result,
            topic_angle=topic_angle,
            status="doctor_review_pending",
        )
        if topic_history_id:
            update_topic_history_generated_article(int(topic_history_id), draft.id, status="generated")
    return task_id


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


def ensure_markdown_requirements(markdown: str, cover_prompt: str, image_prompts: List[Dict[str, str]]) -> str:
    text = sanitize_model_text(markdown).strip()
    if not text:
        text = "请在这里补充公众号正文。"
    if DISCLAIMER_AI not in text:
        text = text.rstrip() + "\n\n" + DISCLAIMER_AI
    if DISCLAIMER_HEALTH not in text:
        text = text.rstrip() + "\n" + DISCLAIMER_HEALTH
    return text.strip()


def image_placeholder(slot_key: str) -> str:
    return "{{image:" + slot_key + "}}"


def markdown_placeholders(markdown: str) -> set[str]:
    return {match.group(1).strip() for match in IMAGE_PLACEHOLDER_RE.finditer(markdown or "")}


def remove_image_placeholder_from_markdown(markdown: str, slot_key: str) -> str:
    if not slot_key:
        return markdown
    placeholder_pattern = re.compile(r"\n{0,2}\{\{\s*image\s*:\s*" + re.escape(slot_key) + r"\s*\}\}\n{0,2}")
    return cleanup_markdown_spacing(placeholder_pattern.sub("\n\n", markdown or ""))


def heading_level(line: str) -> int:
    match = re.match(r"^\s*(#{1,6})\s+", line or "")
    return len(match.group(1)) if match else 0


def heading_text(line: str) -> str:
    text = re.sub(r"^\s*#{1,6}\s*", "", line or "").strip()
    text = re.sub(r"[*_`>]+", "", text)
    return text.strip()


def normalize_section_text(text: str) -> str:
    return re.sub(r"[\s#*_`>《》“”\"'：:，,。！？!?、|｜\-—（）()【】\[\]]+", "", text or "").lower()


def content_heading_indices(lines: Sequence[str]) -> List[int]:
    indices = [idx for idx, line in enumerate(lines) if heading_level(line) > 0]
    if len(indices) <= 1:
        return indices
    first_idx = indices[0]
    first_is_leading = all(not line.strip() for line in lines[:first_idx])
    if first_is_leading and heading_level(lines[first_idx]) <= 2:
        return indices[1:]
    return indices


def find_related_section_heading(lines: Sequence[str], related_section_title: str) -> Optional[int]:
    target = normalize_section_text(related_section_title)
    if not target:
        return None
    for idx in content_heading_indices(lines):
        current = normalize_section_text(heading_text(lines[idx]))
        if not current:
            continue
        if target == current or target in current or current in target:
            return idx
    return None


def normalize_prompt_line(line: str) -> str:
    text = line.strip()
    if text.startswith(">"):
        text = text[1:].strip()
    return text.strip()


def classify_image_prompt_line(line: str) -> Optional[tuple[str, str]]:
    text = normalize_prompt_line(line)
    if not text:
        return None
    has_image_keyword = any(keyword in text for keyword in ["图片提示词", "封面图提示词", "正文配图提示词", "配图提示词"])
    simple_inline = bool(re.match(r"^正文配图\s*\d*\s*[:：]", text))
    if not has_image_keyword and not simple_inline:
        return None
    if "封面" in text:
        role = "cover"
    elif "备用" in text:
        role = "backup"
    else:
        role = "inline"
    prompt = ""
    colon_match = re.search(r"[:：]\s*(.+)$", text)
    if colon_match:
        prompt = colon_match.group(1).strip()
    else:
        bracket_match = re.search(r"[】\]]\s*(.+)$", text)
        if bracket_match:
            prompt = bracket_match.group(1).strip()
    if prompt in {"", "】", "]"}:
        prompt = ""
    return role, prompt


def cleanup_markdown_spacing(markdown: str) -> str:
    lines = [line.rstrip() for line in markdown.splitlines()]
    output: List[str] = []
    blank_count = 0
    for line in lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 2:
                output.append("")
            continue
        blank_count = 0
        output.append(line)
    text = "\n".join(output).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_image_prompts_from_markdown(markdown: str) -> Dict[str, object]:
    lines = (markdown or "").splitlines()
    output: List[str] = []
    inline_prompts: List[Dict[str, str]] = []
    backup_prompts: List[Dict[str, str]] = []
    cover_prompt = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        classified = classify_image_prompt_line(line)
        if not classified:
            output.append(line)
            index += 1
            continue

        role, prompt = classified
        next_index = index + 1
        if not prompt:
            collected: List[str] = []
            while next_index < len(lines):
                candidate_raw = lines[next_index]
                candidate = normalize_prompt_line(candidate_raw)
                if not candidate:
                    next_index += 1
                    break
                if classify_image_prompt_line(candidate_raw) or candidate.startswith("#"):
                    break
                if candidate_raw.lstrip().startswith(">") or len(collected) == 0:
                    collected.append(candidate)
                    next_index += 1
                    if not candidate_raw.lstrip().startswith(">"):
                        break
                    continue
                break
            prompt = " ".join(collected).strip()

        if prompt:
            if role == "cover" and not cover_prompt:
                cover_prompt = prompt
            elif role == "backup":
                backup_prompts.append({"prompt": prompt})
            else:
                slot_key = f"inline_{len(inline_prompts) + 1}"
                inline_prompts.append({"slot_key": slot_key, "prompt": prompt})
                if len(inline_prompts) <= 2:
                    output.append(image_placeholder(slot_key))
                else:
                    backup_prompts.append({"prompt": prompt})
        index = max(next_index, index + 1)

    return {
        "clean_markdown": cleanup_markdown_spacing("\n".join(output)),
        "cover_prompt": cover_prompt,
        "inline_prompts": inline_prompts[:2],
        "backup_prompts": backup_prompts,
    }


def insert_image_placeholder(
    markdown: str,
    slot_key: str,
    insert_position: str,
    related_section_title: str = "",
    replace_existing: bool = False,
) -> str:
    if slot_key in markdown_placeholders(markdown):
        if not replace_existing:
            return markdown
        markdown = remove_image_placeholder_from_markdown(markdown, slot_key)
    if insert_position in {"cover_only", "not_inserted"}:
        return markdown
    placeholder = image_placeholder(slot_key)
    lines = markdown.splitlines()
    if not lines:
        return placeholder

    def insert_after_line(line_index: int) -> str:
        new_lines = lines[: line_index + 1] + ["", placeholder, ""] + lines[line_index + 1 :]
        return cleanup_markdown_spacing("\n".join(new_lines))

    related_heading_index = find_related_section_heading(lines, related_section_title)
    if related_heading_index is not None:
        return insert_after_line(related_heading_index)

    if insert_position == "after_heading_1" or insert_position == "after_heading_2":
        target_count = 1 if insert_position == "after_heading_1" else 2
        headings = content_heading_indices(lines)
        if len(headings) >= target_count:
            return insert_after_line(headings[target_count - 1])

    if insert_position == "before_ending":
        for idx, line in enumerate(lines):
            if DISCLAIMER_AI in line or DISCLAIMER_HEALTH in line:
                new_lines = lines[:idx] + [placeholder, ""] + lines[idx:]
                return cleanup_markdown_spacing("\n".join(new_lines))

    # after_intro: insert after the first non-heading paragraph.
    started = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("{{image:"):
            continue
        started = True
        if started:
            return insert_after_line(idx)
    return cleanup_markdown_spacing(markdown + "\n\n" + placeholder)


def insert_cover_placeholder(markdown: str, slot_key: str = "cover") -> str:
    if slot_key in markdown_placeholders(markdown):
        return markdown
    placeholder = image_placeholder(slot_key)
    lines = (markdown or "").splitlines()
    if not lines:
        return placeholder
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            new_lines = lines[: index + 1] + ["", placeholder, ""] + lines[index + 1 :]
            return cleanup_markdown_spacing("\n".join(new_lines))
    return cleanup_markdown_spacing(placeholder + "\n\n" + (markdown or ""))


def apply_default_image_placeholders(markdown: str, image_records: Sequence[Mapping[str, object]]) -> str:
    text = markdown
    for record in image_records:
        if record.get("image_role") != "inline":
            continue
        params = record.get("visual_params", {})
        if isinstance(params, str):
            params = visual_params_dict(params)
        if not isinstance(params, Mapping):
            params = {}
        text = insert_image_placeholder(
            text,
            str(record.get("slot_key", "")),
            str(record.get("insert_position", "not_inserted")),
            str(params.get("related_section_title") or params.get("section") or ""),
            replace_existing=True,
        )
    return text


def image_related_section_title(image) -> str:
    params = visual_params_dict(image.visual_params)
    return str(params.get("related_section_title") or params.get("section") or "")


def default_image_settings() -> Dict[str, str]:
    settings = get_app_settings_map()
    return {
        "provider": get_runtime_setting("IMAGE_PROVIDER", settings.get("image_provider", "dummy") or "dummy"),
        "model": get_runtime_setting("IMAGE_MODEL", settings.get("image_model", "") or ""),
        "cover_aspect_ratio": get_runtime_setting("DEFAULT_COVER_ASPECT_RATIO", settings.get("default_cover_aspect_ratio", "2.35:1") or "2.35:1"),
        "inline_aspect_ratio": get_runtime_setting("DEFAULT_INLINE_ASPECT_RATIO", settings.get("default_inline_aspect_ratio", "16:9") or "16:9"),
        "style_preset": get_runtime_setting("DEFAULT_IMAGE_STYLE_PRESET", settings.get("default_image_style_preset", "温和治愈插画") or "温和治愈插画"),
    }


def visual_params_json(value: object) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "{}"


def visual_params_dict(value: object) -> Dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def normalize_image_plan_record(
    *,
    image_role: str,
    slot_key: str,
    data: Mapping[str, object],
    defaults: Mapping[str, str],
    insert_position: str,
) -> Dict[str, object]:
    aspect_ratio = str(data.get("aspect_ratio") or (defaults["cover_aspect_ratio"] if image_role == "cover" else defaults["inline_aspect_ratio"]))
    visual_params = visual_params_dict(data.get("visual_params", {}))
    if data.get("scene_purpose"):
        visual_params["scene_purpose"] = sanitize_model_text(str(data.get("scene_purpose", ""))).strip()
    if data.get("related_section_title"):
        visual_params["related_section_title"] = sanitize_model_text(str(data.get("related_section_title", ""))).strip()
    return {
        "image_role": image_role,
        "slot_key": slot_key,
        "prompt": sanitize_model_text(str(data.get("prompt", ""))).strip(),
        "negative_prompt": sanitize_model_text(str(data.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT))).strip() or DEFAULT_NEGATIVE_PROMPT,
        "provider": defaults["provider"],
        "model": defaults["model"],
        "local_path": "",
        "public_url": "",
        "alt_text": sanitize_model_text(str(data.get("alt_text", ""))).strip() or sanitize_model_text(str(data.get("prompt", ""))).strip()[:80],
        "caption": sanitize_model_text(str(data.get("caption", ""))).strip(),
        "insert_position": str(data.get("insert_position") or insert_position),
        "aspect_ratio": aspect_ratio if aspect_ratio in IMAGE_ASPECT_RATIOS else ("2.35:1" if image_role == "cover" else "16:9"),
        "style_preset": str(data.get("style_preset") or defaults["style_preset"]),
        "visual_params": visual_params_json(visual_params),
        "selected": True,
        "status": "prompt_ready" if image_role != "inline" else "not_inserted",
        "error_message": "",
    }


def image_prompts_to_plan_items(image_prompts: Sequence[Mapping[str, str]]) -> tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    inline_items: List[Dict[str, object]] = []
    backup_items: List[Dict[str, object]] = []
    for item in image_prompts:
        position = str(item.get("position", ""))
        prompt = str(item.get("prompt", "")).strip()
        if not prompt or "封面" in position:
            continue
        target = inline_items if len(inline_items) < 2 else backup_items
        target.append({"prompt": prompt, "caption": "", "alt_text": prompt[:80]})
    return inline_items, backup_items


def build_image_records_from_generation(data: Mapping[str, object], extracted: Mapping[str, object], legacy_image_prompts: Sequence[Mapping[str, str]], cover_prompt: str) -> List[Dict[str, object]]:
    defaults = default_image_settings()
    image_plan = data.get("image_plan", {})
    if not isinstance(image_plan, dict):
        image_plan = {}
    records: List[Dict[str, object]] = []

    cover_data = image_plan.get("cover", {}) if isinstance(image_plan.get("cover", {}), dict) else {}
    extracted_cover = str(extracted.get("cover_prompt", "") or "")
    final_cover_prompt = str(cover_data.get("prompt") or cover_prompt or extracted_cover).strip()
    if final_cover_prompt:
        records.append(
            normalize_image_plan_record(
                image_role="cover",
                slot_key="cover",
                data={**cover_data, "prompt": final_cover_prompt},
                defaults=defaults,
                insert_position="cover_only",
            )
        )

    inline_from_plan = image_plan.get("inline_images", [])
    backup_from_plan = image_plan.get("backup_images", [])
    if not isinstance(inline_from_plan, list):
        inline_from_plan = []
    if not isinstance(backup_from_plan, list):
        backup_from_plan = []
    extracted_inline = extracted.get("inline_prompts", [])
    extracted_backup = extracted.get("backup_prompts", [])
    if not isinstance(extracted_inline, list):
        extracted_inline = []
    if not isinstance(extracted_backup, list):
        extracted_backup = []
    legacy_inline, legacy_backup = image_prompts_to_plan_items(legacy_image_prompts)

    inline_candidates = [item for item in inline_from_plan if isinstance(item, dict)] or extracted_inline or legacy_inline
    backup_candidates = [item for item in backup_from_plan if isinstance(item, dict)] + list(extracted_backup or []) + legacy_backup
    max_inline_count = 6 if inline_from_plan else 2
    default_positions = ["after_intro", "after_heading_1", "after_heading_2", "before_ending", "after_heading_2", "before_ending"]
    for index, item in enumerate(inline_candidates[:max_inline_count], start=1):
        slot_key = str(item.get("slot_key") or f"inline_{index}")
        records.append(
            normalize_image_plan_record(
                image_role="inline",
                slot_key=slot_key,
                data=item,
                defaults=defaults,
                insert_position=default_positions[min(index - 1, len(default_positions) - 1)],
            )
        )
    extra_inline = inline_candidates[max_inline_count:]
    for index, item in enumerate((list(extra_inline) + list(backup_candidates))[:2], start=1):
        records.append(
            normalize_image_plan_record(
                image_role="backup",
                slot_key=str(item.get("slot_key") or f"backup_{index}"),
                data=item,
                defaults=defaults,
                insert_position="not_inserted",
            )
        )
    return [record for record in records if str(record.get("prompt", "")).strip()]


def prune_extra_backup_images(article_draft_id: int, max_count: int = 2) -> None:
    backups = [image for image in list_generated_images(article_draft_id) if image.image_role == "backup"]
    backups.sort(key=lambda image: image.id)
    for image in backups[max_count:]:
        delete_generated_image(image.id)


def legacy_image_prompts_from_records(records: Sequence[Mapping[str, object]]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for record in records:
        role = record.get("image_role")
        if role == "cover":
            position = "封面图"
        elif role == "inline":
            position = "正文配图 " + str(record.get("slot_key", "")).replace("inline_", "")
        else:
            position = "备用图"
        result.append({"position": position, "prompt": str(record.get("prompt", ""))})
    return result


def sync_image_status_from_markdown(article_draft_id: int, markdown: str) -> None:
    placeholders = markdown_placeholders(markdown)
    for image in list_generated_images(article_draft_id):
        if image.image_role == "cover":
            if image.slot_key in placeholders:
                update_generated_image(image.id, status="selected", selected=True)
            continue
        if image.image_role != "inline":
            continue
        if image.slot_key in placeholders and image.status in {"prompt_ready", "not_inserted", "inserted"}:
            update_generated_image(image.id, status="inserted", selected=True)
        elif image.slot_key not in placeholders and image.status in {"prompt_ready", "not_inserted", "inserted"}:
            update_generated_image(image.id, status="not_inserted")


def sync_image_records_for_task(task_id: str, image_records: Sequence[Mapping[str, object]], markdown: str) -> None:
    draft = sync_article_draft_from_task(task_id)
    if draft is None:
        return
    replace_generated_images(draft.id, image_records)
    sync_image_status_from_markdown(draft.id, markdown)


def ensure_image_records_for_task(task_id: str) -> Optional[object]:
    task = get_task(task_id)
    if task is None:
        return None
    draft = sync_article_draft_from_task(task_id)
    if draft is None:
        return None
    existing_images = list_generated_images(draft.id)
    markdown = task.get("original_markdown") or task.get("markdown") or ""
    if existing_images:
        prune_extra_backup_images(draft.id)
        sync_image_status_from_markdown(draft.id, markdown)
        return draft

    extracted = extract_image_prompts_from_markdown(markdown)
    cleaned_markdown = ensure_markdown_requirements(str(extracted.get("clean_markdown", markdown)), "", [])
    cover_prompt = task.get("cover_image_prompt", "") or str(extracted.get("cover_prompt", ""))
    legacy_prompts = load_image_prompts(task)
    records = build_image_records_from_generation({}, extracted, legacy_prompts, cover_prompt)
    if records:
        cleaned_markdown = apply_default_image_placeholders(cleaned_markdown, records)
        update_task(
            task_id,
            {
                "markdown": cleaned_markdown,
                "original_markdown": cleaned_markdown,
                "cover_image_prompt": cover_prompt,
                "image_prompts": json.dumps(legacy_image_prompts_from_records(records), ensure_ascii=False, indent=2),
            },
        )
        draft = sync_article_draft_from_task(task_id)
        if draft is not None:
            replace_generated_images(draft.id, records)
            sync_image_status_from_markdown(draft.id, cleaned_markdown)
    return draft


def task_prompt_values(task: Mapping[str, str]) -> Dict[str, str]:
    values = {field: task.get(field, "") or "" for field in TASK_FIELDS}
    values["retrieved_knowledge"] = task.get("retrieved_knowledge", "") or ""
    return values


def generate_article(task_id: str, next_status: str = "已生成") -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    config = get_config()
    prompt = render_template(read_prompt("article_prompt.txt"), task_prompt_values(task))
    data = extract_json_object(call_deepseek(config, prompt, temperature=0.5))

    title = sanitize_model_text(str(data.get("title", ""))).strip()
    digest = sanitize_model_text(str(data.get("digest", ""))).strip()
    cover_prompt = sanitize_model_text(str(data.get("cover_prompt", data.get("cover_image_prompt", "")))).strip()
    image_prompts = normalize_image_prompts(data.get("image_prompts", []), cover_prompt)
    extracted = extract_image_prompts_from_markdown(str(data.get("markdown", "")))
    image_records = build_image_records_from_generation(data, extracted, image_prompts, cover_prompt)
    markdown = ensure_markdown_requirements(str(extracted.get("clean_markdown", "")), "", [])
    markdown = apply_default_image_placeholders(markdown, image_records)

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
            "image_prompts": json.dumps(legacy_image_prompts_from_records(image_records), ensure_ascii=False, indent=2),
            "risk_level": sanitize_model_text(str(data.get("risk_level", ""))).strip(),
            "risk_report": sanitize_model_text(str(data.get("risk_report", ""))).strip(),
            "doctor_review_note": sanitize_model_text(str(data.get("doctor_review_note", ""))).strip(),
            "change_summary": "",
            "status": next_status,
        },
    )
    export_markdown(task_id)
    sync_image_records_for_task(task_id, image_records, markdown)


def sync_article_draft_from_task(task_id: str):
    task = get_task(task_id)
    if task is None:
        return None
    existing_draft = get_article_draft_by_legacy_task(task_id)
    status_map = {
        "待输入": "draft_input",
        "已生成": "ai_generated",
        "已生成，待审核": "doctor_review_pending",
        "待修改": "revision_requested",
        "重新生成中": "regenerating",
        "待审核": "doctor_review_pending",
        "审核通过": "approved",
        "排版中": "layout_ready",
        "已发布": "published",
        "已废弃": "discarded",
    }
    duplicate_check = ""
    viewpoint = task.get("doctor_viewpoint", "") or ""
    match = re.search(r"重复检查[:：]\s*(.+)", viewpoint)
    if match:
        duplicate_check = match.group(1).strip()
    referenced = []
    ref_match = re.search(r"参考内容[:：]\s*(.+)", viewpoint)
    if ref_match:
        referenced = parse_tags(ref_match.group(1))
    existing_refs = []
    if existing_draft and existing_draft.referenced_items:
        try:
            parsed_refs = json.loads(existing_draft.referenced_items)
            if isinstance(parsed_refs, list):
                existing_refs = [str(item) for item in parsed_refs]
        except json.JSONDecodeError:
            existing_refs = []
    return upsert_article_draft_from_legacy_task(
        legacy_task_id=task_id,
        title=task.get("title") or task.get("article_topic") or "未命名稿件",
        digest=task.get("digest", ""),
        markdown=task.get("polished_markdown") or task.get("original_markdown") or task.get("markdown") or "",
        source_type=existing_draft.source_type if existing_draft else ("legacy_task" if not task.get("retrieved_knowledge") else "knowledge_base"),
        knowledge_base_id=existing_draft.knowledge_base_id if existing_draft else None,
        referenced_items=json.dumps(referenced or existing_refs, ensure_ascii=False),
        risk_level=task.get("risk_level", ""),
        risk_report=task.get("risk_report", ""),
        cover_prompt=task.get("cover_image_prompt", ""),
        duplicate_check_result=duplicate_check or (existing_draft.duplicate_check_result if existing_draft else ""),
        topic_angle=task.get("doctor_viewpoint", ""),
        status=status_map.get(task.get("status", ""), "draft_input"),
    )


def rerun_risk_review(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not markdown:
        raise UserFacingError("请先生成正文。")
    settings = get_app_settings_map()
    prompt = render_template(
        read_prompt("risk_review_prompt.txt"),
        {
            "ip_role": settings.get("ip_role", "心理医生"),
            "task_table": render_task_table(task),
            "article_draft": final_markdown(task),
        },
    )
    risk_report = sanitize_model_text(call_deepseek(get_config(), prompt, temperature=0.2)).strip()
    risk_level = task.get("risk_level", "")
    level_match = re.search(r"风险等级\s*[\n\r#：: ]+([低中高])", risk_report)
    if level_match:
        risk_level = level_match.group(1)
    update_task(task_id, {"risk_report": risk_report, "risk_level": risk_level, "status": "待审核"})
    export_markdown(task_id)
    sync_article_draft_from_task(task_id)


def request_revision_and_regenerate(task_id: str, feedback: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    feedback = sanitize_model_text(feedback).strip()
    if not feedback:
        raise UserFacingError("请输入修改意见。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("请先生成正文。")

    old_title = task.get("title", "")
    old_markdown = source_markdown
    update_task(task_id, {"status": "重新生成中", "rewrite_instruction": feedback})

    settings = get_app_settings_map()
    risk_requirements = (
        "不使用真实故事；不做诊断；不给药物建议；不承诺疗效；不制造焦虑；"
        "保留图片占位符；保留免责声明；输出最终可审核正文。"
    )
    prompt = render_template(
        read_prompt("rewrite_prompt.txt"),
        {
            "ip_role": settings.get("ip_role", "心理医生"),
            "risk_requirements": risk_requirements,
            "title": old_title,
            "digest": task.get("digest", ""),
            "markdown": old_markdown,
            "rewrite_instruction": feedback,
        },
    )
    data = extract_json_object(call_deepseek(get_config(), prompt, temperature=0.35))
    extracted = extract_image_prompts_from_markdown(str(data.get("markdown", "")) or old_markdown)
    new_markdown = ensure_markdown_requirements(str(extracted.get("clean_markdown", "")) or old_markdown, "", [])
    new_title = sanitize_model_text(str(data.get("title", old_title))).strip() or old_title
    new_digest = sanitize_model_text(str(data.get("digest", task.get("digest", "")))).strip()
    change_summary = sanitize_model_text(str(data.get("change_summary", ""))).strip()

    update_task(
        task_id,
        {
            "title": new_title,
            "digest": new_digest,
            "markdown": new_markdown,
            "original_markdown": new_markdown,
            "polished_markdown": "",
            "rewrite_instruction": feedback,
            "change_summary": change_summary,
            "status": "待审核",
        },
    )
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, new_markdown)
    draft = get_article_draft_by_legacy_task(task_id)
    if draft is not None:
        create_revision_history(
            article_draft_id=draft.id,
            old_title=old_title,
            old_markdown=old_markdown,
            user_feedback=feedback,
            new_title=new_title,
            new_markdown=new_markdown,
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
    extracted = extract_image_prompts_from_markdown(str(data.get("markdown", "")) or source_markdown)
    markdown = ensure_markdown_requirements(str(extracted.get("clean_markdown", "")) or source_markdown, "", [])
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
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, markdown)


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
        cover_prompt = (
            updates.get("cover_image_prompt")
            or sanitize_model_text(str(data.get("cover_prompt", ""))).strip()
            or task["cover_image_prompt"]
        )
        image_prompts = normalize_image_prompts(data.get("image_prompts", []), cover_prompt)
        if not image_prompts:
            raise UserFacingError("DeepSeek 没有返回新的图片提示词，请重试。")
        extracted = extract_image_prompts_from_markdown(str(data.get("markdown", "")) or source_markdown)
        image_records = build_image_records_from_generation(data, extracted, image_prompts, str(cover_prompt))
        refreshed_markdown = ensure_markdown_requirements(str(extracted.get("clean_markdown", "")) or source_markdown, "", [])
        refreshed_markdown = apply_default_image_placeholders(refreshed_markdown, image_records)
        updates["cover_image_prompt"] = cover_prompt
        updates["image_prompts"] = json.dumps(legacy_image_prompts_from_records(image_records), ensure_ascii=False, indent=2)
        updates["markdown"] = refreshed_markdown
        updates["original_markdown"] = updates["markdown"]
        updates["polished_markdown"] = ""
    update_task(task_id, updates)
    export_markdown(task_id)
    if "image_prompts" in expected_keys or "cover_image_prompt" in expected_keys:
        sync_image_records_for_task(task_id, image_records, updates["markdown"])
    else:
        draft = sync_article_draft_from_task(task_id)
        if draft is not None:
            sync_image_status_from_markdown(draft.id, source_markdown)


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
    if status in {"审核通过", "排版中", "已发布"}:
        status = "待修改"
    elif status == "待审核":
        status = "待修改"
    elif status == "已生成，待审核":
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
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, safe_markdown)


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
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, polished)


def restore_original_markdown(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("当前没有原始 Markdown 可恢复。")
    update_task(task_id, {"markdown": source_markdown, "polished_markdown": ""})
    export_markdown(task_id)
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, source_markdown)


def submit_doctor_review(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    if not task["title"] or not (task.get("original_markdown") or task.get("markdown")):
        raise UserFacingError("请先生成并检查文章内容。")
    update_task(task_id, {"status": "待审核"})
    export_markdown(task_id)
    sync_article_draft_from_task(task_id)


def approve_and_enter_publish(task_id: str) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    if task["status"] not in {"待审核", "已生成，待审核", "审核通过"}:
        raise UserFacingError("只有提交医生审核后的任务，才能进入排版发布页。")
    update_task(task_id, {"status": "排版中"})
    st.session_state["selected_publish_task_id"] = task_id
    go_to_page("排版发布页", task_id=task_id)
    export_markdown(task_id)
    sync_article_draft_from_task(task_id)


def mark_status(task_id: str, status: str, time_field: str = "") -> None:
    updates = {"status": status}
    if time_field:
        updates[time_field] = now_text()
    update_task(task_id, updates)
    export_markdown(task_id)
    sync_article_draft_from_task(task_id)


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


def strip_image_placeholders(markdown: str) -> str:
    text = IMAGE_PLACEHOLDER_RE.sub("", markdown or "")
    return cleanup_markdown_spacing(text)


def image_caption_markdown(caption: str) -> str:
    clean_caption = sanitize_model_text(caption).strip()
    if not clean_caption:
        return ""
    return f'\n\n<center><span style="font-size: 12px; color: #888;">{clean_caption}</span></center>'


def build_publish_markdown(article_id: int, mode: str = "text_only") -> str:
    from orm_models import get_article_draft

    draft = get_article_draft(article_id)
    if draft is None:
        raise UserFacingError("没有找到稿件。")
    body = draft.markdown or ""
    title = draft.title.strip()
    if title and not body.strip().startswith("# "):
        body = f"# {title}\n\n{body.strip()}"
    if mode == "text_only":
        return strip_image_placeholders(body)

    images = {image.slot_key: image for image in list_generated_images(article_id)}

    def replace_match(match: re.Match) -> str:
        slot_key = match.group(1).strip()
        image = images.get(slot_key)
        if image is None:
            return "> [此处保留插图位置：请手动补充图片]"
        if not image.selected:
            return ""
        alt_text = image.alt_text or image.caption or image.prompt[:80] or "文章配图"
        if is_publishable_image_url(image.public_url):
            return f"![{alt_text}]({image.public_url})" + image_caption_markdown(image.caption)
        return f"> [此处保留插图位置：{alt_text}。请先生成稳定公网图片链接]"

    return cleanup_markdown_spacing(IMAGE_PLACEHOLDER_RE.sub(replace_match, body))


def build_publish_markdown_for_task(task_id: str, mode: str = "text_only") -> str:
    draft = sync_article_draft_from_task(task_id)
    if draft is None:
        raise UserFacingError("没有找到稿件。")
    task = get_task(task_id)
    if task is not None:
        sync_image_status_from_markdown(draft.id, final_markdown(task))
    return build_publish_markdown(draft.id, mode)


def missing_public_url_images(task_id: str) -> List[str]:
    draft = ensure_image_records_for_task(task_id)
    if draft is None:
        return []
    task = get_task(task_id)
    placeholders = markdown_placeholders(final_markdown(task)) if task else set()
    missing = []
    for image in list_generated_images(draft.id):
        if image.image_role in {"cover", "inline"} and image.selected and image.slot_key in placeholders and not is_publishable_image_url(image.public_url):
            missing.append(image.slot_key)
    return missing


def image_is_generated(image) -> bool:
    return bool(image.local_path or image.public_url or image.status in {"generated_local", "uploaded_public", "manual_url", "selected"})


def image_has_usable_link(image) -> bool:
    return is_publishable_image_url(image.public_url)


def unknown_image_placeholders(article_draft_id: int, markdown: str) -> List[str]:
    known = {image.slot_key for image in list_generated_images(article_draft_id)}
    return sorted(markdown_placeholders(markdown) - known)


def existing_image_plan_summary(article_draft_id: int) -> str:
    lines = []
    for image in list_generated_images(article_draft_id):
        params = visual_params_dict(image.visual_params)
        lines.append(
            json.dumps(
                {
                    "image_role": image.image_role,
                    "slot_key": image.slot_key,
                    "scene_purpose": params.get("scene_purpose", ""),
                    "related_section_title": params.get("related_section_title", ""),
                    "caption": image.caption,
                    "insert_position": image.insert_position,
                    "status": image_status_label(image.status),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines) or "暂无"


def image_plan_data_from_response(data: Mapping[str, object]) -> Dict[str, object]:
    if isinstance(data.get("image_plan"), dict):
        return dict(data)
    return {"image_plan": {"cover": data.get("cover", {}), "inline_images": data.get("inline_images", []), "backup_images": data.get("backup_images", [])}}


def image_plan_prompt_values(task: Mapping[str, str], draft_id: int, generation_scope: str, target_slot_key: str = "") -> Dict[str, str]:
    settings = get_app_settings_map()
    return {
        "generation_scope": generation_scope,
        "target_slot_key": target_slot_key,
        "existing_image_plan": existing_image_plan_summary(draft_id),
        "title": task.get("title") or task.get("article_topic") or "",
        "digest": task.get("digest", ""),
        "markdown": task.get("original_markdown") or task.get("markdown") or "",
        "ip_role": settings.get("ip_role", "专业人士"),
        "style_preset": get_runtime_setting("DEFAULT_IMAGE_STYLE_PRESET", settings.get("default_image_style_preset", "温和治愈插画")),
    }


def preserve_existing_image_assets(article_draft_id: int, records: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    existing = {image.slot_key: image for image in list_generated_images(article_draft_id)}
    merged: List[Dict[str, object]] = []
    for record in records:
        item = dict(record)
        old = existing.get(str(item.get("slot_key", "")))
        if old and image_is_generated(old):
            item["local_path"] = old.local_path
            item["public_url"] = old.public_url
            item["status"] = old.status
            item["selected"] = old.selected
            item["error_message"] = old.error_message
        merged.append(item)
    return merged


def build_image_plan_records_from_model(task: Mapping[str, str], draft_id: int, generation_scope: str, target_slot_key: str = "") -> tuple[Dict[str, object], List[Dict[str, object]]]:
    prompt = render_template(
        read_prompt("image_plan_prompt.txt"),
        image_plan_prompt_values(task, draft_id, generation_scope, target_slot_key),
    )
    data = extract_json_object(call_deepseek(get_config(), prompt, temperature=0.35))
    normalized_data = image_plan_data_from_response(data)
    cover_prompt = task.get("cover_image_prompt", "")
    extracted = {"clean_markdown": task.get("original_markdown") or task.get("markdown") or ""}
    records = build_image_records_from_generation(normalized_data, extracted, [], cover_prompt)
    return data, records


def regenerate_image_plan(task_id: str, mode: str = "all", image_id: int = 0) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到稿件。")
    draft = ensure_image_records_for_task(task_id)
    if draft is None:
        raise UserFacingError("没有找到图片计划。")

    generation_scope = "整篇图片计划"
    target_slot_key = ""
    target_image = get_generated_image(image_id) if image_id else None
    if mode == "cover":
        generation_scope = "只生成封面图"
        target_slot_key = "cover"
    elif mode == "inline":
        if target_image is None:
            raise UserFacingError("没有找到这张正文配图。")
        generation_scope = "只生成指定正文配图"
        target_slot_key = target_image.slot_key
    elif mode == "add_inline":
        generation_scope = "新增一张正文配图"
        target_slot_key = next_inline_slot(draft.id)

    _, records = build_image_plan_records_from_model(task, draft.id, generation_scope, target_slot_key)
    if not records:
        raise UserFacingError("模型没有返回可用的图片计划，请重试。")

    if mode == "all":
        markdown = task.get("original_markdown") or task.get("markdown") or ""
        updated_markdown = apply_default_image_placeholders(markdown, records)
        merged_records = preserve_existing_image_assets(draft.id, records)
        replace_generated_images(draft.id, merged_records)
        sync_image_status_from_markdown(draft.id, updated_markdown)
        update_task(
            task_id,
            {
                "markdown": updated_markdown,
                "original_markdown": updated_markdown,
                "cover_image_prompt": next((str(record.get("prompt", "")) for record in records if record.get("image_role") == "cover"), task.get("cover_image_prompt", "")),
                "image_prompts": json.dumps(legacy_image_prompts_from_records(records), ensure_ascii=False, indent=2),
            },
        )
        export_markdown(task_id)
        sync_article_draft_from_task(task_id)
        return

    if mode == "add_inline":
        inline_records = [record for record in records if record.get("image_role") == "inline"]
        if not inline_records:
            raise UserFacingError("模型没有返回新增正文配图。")
        record = dict(inline_records[0])
        record["slot_key"] = target_slot_key
        create_generated_image(article_draft_id=draft.id, **record)
        export_markdown(task_id)
        return

    if target_image is None:
        target_image = next((image for image in list_generated_images(draft.id) if image.slot_key == target_slot_key), None)
    if target_image is None:
        raise UserFacingError("没有找到要更新的图片。")
    role = "cover" if mode == "cover" else "inline"
    candidates = [record for record in records if record.get("image_role") == role]
    if not candidates:
        raise UserFacingError("模型没有返回对应图片计划。")
    record = dict(candidates[0])
    update_generated_image(
        target_image.id,
        prompt=str(record.get("prompt", "")),
        negative_prompt=str(record.get("negative_prompt", "")),
        alt_text=str(record.get("alt_text", "")),
        caption=str(record.get("caption", "")),
        insert_position=str(record.get("insert_position", target_image.insert_position)),
        aspect_ratio=str(record.get("aspect_ratio", target_image.aspect_ratio)),
        style_preset=str(record.get("style_preset", target_image.style_preset)),
        visual_params=str(record.get("visual_params", "{}")),
        error_message="",
    )
    if role == "cover":
        update_task(task_id, {"cover_image_prompt": str(record.get("prompt", ""))})
    export_markdown(task_id)


def generate_all_missing_images(article_draft_id: int) -> int:
    generated_count = 0
    for image in list_generated_images(article_draft_id):
        if image.image_role == "backup":
            continue
        if image_is_generated(image):
            continue
        generate_image_with_provider(image.id)
        generated_count += 1
    return generated_count


def remove_image_from_task_markdown(task_id: str, image_id: int) -> None:
    task = get_task(task_id)
    image = get_generated_image(image_id)
    if task is None or image is None:
        raise UserFacingError("没有找到文章或图片。")
    markdown = task.get("original_markdown") or task.get("markdown") or ""
    updated = remove_image_placeholder_from_markdown(markdown, image.slot_key)
    update_task(task_id, {"markdown": updated, "original_markdown": updated, "polished_markdown": ""})
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, updated)
    export_markdown(task_id)


def apply_generated_images_to_task_markdown(task_id: str, draft_id: int) -> int:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到文章。")
    markdown = task.get("original_markdown") or task.get("markdown") or ""
    updated = markdown
    applied_count = 0
    cover_images = [image for image in list_generated_images(draft_id) if image.image_role == "cover" and image_is_generated(image)]
    for image in cover_images[:1]:
        if image.slot_key in markdown_placeholders(updated):
            continue
        updated = insert_cover_placeholder(updated, image.slot_key or "cover")
        update_generated_image(image.id, selected=True, status="selected")
        applied_count += 1
    for image in list_generated_images(draft_id):
        if image.image_role != "inline":
            continue
        if not image_is_generated(image) and image.slot_key not in markdown_placeholders(updated):
            continue
        before = updated
        updated = insert_image_placeholder(
            updated,
            image.slot_key,
            image.insert_position or "after_intro",
            image_related_section_title(image),
            replace_existing=True,
        )
        update_generated_image(image.id, selected=True)
        if updated != before:
            applied_count += 1
    if applied_count == 0:
        raise UserFacingError("当前没有需要应用或整理位置的图片。请先生成正文配图，或检查图片是否已经插入正文。")
    update_task(task_id, {"markdown": updated, "original_markdown": updated, "polished_markdown": ""})
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, updated)
    export_markdown(task_id)
    return applied_count


def task_status_label(status: str) -> str:
    mapping = {
        "待输入": "待输入",
        "已生成": "待审核",
        "已生成，待审核": "待审核",
        "待修改": "需修改",
        "需修改": "需修改",
        "重新生成中": "正在修改",
        "待审核": "待审核",
        "审核通过": "已审核通过",
        "排版中": "已准备发布",
        "已发布": "已发布",
        "已废弃": "已废弃",
    }
    return mapping.get(status or "", status or "待审核")


def save_and_rerun_risk_review(task_id: str, title: str, digest: str, markdown: str) -> None:
    save_manual_edits(task_id, title, digest, markdown)
    rerun_risk_review(task_id)


def build_layout_preview(task_id: str) -> str:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("请先生成正文 Markdown。")
    prompt = render_template(
        read_prompt("layout_enhance_prompt.txt"),
        {
            "layout_style": task.get("layout_style", "温暖治愈"),
            "original_markdown": source_markdown,
        },
    )
    polished = call_deepseek(get_config(), prompt, temperature=0.35)
    polished = ensure_markdown_requirements(polished, task["cover_image_prompt"], load_image_prompts(task))
    if not polished:
        raise UserFacingError("DeepSeek 没有返回优化后的 Markdown，请重试。")
    return polished


def apply_layout_preview(task_id: str, markdown: str) -> None:
    if not markdown.strip():
        raise UserFacingError("没有可应用的优化结果。")
    update_task(task_id, {"polished_markdown": markdown.strip(), "status": "待审核"})
    export_markdown(task_id)
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, markdown)


def build_revision_preview(task_id: str, feedback: str) -> Dict[str, str]:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    feedback = sanitize_model_text(feedback).strip()
    if not feedback:
        raise UserFacingError("请输入修改意见。")
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""
    if not source_markdown:
        raise UserFacingError("请先生成正文。")
    settings = get_app_settings_map()
    prompt = render_template(
        read_prompt("rewrite_prompt.txt"),
        {
            "ip_role": settings.get("ip_role", "专业人士"),
            "risk_requirements": "不使用真实故事；不做诊断；不给药物建议；不承诺疗效；不制造焦虑；保留图片占位符；保留免责声明。",
            "title": task.get("title", ""),
            "digest": task.get("digest", ""),
            "markdown": source_markdown,
            "rewrite_instruction": feedback,
        },
    )
    data = extract_json_object(call_deepseek(get_config(), prompt, temperature=0.35))
    extracted = extract_image_prompts_from_markdown(str(data.get("markdown", "")) or source_markdown)
    markdown = ensure_markdown_requirements(str(extracted.get("clean_markdown", "")) or source_markdown, "", [])
    return {
        "title": sanitize_model_text(str(data.get("title", task.get("title", "")))).strip(),
        "digest": sanitize_model_text(str(data.get("digest", task.get("digest", "")))).strip(),
        "markdown": markdown,
        "change_summary": sanitize_model_text(str(data.get("change_summary", ""))).strip(),
        "feedback": feedback,
    }


def apply_revision_preview(task_id: str, preview: Mapping[str, str]) -> None:
    task = get_task(task_id)
    if task is None:
        raise UserFacingError("没有找到任务。")
    old_title = task.get("title", "")
    old_markdown = task.get("original_markdown") or task.get("markdown") or ""
    markdown = preview.get("markdown", "")
    update_task(
        task_id,
        {
            "title": preview.get("title", old_title),
            "digest": preview.get("digest", task.get("digest", "")),
            "markdown": markdown,
            "original_markdown": markdown,
            "polished_markdown": "",
            "rewrite_instruction": preview.get("feedback", ""),
            "change_summary": preview.get("change_summary", ""),
            "status": "待审核",
        },
    )
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, markdown)
        create_revision_history(
            article_draft_id=draft.id,
            old_title=old_title,
            old_markdown=old_markdown,
            user_feedback=preview.get("feedback", ""),
            new_title=preview.get("title", old_title),
            new_markdown=markdown,
        )
    export_markdown(task_id)


def render_article_markdown_preview(draft_id: int, markdown: str) -> None:
    images = {image.slot_key: image for image in list_generated_images(draft_id)}
    position = 0
    for match in IMAGE_PLACEHOLDER_RE.finditer(markdown or ""):
        before = (markdown or "")[position : match.start()]
        if before.strip():
            st.markdown(before)
        slot_key = match.group(1).strip()
        image = images.get(slot_key)
        if image and image.public_url:
            st.image(image.public_url, caption=image.caption or image.alt_text or None, use_container_width=True)
            if image.caption:
                st.caption(image.caption)
        else:
            st.markdown(
                f"""
                <div style="border:1px dashed #cbd5e1;border-radius:12px;padding:18px;margin:12px 0;background:#f8fafc;color:#64748b;text-align:center;">
                此处为正文配图 {escape(slot_key)}，尚未填写可用图片链接
                </div>
                """,
                unsafe_allow_html=True,
            )
        position = match.end()
    after = (markdown or "")[position:]
    if after.strip():
        st.markdown(after)


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

【知识库参考】
{task.get('retrieved_knowledge') or '未使用知识库'}

【风险审核报告】
{task['risk_report'] or '未生成'}

【医生审核提醒】
{task['doctor_review_note'] or '未生成'}

【提醒】
- 不处理原始心理咨询记录。
- 不使用真实来访者故事。
- AI 不做诊断，不给药物建议，不承诺疗效。
- 未经医生审核通过，不进入排版发布页。
- 当前版本不接真实图片生成模型 API，但支持图片计划、手动上传图片、填写图片链接和生成图文版 Markdown。
- Raphael 仅用于公众号排版预览，最终发布必须由医生人工完成。
"""
    output_path = OUTPUT_DIR / f"{task_id_to_filename(task['task_id'])}_完整交付包.md"
    output_path.write_text(content, encoding="utf-8")
    update_task(task_id, {"output_path": str(output_path)})
    return output_path


def render_browser_copy_button(
    label: str,
    content: str,
    key: str,
    *,
    success_message: str = "已复制，可粘贴到 Raphael。",
    failure_message: str = "复制失败，请展开下方「复制兜底 / 下载 Markdown」手动复制。",
) -> None:
    """Render a browser-side copy button for public Streamlit deployments."""
    safe_content = json.dumps(content or "", ensure_ascii=False)
    safe_label = escape(label)
    safe_success = json.dumps(success_message, ensure_ascii=False)
    safe_failure = json.dumps(failure_message, ensure_ascii=False)
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", key)

    html = f"""
    <div class="copy-wrap">
      <button id="copy-btn-{safe_key}" class="copy-btn" type="button">{safe_label}</button>
      <span id="copy-status-{safe_key}" class="copy-status" aria-live="polite"></span>
    </div>

    <script>
    (() => {{
      const text = {safe_content};
      const successMessage = {safe_success};
      const failureMessage = {safe_failure};
      const button = document.getElementById("copy-btn-{safe_key}");
      const status = document.getElementById("copy-status-{safe_key}");

      function setStatus(message, className) {{
        status.textContent = message;
        status.className = "copy-status " + className;
      }}

      function fallbackCopy(value) {{
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        textarea.style.top = "-9999px";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();

        let ok = false;
        try {{
          ok = document.execCommand("copy");
        }} catch (err) {{
          ok = false;
        }}
        document.body.removeChild(textarea);
        return ok;
      }}

      async function copyText() {{
        if (!text.trim()) {{
          setStatus("没有可复制的内容。", "fail");
          return;
        }}
        setStatus("复制中...", "muted");
        try {{
          if (navigator.clipboard && window.isSecureContext) {{
            await navigator.clipboard.writeText(text);
            setStatus(successMessage, "ok");
            return;
          }}
        }} catch (err) {{}}

        if (fallbackCopy(text)) {{
          setStatus(successMessage, "ok");
        }} else {{
          setStatus(failureMessage, "fail");
        }}
      }}

      button.addEventListener("click", copyText);
    }})();
    </script>

    <style>
    html, body {{
      margin: 0;
      padding: 0;
      background: transparent;
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .copy-wrap {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      width: 100%;
      min-height: 64px;
    }}
    .copy-btn {{
      width: 100%;
      min-height: 42px;
      padding: 0.58rem 0.9rem;
      border: 1px solid rgba(49, 51, 63, 0.22);
      border-radius: 8px;
      background: #ffffff;
      color: #262730;
      cursor: pointer;
      font-size: 14px;
      font-weight: 600;
      line-height: 1.2;
    }}
    .copy-btn:hover {{
      border-color: #ff4b4b;
      color: #ff4b4b;
    }}
    .copy-btn:active {{
      transform: translateY(1px);
    }}
    .copy-status {{
      min-height: 18px;
      font-size: 12px;
      line-height: 1.45;
      word-break: break-word;
    }}
    .copy-status.muted {{
      color: #8a8f98;
    }}
    .copy-status.ok {{
      color: #16a34a;
    }}
    .copy-status.fail {{
      color: #d97706;
    }}
    @media (prefers-color-scheme: dark) {{
      .copy-btn {{
        border-color: rgba(250, 250, 250, 0.24);
        background: transparent;
        color: #fafafa;
      }}
    }}
    </style>
    """
    components.html(html, height=76)


def render_copy_button(text: str, label: str, copied_label: str) -> None:
    button_key = f"copy_{re.sub(r'[^a-zA-Z0-9_]', '_', label)}_{abs(hash(text or '')) % 1000000}"
    render_browser_copy_button(
        label,
        text,
        button_key,
        success_message=copied_label,
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
        "未审核通过不进入排版发布页；图片生成模型未配置时，只提供提示词、上传图片和填写图片链接。"
    )


def render_entry_card(
    title: str,
    description: str,
    button_label: str,
    target_page: str,
    *,
    recommended: bool = False,
) -> None:
    card_class = "entry-card recommended" if recommended else "entry-card"
    button_class = "entry-button primary" if recommended else "entry-button"
    badge = '<span class="entry-badge">推荐</span>' if recommended else ""
    st.markdown(
        f"""
        <div class="{card_class}">
            <div class="entry-top">
                <div class="entry-badge-row">{badge}</div>
                <div class="entry-title">{escape(title)}</div>
                <div class="entry-desc">{escape(description)}</div>
            </div>
            <a class="{button_class}" href="{page_href(target_page)}" target="_self">{escape(button_label)}</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_workspace_page(tasks: List[Dict[str, str]]) -> None:
    st.markdown('<div class="workspace-hero">', unsafe_allow_html=True)
    st.header("公众号内容工作台")
    st.markdown(
        '<div class="workspace-subtitle">选择一种方式，快速生成可用于公众号发布的文章。</div>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    top_cols = st.columns([1, 4])
    with top_cols[0]:
        if st.button("新增今日素材", type="secondary", use_container_width=True):
            go_to_page("新增今日素材")
            st.rerun()
    with top_cols[1]:
        st.caption("把今天的新想法、观点、读者问题或零散笔记补充到知识库。")

    entry_cols = st.columns(3)
    with entry_cols[0]:
        render_entry_card(
            "直接生成一篇",
            "已经有明确主题，马上生成一篇公众号文章。",
            "开始生成",
            "新建文章页",
        )
    with entry_cols[1]:
        render_entry_card(
            "基于知识库生成",
            "根据已有资料、案例、笔记和历史内容推荐选题并生成文章。",
            "从知识库生成",
            "基于知识库生成",
            recommended=True,
        )
    with entry_cols[2]:
        render_entry_card(
            "每周计划生成",
            "设置每周主题和知识库，手动生成约 3 篇待审核稿件。",
            "设置计划",
            "计划生成",
        )

    waiting_review = len([task for task in tasks if task.get("status") in {"已生成，待审核", "待审核"}])
    generated_not_published = len(
        [
            task
            for task in tasks
            if task.get("title")
            and task.get("status") not in {"已发布"}
        ]
    )
    weekly_remaining = 0
    try:
        for plan in list_weekly_plans()[:1]:
            topics = list_weekly_topics(int(plan["id"]))
            weekly_remaining = len([topic for topic in topics if not topic.get("generated_article_task_id")])
            break
    except Exception:
        weekly_remaining = 0

    st.markdown('<div class="soft-section-title">待处理</div>', unsafe_allow_html=True)
    metric_cols = st.columns(3)
    metric_cols[0].metric("待审核稿件", waiting_review)
    metric_cols[1].metric("已生成未发布", generated_not_published)
    metric_cols[2].metric("本周计划剩余", weekly_remaining)

    st.markdown('<div class="soft-section-title">最近生成</div>', unsafe_allow_html=True)
    recent_tasks = [task for task in tasks if task.get("title") or task.get("article_topic")][:5]
    if not recent_tasks:
        st.info("还没有生成过文章，可以先从上方入口开始。")
        return
    rows = [
        {
            "标题": task.get("title") or task.get("article_topic") or "未命名",
            "状态": task.get("status") or "待输入",
            "生成时间": task.get("created_at") or "",
            "更新时间": task.get("updated_at") or "",
        }
        for task in recent_tasks
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    selected_recent = st.selectbox(
        "选择最近稿件",
        [task["task_id"] for task in recent_tasks],
        format_func=lambda task_id: next(
            (task.get("title") or task.get("article_topic") or task_id for task in recent_tasks if task["task_id"] == task_id),
            task_id,
        ),
        key="workspace_recent_task",
    )
    if st.button("查看 / 继续编辑", type="primary"):
        st.session_state["selected_task_id"] = selected_recent
        go_to_page("任务详情 / 编辑页", task_id=selected_recent)
        st.rerun()


def render_settings_page() -> None:
    st.subheader("设置")
    settings = get_app_settings_map()
    api_key = get_runtime_setting("DEEPSEEK_API_KEY")
    api_status = "已配置" if api_key and api_key != "your_deepseek_api_key_here" else "未配置"
    cols = st.columns(2)
    cols[0].metric("DeepSeek API", api_status)
    cols[1].metric("当前 IP 角色设定", settings.get("ip_role", "心理医生"))
    st.markdown("#### 基础设置")
    st.text_input("默认文章风格", value=settings.get("default_article_style", "温和科普"), disabled=True)
    st.text_input("默认文章长度", value=settings.get("default_article_length", "中等1200字"), disabled=True)
    st.text_input("默认目标读者", value=settings.get("default_target_reader", ""), disabled=True)
    st.text_input("当前 IP 署名", value=settings.get("ip_name", ""), disabled=True)
    st.text_input("默认 Raphael 链接", value=settings.get("raphael_url", RAPHAEL_URL), disabled=True)

    st.markdown("#### 图片生成设置")
    image_enabled = get_runtime_setting("IMAGE_GENERATION_ENABLED", settings.get("image_generation_enabled", "false"))
    image_provider = get_runtime_setting("IMAGE_PROVIDER", settings.get("image_provider", "dummy"))
    image_model = get_runtime_setting("IMAGE_MODEL", settings.get("image_model", ""))
    storage_provider = get_runtime_setting("IMAGE_STORAGE_PROVIDER", settings.get("image_storage_provider", "manual_url"))
    public_base_url = get_runtime_setting("IMAGE_PUBLIC_BASE_URL", settings.get("image_public_base_url", ""))
    image_cols = st.columns(3)
    image_cols[0].metric("图片生成", "已启用" if str(image_enabled).lower() == "true" else "未启用")
    image_cols[1].metric("图片服务", image_provider or "未配置")
    image_cols[2].metric("图片存储", storage_provider or "manual_url")
    st.text_input("默认图片模型", value=image_model or "未配置", disabled=True)
    st.text_input("默认图片风格", value=get_runtime_setting("DEFAULT_IMAGE_STYLE_PRESET", settings.get("default_image_style_preset", "温和治愈插画")), disabled=True)
    st.text_input("默认封面图比例", value=get_runtime_setting("DEFAULT_COVER_ASPECT_RATIO", settings.get("default_cover_aspect_ratio", "2.35:1")), disabled=True)
    st.text_input("默认正文配图比例", value=get_runtime_setting("DEFAULT_INLINE_ASPECT_RATIO", settings.get("default_inline_aspect_ratio", "16:9")), disabled=True)
    st.text_input("图片公开访问基础地址", value=public_base_url or "未配置", disabled=True)
    if image_provider == "dummy" or not image_model:
        st.info("当前尚未配置图片生成模型。你可以先复制提示词去其他工具生成图片，或手动上传已有图片。")
    if storage_provider == "manual_url":
        st.info("当前尚未配置稳定云端图片存储。图片可本地预览和下载，但图文发布前需要稳定 HTTPS 图片链接。")
    if storage_provider in {"cloudinary", "cloudinary_unsigned"}:
        cloud_status = "已配置" if get_runtime_setting("CLOUDINARY_CLOUD_NAME") and get_runtime_setting("CLOUDINARY_UPLOAD_PRESET") else "未配置完整"
        st.info(f"当前使用 Cloudinary 图片存储：{cloud_status}。")
    if public_base_url and is_local_public_url(public_base_url):
        st.warning("当前图片链接可能仅本机可访问。若希望复制到 Raphael 或公众号后台后正常显示，请使用公网 HTTPS 图片链接。")
    st.info("API Key 不会在页面明文展示。")


def render_new_article_page() -> None:
    st.subheader("直接生成一篇")
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


def task_source_info(task: Mapping[str, str]) -> tuple[str, str]:
    draft = get_article_draft_by_legacy_task(task["task_id"])
    if draft is None:
        if task.get("retrieved_knowledge"):
            return "知识库生成", "未记录"
        return "直接生成", "不使用知识库"
    source_labels = {
        "direct": "直接生成",
        "legacy_task": "历史任务",
        "knowledge_base": "知识库生成",
        "weekly_plan": "计划生成",
    }
    source = source_labels.get(draft.source_type, draft.source_type or "直接生成")
    base_name = knowledge_base_name(draft.knowledge_base_id) if draft.knowledge_base_id else "不使用知识库"
    return source, base_name


def task_matches_history_filter(task: Mapping[str, str], status_filter: str) -> bool:
    status = task.get("status", "") or "待输入"
    if status_filter == "全部":
        return True
    if status_filter == "待审核":
        return status in {"已生成，待审核", "待审核"}
    if status_filter == "已通过":
        return status in {"审核通过", "排版中"}
    if status_filter == "已发布":
        return status == "已发布"
    if status_filter == "已废弃":
        return status == "已废弃"
    return True


def render_task_list_page(tasks: List[Dict[str, str]]) -> None:
    st.subheader("历史稿件")
    st.caption("集中查看已经生成过的稿件，继续编辑、复制最终 Markdown，或标记发布状态。")
    if not tasks:
        st.warning("还没有稿件，请先到内容工作台生成一篇文章。")
        return

    filter_cols = st.columns([1, 1, 3])
    with filter_cols[0]:
        status_filter = st.selectbox("状态筛选", ["全部", "待审核", "已通过", "已发布", "已废弃"], key="history_status_filter")
    with filter_cols[1]:
        source_filter = st.selectbox("来源筛选", ["全部", "直接生成", "知识库生成", "计划生成", "历史任务"], key="history_source_filter")
    with filter_cols[2]:
        keyword = st.text_input("搜索标题或主题", placeholder="输入标题、主题关键词", key="history_keyword")

    enriched_tasks = []
    for task in tasks:
        source, base_name = task_source_info(task)
        title = task.get("title") or task.get("article_topic") or "未命名稿件"
        if not task_matches_history_filter(task, status_filter):
            continue
        if source_filter != "全部" and source != source_filter:
            continue
        if keyword and keyword.strip() not in title and keyword.strip() not in task.get("article_topic", ""):
            continue
        enriched_tasks.append({**task, "_source": source, "_base_name": base_name, "_display_title": title})

    if not enriched_tasks:
        st.info("当前筛选条件下没有稿件。")
        return

    summary_cols = st.columns(4)
    summary_cols[0].metric("当前筛选稿件", len(enriched_tasks))
    summary_cols[1].metric("待审核", len([task for task in tasks if task.get("status") in {"已生成，待审核", "待审核"}]))
    summary_cols[2].metric("已通过", len([task for task in tasks if task.get("status") in {"审核通过", "排版中"}]))
    summary_cols[3].metric("已发布", len([task for task in tasks if task.get("status") == "已发布"]))

    rows = [
        {
            "标题": task["_display_title"],
            "来源": task["_source"],
            "使用知识库": task["_base_name"],
            "状态": task.get("status") or "待输入",
            "风险等级": task.get("risk_level") or "未生成",
            "生成时间": task.get("created_at") or "",
            "更新时间": task.get("updated_at") or "",
        }
        for task in enriched_tasks
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    task_ids = [task["task_id"] for task in enriched_tasks]
    query_task_id = get_query_param("task_id")
    session_selected = st.session_state.get("history_selected_task_id") or st.session_state.get("selected_task_id")
    selected_id = session_selected or query_task_id
    if selected_id not in task_ids:
        selected_id = query_task_id if query_task_id in task_ids else task_ids[0]
    selected = st.selectbox(
        "选择要处理的稿件",
        task_ids,
        index=task_ids.index(selected_id),
        format_func=lambda task_id: next(
            (task["_display_title"] for task in enriched_tasks if task["task_id"] == task_id),
            task_id,
        ),
        key="history_selected_task_id",
    )
    st.session_state["selected_task_id"] = selected
    if query_task_id != selected:
        st.query_params["task_id"] = selected

    selected_task = get_task(selected)
    if selected_task is None:
        st.error("稿件不存在。")
        return
    source, base_name = task_source_info(selected_task)
    can_copy = selected_task.get("status") in {"审核通过", "排版中", "已发布"}

    with st.container(border=True):
        st.markdown(f"### {selected_task.get('title') or selected_task.get('article_topic') or '未命名稿件'}")
        render_compact_info_grid(
            [
                ("状态", selected_task.get("status") or "待输入"),
                ("来源", source),
                ("知识库", base_name),
                ("风险", selected_task.get("risk_level") or "未生成"),
                ("更新时间", selected_task.get("updated_at") or "暂无"),
            ],
            columns=5,
        )

        action_cols = st.columns(5)
        with action_cols[0]:
            if st.button("查看稿件", type="primary", use_container_width=True, key=f"history_view_{selected}"):
                go_to_page("任务详情 / 编辑页", task_id=selected)
                st.rerun()
        with action_cols[1]:
            if st.button("继续编辑", use_container_width=True, key=f"history_edit_{selected}"):
                go_to_page("任务详情 / 编辑页", task_id=selected)
                st.rerun()
        with action_cols[2]:
            if can_copy:
                render_copy_button(build_publish_markdown_for_task(selected, "text_only"), "复制文字版", "已复制文字版")
            else:
                st.button("复制 Markdown", disabled=True, help="审核通过后才能复制最终发布内容。", use_container_width=True)
        with action_cols[3]:
            if can_copy and selected_task.get("status") != "已发布":
                run_action("标记已发布", mark_status, selected, "已发布", "published_at", button_type="primary", key=f"history_publish_{selected}")
            else:
                st.button("标记已发布", disabled=True, use_container_width=True)
        with action_cols[4]:
            if selected_task.get("status") != "已废弃":
                run_action("标记废弃", mark_status, selected, "已废弃", key=f"history_discard_{selected}")
            else:
                st.button("已废弃", disabled=True, use_container_width=True)


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


def image_status_label(status: str) -> str:
    return IMAGE_STATUS_LABELS.get(status, status or "未生成")


def image_link_status_label(image) -> str:
    if is_publishable_image_url(image.public_url):
        return "稳定链接"
    if image.public_url and is_temporary_image_url(image.public_url):
        return "临时链接"
    if image.public_url:
        return "不可发布链接"
    return "未生成链接"


def is_local_public_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.hostname in {"127.0.0.1", "localhost"} or not parsed.scheme


def is_temporary_image_url(url: str) -> bool:
    parsed = urlparse(url or "")
    query = parsed.query.lower()
    host = (parsed.hostname or "").lower()
    if not url:
        return False
    temporary_markers = [
        "x-amz-signature",
        "x-amz-expires",
        "x-amz-credential",
        "expires=",
        "signature=",
    ]
    return "siliconflow-image" in host or any(marker in query for marker in temporary_markers)


def is_streamlit_auth_static_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return host.endswith(".streamlit.app") and (
        parsed.path.startswith("/app/static/")
        or parsed.path.startswith("/media/")
        or parsed.path.startswith("/~/+/media/")
    )


def is_publishable_image_url(url: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.scheme != "https":
        return False
    if is_local_public_url(url) or is_temporary_image_url(url) or is_streamlit_auth_static_url(url):
        return False
    return True


def next_inline_slot(article_draft_id: int) -> str:
    used = {image.slot_key for image in list_generated_images(article_draft_id)}
    index = 1
    while f"inline_{index}" in used:
        index += 1
    return f"inline_{index}"


def save_uploaded_image_file(image_id: int, uploaded_file) -> None:
    image = get_generated_image(image_id)
    if image is None:
        raise UserFacingError("图片记录不存在。")
    if uploaded_file is None:
        raise UserFacingError("请先选择图片文件。")
    IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploaded_file.name).suffix or ".png"
    filename = f"image_{image.article_draft_id}_{image.slot_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"
    path = IMAGE_OUTPUT_DIR / filename
    path.write_bytes(uploaded_file.getvalue())
    update_generated_image(image_id, local_path=str(path), status="generated_local", error_message="")


def save_manual_image_url(image_id: int, public_url: str) -> None:
    clean_url = public_url.strip()
    if not clean_url:
        raise UserFacingError("请填写图片链接。")
    update_generated_image(image_id, public_url=clean_url, status="manual_url", selected=True, error_message="")


def upload_image_to_storage(image_id: int) -> None:
    image = get_generated_image(image_id)
    if image is None:
        raise UserFacingError("图片记录不存在。")
    settings = get_app_settings_map()
    provider_name = get_runtime_setting("IMAGE_STORAGE_PROVIDER", settings.get("image_storage_provider", "manual_url"))
    public_base_url = get_runtime_setting("IMAGE_PUBLIC_BASE_URL", settings.get("image_public_base_url", ""))
    provider = get_image_storage_provider(provider_name, public_base_url)
    result = provider.upload_image(image.local_path)
    if not result.success:
        update_generated_image(image_id, error_message=result.error_message)
        raise UserFacingError(result.error_message)
    update_generated_image(image_id, public_url=result.public_url, status="uploaded_public", selected=True, error_message="")


def configured_storage_provider_name() -> str:
    settings = get_app_settings_map()
    return get_runtime_setting("IMAGE_STORAGE_PROVIDER", settings.get("image_storage_provider", "manual_url")).strip().lower()


def storage_upload_is_configured() -> bool:
    return configured_storage_provider_name() not in {"", "manual_url", "local_only"}


def try_upload_generated_image_to_storage(image_id: int) -> str:
    if not storage_upload_is_configured():
        return ""
    try:
        upload_image_to_storage(image_id)
    except Exception:
        return ""
    image = get_generated_image(image_id)
    return image.public_url if image else ""


def upload_all_images_to_storage(draft_id: int) -> int:
    uploaded_count = 0
    for image in list_generated_images(draft_id):
        if image.image_role == "backup":
            continue
        if is_publishable_image_url(image.public_url):
            continue
        if not image.local_path:
            continue
        upload_image_to_storage(image.id)
        uploaded_count += 1
    if uploaded_count == 0:
        raise UserFacingError("当前没有可上传的本地图片，或图片已经有稳定公网链接。")
    return uploaded_count


def generate_image_with_provider(image_id: int) -> None:
    image = get_generated_image(image_id)
    if image is None:
        raise UserFacingError("图片记录不存在。")
    update_generated_image(image_id, status="generation_pending", error_message="")
    settings = get_app_settings_map()
    provider_name = get_runtime_setting("IMAGE_PROVIDER", settings.get("image_provider", "dummy"))
    model_name = get_runtime_setting("IMAGE_MODEL", settings.get("image_model", ""))
    if provider_name.strip().lower() in {"siliconflow", "silicon_flow"}:
        model_name = get_runtime_setting("SILICONFLOW_IMAGE_MODEL", model_name or "Tongyi-MAI/Z-Image-Turbo")
    provider = get_image_generation_provider(provider_name)
    try:
        visual_params = json.loads(image.visual_params or "{}")
    except json.JSONDecodeError:
        visual_params = {}
    result = provider.generate_image(
        prompt=image.prompt,
        negative_prompt=image.negative_prompt,
        aspect_ratio=image.aspect_ratio,
        style_preset=image.style_preset,
        visual_params=visual_params,
        output_dir=str(IMAGE_OUTPUT_DIR),
    )
    if not result.success:
        update_generated_image(image_id, status="failed", error_message=result.error_message)
        raise UserFacingError(result.error_message)
    status = "generated_local"
    public_url = ""
    error_message = "图片已生成到本地。当前未配置稳定云端图片存储，SiliconFlow 临时链接不会用于最终发布。"
    update_generated_image(
        image_id,
        provider=provider_name,
        model=model_name,
        local_path=result.local_path,
        public_url=public_url,
        status=status,
        error_message=error_message,
    )
    stable_url = try_upload_generated_image_to_storage(image_id)
    if stable_url:
        update_generated_image(image_id, public_url=stable_url, status="uploaded_public", selected=True, error_message="")


def insert_image_into_task_markdown(task_id: str, image_id: int) -> None:
    task = get_task(task_id)
    image = get_generated_image(image_id)
    if task is None or image is None:
        raise UserFacingError("没有找到文章或图片。")
    if image.image_role != "inline":
        raise UserFacingError("封面图不插入正文。")
    markdown = task.get("original_markdown") or task.get("markdown") or ""
    updated = insert_image_placeholder(
        markdown,
        image.slot_key,
        image.insert_position or "after_intro",
        image_related_section_title(image),
        replace_existing=True,
    )
    update_task(task_id, {"markdown": updated, "original_markdown": updated, "polished_markdown": ""})
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, updated)
    export_markdown(task_id)


def apply_cover_to_task_markdown(task_id: str, image_id: int) -> None:
    task = get_task(task_id)
    image = get_generated_image(image_id)
    if task is None or image is None:
        raise UserFacingError("没有找到文章或图片。")
    if image.image_role != "cover":
        raise UserFacingError("这张图片不是封面图。")
    markdown = task.get("original_markdown") or task.get("markdown") or ""
    updated = insert_cover_placeholder(markdown, image.slot_key or "cover")
    update_generated_image(image.id, selected=True, status="selected")
    update_task(task_id, {"markdown": updated, "original_markdown": updated, "polished_markdown": ""})
    draft = sync_article_draft_from_task(task_id)
    if draft is not None:
        sync_image_status_from_markdown(draft.id, updated)
    export_markdown(task_id)


def update_image_meta(image_id: int, values: Mapping[str, object]) -> None:
    update_generated_image(
        image_id,
        prompt=str(values.get("prompt", "")),
        negative_prompt=str(values.get("negative_prompt", "")),
        alt_text=str(values.get("alt_text", "")),
        caption=str(values.get("caption", "")),
        insert_position=str(values.get("insert_position", "not_inserted")),
        aspect_ratio=str(values.get("aspect_ratio", "16:9")),
        style_preset=str(values.get("style_preset", "温和治愈插画")),
        selected=bool(values.get("selected", True)),
    )


def looks_like_english_text(text: str) -> bool:
    letters = re.findall(r"[A-Za-z]", text or "")
    chinese = re.findall(r"[\u4e00-\u9fff]", text or "")
    return len(letters) >= 20 and len(letters) > len(chinese) * 2


def localize_image_prompt_to_chinese(image_id: int) -> None:
    image = get_generated_image(image_id)
    if image is None:
        raise UserFacingError("图片记录不存在。")
    params = visual_params_dict(image.visual_params)
    prompt = f"""
你是公众号图片提示词编辑。

请把下面图片计划中的英文或中英混合内容改写成中文。

要求：
1. 只改语言，不改变画面含义。
2. 保留视觉导演级细节：主体、场景、构图、光线、色彩、镜头、情绪、风格。
3. 负向提示词也必须是中文。
4. 不新增真实患者、病历、诊断书、药物、医院病床、自伤、自杀、血腥、标识、水印等元素。
5. 严禁输出 <think>、Thinking Process、推理过程。
6. 只输出 JSON，不要输出解释。

当前图片用途：{image.image_role}
当前编号：{image.slot_key}
当前图片提示词：
{image.prompt}

当前负向提示词：
{image.negative_prompt or DEFAULT_NEGATIVE_PROMPT}

当前图注：
{image.caption}

当前图片说明：
{image.alt_text}

当前视觉参数：
{json.dumps(params, ensure_ascii=False)}

请输出 JSON：
{{
  "prompt": "中文图片提示词",
  "negative_prompt": "中文负向提示词",
  "alt_text": "中文图片说明",
  "caption": "中文图注",
  "visual_params": {{
    "subject": "中文主体描述",
    "scene": "中文场景描述",
    "composition": "中文构图描述",
    "lighting": "中文光线描述",
    "color_palette": "中文色彩描述",
    "camera": "中文镜头和景别描述",
    "mood": "中文情绪氛围描述",
    "scene_purpose": "中文画面目标",
    "related_section_title": "中文对应小节标题"
  }}
}}
"""
    data = extract_json_object(call_deepseek(get_config(), prompt, temperature=0.2))
    visual_params = data.get("visual_params", params)
    if not isinstance(visual_params, dict):
        visual_params = params
    update_generated_image(
        image_id,
        prompt=sanitize_model_text(str(data.get("prompt", image.prompt))).strip(),
        negative_prompt=sanitize_model_text(str(data.get("negative_prompt", image.negative_prompt or DEFAULT_NEGATIVE_PROMPT))).strip(),
        alt_text=sanitize_model_text(str(data.get("alt_text", image.alt_text))).strip(),
        caption=sanitize_model_text(str(data.get("caption", image.caption))).strip(),
        visual_params=visual_params_json(visual_params),
        error_message="",
    )


def promote_backup_image(article_draft_id: int, image_id: int, target_role: str) -> None:
    image = get_generated_image(image_id)
    if image is None:
        raise UserFacingError("图片记录不存在。")
    if target_role == "cover":
        update_generated_image(image_id, image_role="cover", slot_key="cover", insert_position="cover_only", aspect_ratio="2.35:1", status="prompt_ready")
    else:
        update_generated_image(image_id, image_role="inline", slot_key=next_inline_slot(article_draft_id), insert_position="after_intro", status="not_inserted")


def local_image_data_uri(path_text: str) -> str:
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return ""
    suffix = path.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_preview_src(image) -> str:
    if image.public_url and not is_temporary_image_url(image.public_url):
        return image.public_url
    if image.local_path:
        return local_image_data_uri(image.local_path)
    if image.public_url:
        return image.public_url
    return ""


def render_image_chip_row(items: Sequence[tuple[str, object]]) -> None:
    chips = []
    for label, value in items:
        text = f"{label}：{value or '暂无'}"
        chips.append(f'<span class="image-chip">{escape(str(text))}</span>')
    st.markdown(f'<div class="image-chip-row">{"".join(chips)}</div>', unsafe_allow_html=True)


def render_image_thumbnail(image) -> None:
    src = image_preview_src(image)
    if src:
        alt = escape(image.alt_text or image.caption or image.slot_key)
        st.markdown(f'<img class="image-thumb" src="{escape(src)}" alt="{alt}">', unsafe_allow_html=True)
    else:
        st.markdown('<div class="image-thumb-empty">暂无图片预览</div>', unsafe_allow_html=True)


def render_image_full_preview(image) -> None:
    if image.local_path and Path(image.local_path).exists():
        st.image(image.local_path, caption=image.caption or image.alt_text or None, use_container_width=True)
    elif image.public_url:
        st.image(image.public_url, caption=image.caption or image.alt_text or None, use_container_width=True)
    else:
        st.caption("暂无图片预览。")


def render_generated_image_card(task_id: str, draft_id: int, image) -> None:
    role_label = {"cover": "封面图", "inline": "正文配图", "backup": "备用图"}.get(image.image_role, image.image_role)
    params = visual_params_dict(image.visual_params)
    scene_purpose = str(params.get("scene_purpose") or params.get("purpose") or "暂无")
    related_section = str(params.get("related_section_title") or params.get("section") or ("封面" if image.image_role == "cover" else "未指定小节"))
    task = get_task(task_id)
    current_markdown = (task.get("original_markdown") or task.get("markdown") or "") if task else ""
    applied_slots = markdown_placeholders(current_markdown)
    with st.container(border=True):
        st.markdown(f"##### {role_label}｜{image.slot_key}")
        render_image_chip_row(
            [
                ("状态", image_status_label(image.status)),
                ("链接", image_link_status_label(image)),
                ("画幅", image.aspect_ratio),
                ("小节", related_section),
                ("位置", IMAGE_INSERT_LABELS.get(image.insert_position, image.insert_position)),
            ]
        )
        st.markdown(f'<div class="image-purpose">画面目标：{escape(scene_purpose)}</div>', unsafe_allow_html=True)
        preview_col, quick_col = st.columns([0.95, 1.05])
        with preview_col:
            render_image_thumbnail(image)
        with quick_col:
            if image.image_role == "inline":
                if image.slot_key in applied_slots:
                    st.button("已应用到正文", disabled=True, use_container_width=True, key=f"inserted_disabled_{image.id}")
                    if st.button("重新匹配位置", key=f"reposition_image_placeholder_{image.id}", use_container_width=True):
                        try:
                            insert_image_into_task_markdown(task_id, image.id)
                            set_flash("图片位置已按对应小节重新整理。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                    if st.button("取消应用", key=f"remove_image_placeholder_{image.id}", use_container_width=True):
                        try:
                            remove_image_from_task_markdown(task_id, image.id)
                            set_flash("已从正文中移除图片占位符。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                else:
                    if st.button("应用到正文", key=f"insert_image_{image.id}", type="primary", use_container_width=True, disabled=not image_is_generated(image)):
                        try:
                            insert_image_into_task_markdown(task_id, image.id)
                            set_flash("图片已应用到正文。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                    if not image_is_generated(image):
                        st.caption("先生成图片后再应用到正文。")
            elif image.image_role == "backup":
                if st.button("设为正文配图", key=f"promote_inline_{image.id}", use_container_width=True):
                    promote_backup_image(draft_id, image.id, "inline")
                    st.rerun()
                if st.button("设为封面", key=f"promote_cover_{image.id}", use_container_width=True):
                    promote_backup_image(draft_id, image.id, "cover")
                    st.rerun()
            else:
                if image.slot_key in applied_slots:
                    st.button("已应用到正文", disabled=True, use_container_width=True, key=f"cover_applied_disabled_{image.id}")
                    if st.button("取消应用", key=f"remove_cover_placeholder_{image.id}", use_container_width=True):
                        try:
                            remove_image_from_task_markdown(task_id, image.id)
                            set_flash("已从正文中移除封面图占位符。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                else:
                    if st.button("设为封面并应用到正文", key=f"select_cover_{image.id}", type="primary", use_container_width=True, disabled=not image_is_generated(image)):
                        try:
                            apply_cover_to_task_markdown(task_id, image.id)
                            set_flash("封面图已应用到正文开头。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                    if not image_is_generated(image):
                        st.caption("先生成封面图后再应用到正文。")

            if st.button("生成 / 重新生成图片", key=f"generate_image_{image.id}", use_container_width=True):
                try:
                    generate_image_with_provider(image.id)
                    set_flash("图片已生成。")
                    st.rerun()
                except Exception as exc:
                    st.warning(str(exc))

        with st.expander("预览大图", expanded=False):
            render_image_full_preview(image)

        with st.expander("图片提示词", expanded=False):
            st.text_area("图片提示词", value=image.prompt, height=130, disabled=True, key=f"image_prompt_read_{image.id}")
            prompt_cols = st.columns(2)
            with prompt_cols[0]:
                render_copy_button(image.prompt, f"复制提示词 {image.slot_key}", "已复制提示词")
            with prompt_cols[1]:
                button_label = "转为中文提示词" if looks_like_english_text(image.prompt) else "重新整理为中文"
                if st.button(button_label, key=f"localize_prompt_{image.id}", use_container_width=True):
                    progress = st.empty()
                    try:
                        progress.info("正在整理中文提示词，请稍等...")
                        localize_image_prompt_to_chinese(image.id)
                        progress.empty()
                        set_flash("图片提示词已转为中文。")
                        st.rerun()
                    except Exception as exc:
                        progress.empty()
                        st.error(str(exc))
            st.caption("日常只需要复制这一段完整提示词。需要调整画幅、风格或负向提示词时，可展开下方编辑区。")

        with st.expander("编辑提示词与图片信息", expanded=False):
            with st.form(f"image_meta_form_{image.id}"):
                prompt = st.text_area("图片提示词", value=image.prompt, height=90)
                negative_prompt = st.text_area("负向提示词", value=image.negative_prompt or DEFAULT_NEGATIVE_PROMPT, height=70)
                alt_text = st.text_input("图片说明", value=image.alt_text)
                caption = st.text_input("图注", value=image.caption)
                aspect_ratio = st.selectbox("画幅比例", IMAGE_ASPECT_RATIOS, index=option_index(IMAGE_ASPECT_RATIOS, image.aspect_ratio))
                style_preset = st.selectbox("图片风格", IMAGE_STYLE_PRESETS, index=option_index(IMAGE_STYLE_PRESETS, image.style_preset))
                insert_position = st.selectbox(
                    "插入位置",
                    IMAGE_INSERT_POSITIONS,
                    index=option_index(IMAGE_INSERT_POSITIONS, image.insert_position),
                    format_func=lambda value: IMAGE_INSERT_LABELS.get(value, value),
                )
                selected = st.checkbox("用于最终图文版", value=bool(image.selected))
                saved = st.form_submit_button("保存图片信息", type="primary")
            if saved:
                update_image_meta(
                    image.id,
                    {
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "alt_text": alt_text,
                        "caption": caption,
                        "aspect_ratio": aspect_ratio,
                        "style_preset": style_preset,
                        "insert_position": insert_position,
                        "selected": selected,
                    },
                )
                set_flash("图片信息已保存。")
                st.rerun()

        with st.expander("图片链接、上传和下载", expanded=False):
            public_url = st.text_input("图片链接", value=image.public_url, key=f"image_url_{image.id}", placeholder="粘贴公网 HTTPS 图片链接")
            url_cols = st.columns(2)
            with url_cols[0]:
                if st.button("保存图片链接", key=f"save_image_url_{image.id}", use_container_width=True):
                    try:
                        save_manual_image_url(image.id, public_url)
                        if is_local_public_url(public_url):
                            set_flash("图片链接已保存，但它可能仅本机可访问。建议使用公网 HTTPS 链接。", "warning")
                        else:
                            set_flash("图片链接已保存。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            with url_cols[1]:
                if is_publishable_image_url(image.public_url):
                    render_copy_button(image.public_url, f"复制图片链接 {image.slot_key}", "已复制链接")
                elif image.public_url:
                    st.button("临时链接不可发布", disabled=True, use_container_width=True, key=f"copy_temp_image_url_disabled_{image.id}")
                else:
                    st.button("复制图片链接", disabled=True, use_container_width=True, key=f"copy_image_url_disabled_{image.id}")

            uploaded = st.file_uploader("手动上传图片", type=["png", "jpg", "jpeg", "webp"], key=f"upload_image_{image.id}")
            upload_cols = st.columns(3)
            with upload_cols[0]:
                if st.button("保存上传图片", key=f"save_upload_{image.id}", use_container_width=True):
                    try:
                        save_uploaded_image_file(image.id, uploaded)
                        set_flash("图片已保存到本地。若要复制到 Raphael 后直接显示，请填写公网图片链接。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            with upload_cols[1]:
                if st.button("生成稳定发布链接", key=f"upload_public_{image.id}", use_container_width=True, disabled=not storage_upload_is_configured()):
                    try:
                        upload_image_to_storage(image.id)
                        set_flash("图片链接已生成。")
                        st.rerun()
                    except Exception as exc:
                        st.warning(str(exc))
            with upload_cols[2]:
                if image.local_path and Path(image.local_path).exists():
                    st.download_button(
                        "下载图片",
                        data=Path(image.local_path).read_bytes(),
                        file_name=Path(image.local_path).name,
                        use_container_width=True,
                    )
                else:
                    st.button("下载图片", disabled=True, use_container_width=True, key=f"download_disabled_{image.id}")

        more_cols = st.columns(2)
        with more_cols[0]:
            if image.image_role == "cover":
                if st.button("重写封面提示词", key=f"regen_cover_prompt_{image.id}", use_container_width=True):
                    try:
                        regenerate_image_plan(task_id, "cover", image.id)
                        set_flash("封面图提示词已更新，已有图片不会被删除。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            elif image.image_role == "inline":
                if st.button("重写配图提示词", key=f"regen_inline_prompt_{image.id}", use_container_width=True):
                    try:
                        regenerate_image_plan(task_id, "inline", image.id)
                        set_flash("正文配图提示词已更新，已有图片不会被删除。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        with more_cols[1]:
            if image.image_role != "cover":
                if st.button("删除", key=f"delete_image_{image.id}", use_container_width=True):
                    delete_generated_image(image.id)
                    set_flash("图片记录已删除。")
                    st.rerun()
        if image.error_message:
            st.warning(image.error_message)


def render_image_generation_center(task_id: str, draft_id: int) -> None:
    images = list_generated_images(draft_id)
    st.markdown("#### 图片生成中心")
    st.caption("系统会生成图片、插入正文，并为最终发布准备稳定 HTTPS 图片链接。临时图片链接不会进入最终图文 Markdown。")
    total = len(images)
    cover_count = len([image for image in images if image.image_role == "cover"])
    inline_count = len([image for image in images if image.image_role == "inline"])
    backup_count = len([image for image in images if image.image_role == "backup"])
    generated_count = len([image for image in images if image_is_generated(image)])
    link_count = len([image for image in images if image_has_usable_link(image)])
    inserted_count = len([image for image in images if image.image_role == "inline" and image.status == "inserted"])
    render_compact_info_grid(
        [
            ("图片计划", f"{cover_count} 张封面 + {inline_count} 张正文 + {backup_count} 张备用"),
            ("已生成", f"{generated_count} / {total}"),
            ("可发布链接", f"{link_count} / {total}"),
            ("已插入正文", f"{inserted_count} / {inline_count or 1}"),
        ],
        columns=4,
    )
    action_top_cols = st.columns(2)
    with action_top_cols[0]:
        if st.button("重新生成图片计划", key=f"regen_image_plan_{task_id}", use_container_width=True):
            try:
                regenerate_image_plan(task_id, "all")
                set_flash("图片计划已重新生成，已有图片文件和链接会尽量保留。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with action_top_cols[1]:
        current_task = get_task(task_id)
        current_markdown = (current_task.get("original_markdown") or current_task.get("markdown") or "") if current_task else ""
        applicable_count = len(
            [
                image
                for image in images
                if image.image_role in {"cover", "inline"} and (image_is_generated(image) or image.slot_key in markdown_placeholders(current_markdown))
            ]
        )
        if st.button("应用并整理图片到正文", key=f"apply_generated_images_{task_id}", type="primary", use_container_width=True, disabled=applicable_count == 0):
            try:
                count = apply_generated_images_to_task_markdown(task_id, draft_id)
                set_flash(f"已应用或整理 {count} 张图片。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    action_bottom_cols = st.columns(3)
    with action_bottom_cols[0]:
        missing_count = len([image for image in images if image.image_role != "backup" and not image_is_generated(image)])
        generate_label = f"生成 {missing_count} 张图片" if missing_count else "图片已全部生成"
        if st.button(generate_label, key=f"generate_all_images_{task_id}", use_container_width=True, disabled=missing_count == 0):
            try:
                count = generate_all_missing_images(draft_id)
                set_flash(f"已生成 {count} 张图片。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with action_bottom_cols[1]:
        stable_link_count = len([image for image in images if image.image_role != "backup" and image.local_path and not image_has_usable_link(image)])
        storage_ready = storage_upload_is_configured()
        stable_label = f"生成 {stable_link_count} 个稳定链接" if stable_link_count else "稳定链接已完成"
        if st.button(stable_label, key=f"upload_all_images_{task_id}", use_container_width=True, disabled=stable_link_count == 0 or not storage_ready):
            try:
                count = upload_all_images_to_storage(draft_id)
                set_flash(f"已生成 {count} 张稳定发布图片链接。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if stable_link_count > 0 and not storage_ready:
            st.caption("需先配置稳定云端图片存储。")
    with action_bottom_cols[2]:
        if st.button("新增正文配图", key=f"add_inline_image_{task_id}", use_container_width=True):
            try:
                regenerate_image_plan(task_id, "add_inline")
                set_flash("已新增一张正文配图计划。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    settings = get_app_settings_map()
    if get_runtime_setting("IMAGE_PROVIDER", settings.get("image_provider", "dummy")) == "dummy":
        st.info("当前尚未配置图片生成模型。你可以先复制提示词去其他工具生成图片，或上传已有图片。")
    if get_runtime_setting("IMAGE_PROVIDER", settings.get("image_provider", "dummy")).strip().lower() in {"siliconflow", "silicon_flow"}:
        st.info("当前已接入 SiliconFlow 图片生成。平台返回的是临时链接，系统会优先使用本地图片上传后的稳定发布链接。")
    if get_runtime_setting("IMAGE_STORAGE_PROVIDER", settings.get("image_storage_provider", "manual_url")) == "manual_url":
        st.warning("当前尚未配置稳定云端图片存储。复制到公众号前，请先配置 Cloudinary / OSS / 部署静态图片链接，或手动填写稳定 HTTPS 图片链接。")
    if not images:
        st.warning("当前文章还没有图片计划。可以点击“重新生成图片计划”。")
        return
    groups = [
        ("封面图", [image for image in images if image.image_role == "cover"]),
        ("正文配图", [image for image in images if image.image_role == "inline"]),
        ("备用图", [image for image in images if image.image_role == "backup"]),
    ]
    for title, group in groups:
        with st.expander(title, expanded=title != "备用图"):
            if not group:
                st.caption("暂无。")
            for image in group:
                render_generated_image_card(task_id, draft_id, image)


def render_task_detail_page(tasks: List[Dict[str, str]]) -> None:
    st.subheader("文章详情 / 审核发布页")
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
    draft = get_article_draft_by_legacy_task(task["task_id"])
    source_name = "直接创建"
    referenced_items_text = "暂无"
    duplicate_check = ""
    if draft is not None:
        if draft.knowledge_base_id:
            base = orm_get_knowledge_base(int(draft.knowledge_base_id))
            source_name = base.name if base else "知识库"
        elif draft.source_type == "knowledge_base":
            source_name = "知识库"
        if draft.referenced_items:
            try:
                refs = json.loads(draft.referenced_items)
                if isinstance(refs, list) and refs:
                    referenced_items_text = "、".join(str(ref) for ref in refs)
            except json.JSONDecodeError:
                referenced_items_text = draft.referenced_items
        duplicate_check = draft.duplicate_check_result or ""

    status = task["status"]
    reviewed_statuses = {"审核通过", "排版中", "已发布"}
    can_publish_actions = status in reviewed_statuses

    st.markdown(f"### {task['title'] or task['article_topic'] or '未命名稿件'}")
    top_cols = st.columns(5)
    top_cols[0].metric("状态", status or "待输入")
    top_cols[1].metric("风险等级", task["risk_level"] or "未生成")
    top_cols[2].metric("来源知识库", source_name)
    top_cols[3].metric("生成时间", task["created_at"] or "未记录")
    top_cols[4].metric("更新时间", task["updated_at"] or "未记录")
    show_boundary_notice()

    if not source_markdown:
        st.warning("这篇稿件还没有生成正文。请先点击“生成文案”。")
        run_action("生成文案", generate_article, task["task_id"], button_type="primary")
        return
    draft = ensure_image_records_for_task(task["task_id"])
    task = get_task(selected) or task
    source_markdown = task.get("original_markdown") or task.get("markdown") or ""

    left, right = st.columns([1.45, 1])
    with left:
        st.markdown("#### 正文编辑主区")
        edited_title = st.text_input("文章标题", value=task["title"])
        edited_digest = st.text_area("文章摘要", value=task["digest"], height=90)
        view_mode = st.radio("正文模式", ["编辑模式", "预览模式"], horizontal=True, key=f"detail_view_mode_{task['task_id']}")
        if view_mode == "编辑模式":
            edited_markdown = st.text_area(
                "公众号正文 Markdown",
                value=source_markdown,
                height=620,
                help="正文中如需插图，保留 {{image:inline_1}} 这类图片占位符。",
            )
        else:
            edited_markdown = source_markdown
            st.caption("预览模式只用于查看最终阅读效果，不用于编辑。")
            if draft is not None:
                render_article_markdown_preview(draft.id, source_markdown)
            else:
                st.markdown(source_markdown)

        save_cols = st.columns(2)
        with save_cols[0]:
            if st.button("保存修改", type="primary", use_container_width=True):
                try:
                    save_manual_edits(task["task_id"], edited_title, edited_digest, edited_markdown)
                    if draft is not None:
                        unknown = unknown_image_placeholders(draft.id, edited_markdown)
                        if unknown:
                            set_flash("已保存。发现未识别图片占位符：" + "、".join(unknown) + "，请在图片生成中心新增对应配图或手动调整。", "warning")
                        else:
                            set_flash("已保存修改。")
                    else:
                        set_flash("已保存修改。")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        with save_cols[1]:
            review_label = "提交复审" if status in {"待修改", "需修改"} else "保存并重新审核"
            if st.button(review_label, use_container_width=True):
                progress = st.empty()
                try:
                    progress.info("正在保存并重新审核，请稍等...")
                    save_and_rerun_risk_review(task["task_id"], edited_title, edited_digest, edited_markdown)
                    progress.empty()
                    set_flash("已保存并完成风险审核，状态已回到待审核。")
                    st.rerun()
                except Exception as exc:
                    progress.empty()
                    st.error(str(exc))

        with st.expander("辅助修改", expanded=False):
            st.caption("这些是 AI 辅助工具，不会自动发布。修改后建议人工检查。")
            aux_cols = st.columns(3)
            with aux_cols[0]:
                run_action("重新生成标题", simple_regenerate, task["task_id"], "title_prompt.txt", ["title"])
            with aux_cols[1]:
                run_action("重新生成摘要", simple_regenerate, task["task_id"], "digest_prompt.txt", ["digest"])
            with aux_cols[2]:
                run_action(
                    "润色正文",
                    request_revision_and_regenerate,
                    task["task_id"],
                    "请在不改变原意和结构的前提下，润色表达，让文章更顺畅、更适合公众号阅读。",
                    key=f"polish_body_{task['task_id']}",
                )
            aux_cols2 = st.columns(3)
            with aux_cols2[0]:
                if st.button("一键优化排版", key=f"layout_preview_btn_{task['task_id']}", use_container_width=True):
                    progress = st.empty()
                    try:
                        progress.info("正在生成轻量排版优化预览，请稍等...")
                        st.session_state[f"layout_preview_{task['task_id']}"] = build_layout_preview(task["task_id"])
                        progress.empty()
                        set_flash("已生成排版优化预览，确认后才会应用。")
                        st.rerun()
                    except Exception as exc:
                        progress.empty()
                        st.error(str(exc))
            with aux_cols2[1]:
                if st.button("重新生成图片计划", key=f"regen_plan_aux_{task['task_id']}", use_container_width=True):
                    progress = st.empty()
                    try:
                        progress.info("正在重新生成图片计划，请稍等...")
                        regenerate_image_plan(task["task_id"], "all")
                        progress.empty()
                        set_flash("图片计划已重新生成。")
                        st.rerun()
                    except Exception as exc:
                        progress.empty()
                        st.error(str(exc))
            with aux_cols2[2]:
                run_action("重新风险审核", rerun_risk_review, task["task_id"], key=f"rerisk_{task['task_id']}")

            layout_preview_key = f"layout_preview_{task['task_id']}"
            if st.session_state.get(layout_preview_key):
                st.markdown("##### 一键优化排版预览")
                st.caption("轻量优化正文结构，方便后续粘贴到 Raphael 排版预览。确认后才会应用。")
                st.text_area("优化后的 Markdown", value=st.session_state[layout_preview_key], height=260, key=f"layout_preview_text_{task['task_id']}")
                apply_cols = st.columns(2)
                with apply_cols[0]:
                    if st.button("应用优化结果", type="primary", use_container_width=True, key=f"apply_layout_{task['task_id']}"):
                        try:
                            apply_layout_preview(task["task_id"], st.session_state[layout_preview_key])
                            st.session_state.pop(layout_preview_key, None)
                            set_flash("已应用优化结果。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                with apply_cols[1]:
                    if st.button("放弃优化结果", use_container_width=True, key=f"discard_layout_{task['task_id']}"):
                        st.session_state.pop(layout_preview_key, None)
                        st.rerun()

            st.markdown("##### 退回修改")
            with st.form(f"revision_form_{task['task_id']}"):
                revision_feedback = st.text_area(
                    "修改意见",
                    value=task.get("rewrite_instruction", ""),
                    height=100,
                    placeholder="例如：语气再轻松一点、去掉第二段、增加一个实际建议、标题不要太夸张、图片提示词更有生活感。",
                )
                revision_mode = st.radio("处理方式", ["AI 根据修改意见重写正文", "仅记录修改意见，我手动修改"], horizontal=False)
                revision_submitted = st.form_submit_button("确认退回修改", type="primary")
            if revision_submitted:
                if revision_mode == "仅记录修改意见，我手动修改":
                    update_task(task["task_id"], {"rewrite_instruction": revision_feedback, "status": "需修改"})
                    set_flash("已记录修改意见，稿件状态已设为需修改。")
                    st.rerun()
                progress = st.empty()
                try:
                    progress.info("正在根据修改意见生成预览，请稍等...")
                    st.session_state[f"revision_preview_{task['task_id']}"] = build_revision_preview(task["task_id"], revision_feedback)
                    progress.empty()
                    set_flash("已生成修改预览，确认后才会应用。")
                    st.rerun()
                except Exception as exc:
                    progress.empty()
                    st.error(str(exc))

            revision_preview_key = f"revision_preview_{task['task_id']}"
            revision_preview = st.session_state.get(revision_preview_key)
            if revision_preview:
                st.markdown("##### 修改预览")
                st.text_input("预览标题", value=revision_preview.get("title", ""), disabled=True, key=f"revision_title_preview_{task['task_id']}")
                st.text_area("预览摘要", value=revision_preview.get("digest", ""), height=80, disabled=True, key=f"revision_digest_preview_{task['task_id']}")
                st.text_area("预览正文", value=revision_preview.get("markdown", ""), height=260, disabled=True, key=f"revision_markdown_preview_{task['task_id']}")
                preview_cols = st.columns(2)
                with preview_cols[0]:
                    if st.button("应用修改预览", type="primary", use_container_width=True, key=f"apply_revision_{task['task_id']}"):
                        try:
                            apply_revision_preview(task["task_id"], revision_preview)
                            st.session_state.pop(revision_preview_key, None)
                            set_flash("已应用修改预览，状态回到待审核。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                with preview_cols[1]:
                    if st.button("放弃修改预览", use_container_width=True, key=f"discard_revision_{task['task_id']}"):
                        st.session_state.pop(revision_preview_key, None)
                        st.rerun()

        if task["change_summary"]:
            st.info("最近修改摘要：" + task["change_summary"])

    with right:
        with st.container(height=860, border=False):
            st.markdown("#### 审核与图片")
            render_compact_info_grid(
                [
                    ("当前状态", task_status_label(status)),
                    ("风险等级", task["risk_level"] or "未生成"),
                    ("最近审核", task["updated_at"] or "未记录"),
                ],
                columns=3,
            )
            st.markdown("##### 风险审核报告")
            st.markdown(task["risk_report"] or "暂无风险审核报告。")
            if task["doctor_review_note"]:
                st.warning(task["doctor_review_note"])

            with st.expander("引用内容与重复检查", expanded=False):
                st.markdown("**引用内容**")
                st.write(referenced_items_text)
                st.markdown("**重复检查结果**")
                st.write(duplicate_check or "暂无重复检查结果。")
                if task.get("retrieved_knowledge"):
                    st.text_area("知识库参考", value=task["retrieved_knowledge"], height=220, disabled=True)

            if draft is not None:
                render_image_generation_center(task["task_id"], draft.id)

    st.divider()
    st.markdown("#### 审核与发布前准备")
    action_cols = st.columns(5)
    with action_cols[0]:
        if status in {"已生成", "已生成，待审核", "待修改", "待审核"}:
            if st.button("审核通过", type="primary", use_container_width=True):
                mark_status(task["task_id"], "审核通过")
                set_flash("已审核通过，可以复制文字版或图文版 Markdown。")
                st.rerun()
        else:
            st.button("审核通过", disabled=True, use_container_width=True)
    with action_cols[1]:
        if can_publish_actions:
            text_only_markdown = build_publish_markdown_for_task(task["task_id"], "text_only")
            render_browser_copy_button(
                "复制文字版 Markdown",
                text_only_markdown,
                key=f"detail_text_copy_{task['task_id']}",
                success_message="文字版 Markdown 已复制。",
            )
        else:
            st.button("复制文字版", disabled=True, help="审核通过后才能复制发布内容。", use_container_width=True)
    with action_cols[2]:
        if can_publish_actions:
            with_images_markdown = build_publish_markdown_for_task(task["task_id"], "with_images")
            render_browser_copy_button(
                "复制图文版 Markdown",
                with_images_markdown,
                key=f"detail_image_copy_{task['task_id']}",
                success_message="图文版 Markdown 已复制。",
            )
        else:
            st.button("复制图文版", disabled=True, help="审核通过后才能复制发布内容。", use_container_width=True)
    with action_cols[3]:
        if can_publish_actions:
            st.link_button("打开 Raphael 排版预览", RAPHAEL_URL, use_container_width=True)
        else:
            st.button("打开 Raphael", disabled=True, help="审核通过后才能进入发布前准备。", use_container_width=True)
    with action_cols[4]:
        if can_publish_actions:
            run_action("标记为已发布", mark_status, task["task_id"], "已发布", "published_at", key=f"mark_published_{task['task_id']}")
        else:
            st.button("标记为已发布", disabled=True, use_container_width=True)

    missing_images = missing_public_url_images(task["task_id"]) if can_publish_actions else []
    if missing_images:
        st.warning("当前部分图片没有稳定 HTTPS 发布链接，图文版 Markdown 会保留插图占位。请先在图片生成中心点击“生成稳定发布链接”，或手动填写稳定公网图片链接。")
    render_publish_preview_card(task["task_id"], can_publish_actions)
    st.caption("复制 Markdown 后，在 Raphael 中粘贴预览，再复制到公众号后台。系统不会自动发布公众号。")
    with st.expander("复制兜底 / 下载 Markdown", expanded=False):
        fallback_mode = st.radio("选择复制版本", ["文字版", "图文版"], horizontal=True, key=f"fallback_publish_mode_{task['task_id']}")
        fallback_markdown = build_publish_markdown_for_task(task["task_id"], "with_images" if fallback_mode == "图文版" else "text_only") if can_publish_actions else final_markdown(task)
        st.text_area("最终 Markdown，可手动全选复制", value=fallback_markdown, height=320)
        st.download_button(
            "下载 Markdown 文件",
            data=fallback_markdown.encode("utf-8"),
            file_name=f"{task_id_to_filename(task['task_id'])}.md",
            mime="text/markdown",
        )


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

    if task["status"] not in {"审核通过", "排版中", "已发布"}:
        st.warning("未审核通过，不能进入排版发布。请先在任务详情 / 编辑页提交医生审核并审核通过。")
        return
    if task["status"] == "审核通过":
        mark_status(task["task_id"], "排版中")
        st.rerun()

    text_only_markdown = build_publish_markdown_for_task(task["task_id"], "text_only")
    with_images_markdown = build_publish_markdown_for_task(task["task_id"], "with_images")
    missing_images = missing_public_url_images(task["task_id"])
    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### 发布 Markdown")
        version = st.radio("选择版本", ["图文版", "文字版"], horizontal=True)
        markdown = with_images_markdown if version == "图文版" else text_only_markdown
        if version == "图文版" and missing_images:
            st.warning("当前部分图片没有稳定 HTTPS 发布链接，图文版 Markdown 已保留插图占位。请先回到图片生成中心生成稳定发布链接。")
        elif version == "图文版":
            st.success("当前图文版 Markdown 已使用稳定 HTTPS 图片链接，可进入 Raphael 或公众号后台做最终检查。")
        render_copy_button(markdown, f"复制{version} Markdown", f"已复制{version}")
        st.text_area("Markdown 内容", value=markdown, height=680)
        st.download_button(
            f"下载{version} Markdown",
            data=markdown.encode("utf-8"),
            file_name=f"{task_id_to_filename(task['task_id'])}_{version}.md",
            mime="text/markdown",
        )
        st.link_button("打开 Raphael（新窗口，推荐）", RAPHAEL_URL)
        st.info("推荐复制 Markdown 后，在新窗口打开 Raphael 使用。右侧内嵌预览可能受第三方 iframe 限制。")
        run_action("标记为已发布", mark_status, task["task_id"], "已发布", "published_at", button_type="primary")

    with right:
        st.markdown("#### Raphael 排版预览")
        st.warning("如果右侧无法显示，或选择款式、设备预览按钮没有反应，这是 Raphael 在第三方 iframe 中的限制。请点击“打开 Raphael（新窗口，推荐）”使用完整功能。")
        components.iframe(RAPHAEL_URL, height=760, scrolling=True)


def render_knowledge_topic_cards(
    topics: List[Dict[str, object]],
    *,
    knowledge_base_id: int,
    writing_style: str,
    article_length: str,
    session_key: str,
) -> None:
    if not topics:
        return
    st.markdown("#### 推荐选题")
    top_cols = st.columns([1, 1, 3])
    with top_cols[0]:
        if st.button("批量生成 3 篇", type="primary", use_container_width=True, key=f"batch_generate_{session_key}"):
            progress = st.empty()
            try:
                for index, topic in enumerate(topics[:3], start=1):
                    progress.info(f"正在生成第 {index} 篇文章，请稍等...")
                    task_id = create_article_task_from_knowledge_topic(
                        knowledge_base_id=knowledge_base_id,
                        title=str(topic.get("title", "")),
                        target_reader=str(topic.get("target_reader", "")),
                        core_viewpoint=str(topic.get("core_viewpoint", "")),
                        topic_angle=str(topic.get("topic_angle", "")),
                        risk_tags=topic.get("risk_tags", []),
                        referenced_items=topic.get("referenced_items", []),
                        retrieved_knowledge=str(topic.get("retrieved_knowledge", "")),
                        duplicate_check_result=str(topic.get("duplicate_check_result", "")),
                        writing_style=writing_style,
                        article_length=article_length,
                        topic_history_id=int(topic.get("topic_history_id") or 0) or None,
                    )
                    st.session_state["selected_task_id"] = task_id
                progress.empty()
                set_flash("已批量生成 3 篇文章任务，请到历史稿件查看并审核。")
                go_to_page("历史稿件")
                st.rerun()
            except Exception as exc:
                progress.empty()
                st.error(str(exc))
    with top_cols[1]:
        if st.button("清空选题", use_container_width=True, key=f"clear_topics_{session_key}"):
            st.session_state.pop(session_key, None)
            st.rerun()
    with top_cols[2]:
        st.info("生成后的文章会进入“已生成，待审核”，仍需人工审核后才能进入排版。")

    for index, topic in enumerate(topics, start=1):
        with st.container(border=True):
            st.markdown(f"### {index}. {topic.get('title', '未命名选题')}")
            st.markdown(f"**目标读者：** {topic.get('target_reader') or '公众号读者'}")
            st.markdown(f"**核心观点：** {topic.get('core_viewpoint') or '未填写'}")
            st.markdown(f"**文章角度：** {topic.get('topic_angle') or '未填写'}")
            st.markdown(f"**重复检查结果：** {topic.get('duplicate_check_result') or '已参考历史信息避重'}")
            refs = topic.get("referenced_items", [])
            ref_text = join_tags(refs) if isinstance(refs, list) else str(refs or "")
            risk_tags = topic.get("risk_tags", [])
            risk_text = join_tags(risk_tags) if isinstance(risk_tags, list) else str(risk_tags or "无")
            st.markdown(f"**参考内容：** {ref_text or '知识库综合参考'}")
            st.markdown(f"**风险标签：** {risk_text or '无'}")
            st.markdown(f"**推荐理由：** {topic.get('reason') or '未填写'}")

            action_cols = st.columns(2)
            with action_cols[0]:
                if st.button("生成这篇", type="primary", key=f"generate_topic_article_{session_key}_{index}", use_container_width=True):
                    progress = st.empty()
                    try:
                        progress.info("正在基于这个选题生成文章，请稍等...")
                        task_id = create_article_task_from_knowledge_topic(
                            knowledge_base_id=knowledge_base_id,
                            title=str(topic.get("title", "")),
                            target_reader=str(topic.get("target_reader", "")),
                            core_viewpoint=str(topic.get("core_viewpoint", "")),
                            topic_angle=str(topic.get("topic_angle", "")),
                            risk_tags=topic.get("risk_tags", []),
                            referenced_items=topic.get("referenced_items", []),
                            retrieved_knowledge=str(topic.get("retrieved_knowledge", "")),
                            duplicate_check_result=str(topic.get("duplicate_check_result", "")),
                            writing_style=writing_style,
                            article_length=article_length,
                            topic_history_id=int(topic.get("topic_history_id") or 0) or None,
                        )
                        progress.empty()
                        st.session_state["selected_task_id"] = task_id
                        set_flash("文章已生成，进入待审核。")
                        go_to_page("任务详情 / 编辑页", task_id=task_id)
                        st.rerun()
                    except Exception as exc:
                        progress.empty()
                        st.error(str(exc))
            with action_cols[1]:
                if st.button("换个角度", key=f"refresh_topic_angle_{session_key}_{index}", use_container_width=True):
                    progress = st.empty()
                    try:
                        progress.info("正在换一个角度，请稍等...")
                        new_topics = generate_knowledge_topics(
                            knowledge_base_id=knowledge_base_id,
                            generation_mode="针对单个选题换一个不同角度",
                            user_topic=str(topic.get("title", "")),
                            target_reader=str(topic.get("target_reader", "")),
                            writing_style=writing_style,
                            article_length=article_length,
                            article_count=1,
                        )
                        topics[index - 1] = new_topics[0]
                        st.session_state[session_key] = topics
                        progress.empty()
                        set_flash("已换一个角度。")
                        st.rerun()
                    except Exception as exc:
                        progress.empty()
                        st.error(str(exc))


def render_knowledge_generate_page() -> None:
    st.subheader("基于知识库生成")
    st.caption("选择知识库后，可以让 AI 推荐选题，也可以自己输入主题，或选择具体内容生成文章。")

    bases = list_knowledge_bases()
    if not bases:
        st.warning("还没有知识库，请先创建知识库。")
        return
    query_base_text = get_query_param("knowledge_id")
    query_base_id = int(query_base_text) if query_base_text.isdigit() else 0
    default_base_id = query_base_id or st.session_state.get("current_knowledge_base_id") or bases[0].id
    if default_base_id not in [base.id for base in bases]:
        default_base_id = bases[0].id
    base_options = {base.id: base for base in bases}

    st.markdown("#### 第 1 步：选择知识库")
    selected_base_id = st.selectbox(
        "选择知识库",
        list(base_options.keys()),
        index=list(base_options.keys()).index(default_base_id),
        format_func=lambda base_id: base_options[base_id].name,
        key="knowledge_generate_base_id",
    )
    selected_base = base_options[selected_base_id]
    st.session_state["current_knowledge_base_id"] = selected_base_id
    items = list_knowledge_contents(selected_base_id)
    tags: List[str] = []
    for item in items:
        for tag in parse_tags(item.tags):
            if tag not in tags:
                tags.append(tag)
    with st.container(border=True):
        st.markdown(f"### {selected_base.name}")
        st.caption(selected_base.description or "暂无简介。")
        render_compact_info_grid(
            [
                ("已收录内容", len(items)),
                ("适合主题", "、".join(tags[:4]) or "暂未设置"),
                ("最近更新", max((item.updated_at for item in items), default=selected_base.updated_at) or "暂无"),
            ],
            columns=3,
        )

    if not items:
        st.info("这个知识库还没有内容。请先新增今日素材或上传资料。")
        if st.button("去新增今日素材", type="primary"):
            go_to_page("新增今日素材", knowledge_id=str(selected_base_id))
            st.rerun()
        return

    st.markdown("#### 第 2 步：选择生成方式")
    generation_mode = st.radio(
        "生成方式",
        ["AI 自动推荐选题", "我自己输入主题", "选择知识库中的具体内容生成"],
        horizontal=True,
        key="knowledge_generation_mode",
    )

    settings = get_app_settings_map()
    default_style = settings.get("default_article_style", "温和科普")
    default_length = settings.get("default_article_length", "中等1200字")
    style_options = WRITING_STYLES
    length_options = ARTICLE_LENGTHS
    writing_style = st.selectbox(
        "文章风格",
        style_options,
        index=option_index(style_options, default_style),
        key="knowledge_generate_style",
    )
    article_length = st.selectbox(
        "文章长度",
        length_options,
        index=option_index(length_options, default_length, 1),
        key="knowledge_generate_length",
    )

    session_key = f"knowledge_topics_{selected_base_id}_{generation_mode}"

    if generation_mode == "AI 自动推荐选题":
        st.info("系统会参考知识库、历史稿件和历史选题，推荐 5 个尽量不重复的选题。")
        if st.button("AI 推荐选题", type="primary"):
            progress = st.empty()
            try:
                progress.info("正在推荐选题，请稍等...")
                topics = generate_knowledge_topics(
                    knowledge_base_id=selected_base_id,
                    generation_mode="AI 自动推荐选题",
                    writing_style=writing_style,
                    article_length=article_length,
                    article_count=5,
                )
                st.session_state[session_key] = topics
                progress.empty()
                set_flash("已生成推荐选题。")
                st.rerun()
            except Exception as exc:
                progress.empty()
                st.error(str(exc))
        topics = st.session_state.get(session_key, [])
        render_knowledge_topic_cards(
            topics,
            knowledge_base_id=selected_base_id,
            writing_style=writing_style,
            article_length=article_length,
            session_key=session_key,
        )

    elif generation_mode == "我自己输入主题":
        with st.form("knowledge_manual_topic_form"):
            user_topic = st.text_input("文章主题", placeholder="例：为什么越焦虑越容易拖延")
            target_reader = st.text_input("目标读者", value=settings.get("default_target_reader", "公众号读者"))
            with st.expander("高级设置（选填）", expanded=False):
                manual_core_viewpoint = st.text_area(
                    "核心观点",
                    placeholder="例：拖延不一定是懒，也可能是压力过载后的回避和自我保护。",
                    height=90,
                )
                manual_topic_angle = st.text_area(
                    "文章角度",
                    placeholder="例：从日常压力和情绪调节角度解释，给出低风险、通用、可执行的小建议。",
                    height=90,
                )
                manual_risk_tags = st.text_input("风险标签", placeholder="例：焦虑、睡眠、情绪调节")
                reference_count = st.slider(
                    "参考知识条数",
                    min_value=1,
                    max_value=max(1, min(12, len(items))),
                    value=max(1, min(5, len(items))),
                    help="条数越多，参考内容越充分，但生成速度可能更慢。",
                )
                manual_image_style = st.selectbox("图片风格", IMAGE_STYLES, key="manual_knowledge_image_style")
                manual_layout_style = st.selectbox("排版风格", LAYOUT_STYLES, key="manual_knowledge_layout_style")
            submitted = st.form_submit_button("结合知识库生成文章", type="primary")
        if submitted:
            progress = st.empty()
            try:
                if not user_topic.strip():
                    raise UserFacingError("请先填写文章主题。")
                progress.info("正在结合知识库生成文章，请稍等...")
                retrieved = build_knowledge_context_for_base(selected_base_id)
                task_id = create_article_task_from_knowledge_topic(
                    knowledge_base_id=selected_base_id,
                    title=user_topic,
                    target_reader=target_reader,
                    core_viewpoint=manual_core_viewpoint or "结合知识库内容进行专业、通俗、低风险的公众号科普。",
                    topic_angle=manual_topic_angle or "用户自定义主题，结合知识库展开。",
                    risk_tags=parse_tags(manual_risk_tags),
                    referenced_items=[item.title for item in items[:reference_count]],
                    retrieved_knowledge=retrieved,
                    duplicate_check_result="用户自定义主题，已附带历史轻量信息用于后续人工判断。",
                    writing_style=writing_style,
                    article_length=article_length,
                    image_style=manual_image_style,
                    layout_style=manual_layout_style,
                )
                progress.empty()
                st.session_state["selected_task_id"] = task_id
                set_flash("文章已生成，进入待审核。")
                go_to_page("任务详情 / 编辑页", task_id=task_id)
                st.rerun()
            except Exception as exc:
                progress.empty()
                st.error(str(exc))

    else:
        st.markdown("选择要参考的内容")
        item_ids = [item.id for item in items]
        selected_item_ids = st.multiselect(
            "选择 1-5 条已收录内容",
            item_ids,
            format_func=lambda item_id: next((item.title for item in items if item.id == item_id), str(item_id)),
            max_selections=5,
            key=f"knowledge_selected_items_{selected_base_id}",
        )
        custom_topic = st.text_input("生成主题（可选）", placeholder="不填则根据选中内容自动生成主题")
        selected_items = [item for item in items if item.id in selected_item_ids]
        if selected_items:
            st.dataframe(
                [
                    {
                        "内容标题": item.title,
                        "简短摘要": item.summary or item.content[:80],
                        "标签": item.tags,
                        "最近使用状态": item.usage_status,
                    }
                    for item in selected_items
                ],
                width="stretch",
                hide_index=True,
            )
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("基于选中内容推荐选题", type="primary", use_container_width=True):
                progress = st.empty()
                try:
                    if not selected_item_ids:
                        raise UserFacingError("请先选择 1-5 条内容。")
                    progress.info("正在基于选中内容推荐选题，请稍等...")
                    topics = generate_knowledge_topics(
                        knowledge_base_id=selected_base_id,
                        generation_mode="选择知识库中的具体内容生成",
                        user_topic=custom_topic,
                        selected_item_ids=selected_item_ids,
                        writing_style=writing_style,
                        article_length=article_length,
                        article_count=5,
                    )
                    st.session_state[session_key] = topics
                    progress.empty()
                    set_flash("已基于选中内容推荐选题。")
                    st.rerun()
                except Exception as exc:
                    progress.empty()
                    st.error(str(exc))
        with action_cols[1]:
            if st.button("直接生成文章", use_container_width=True):
                progress = st.empty()
                try:
                    if not selected_item_ids:
                        raise UserFacingError("请先选择 1-5 条内容。")
                    title = custom_topic.strip() or "、".join(item.title for item in selected_items[:2])
                    progress.info("正在基于选中内容生成文章，请稍等...")
                    task_id = create_article_task_from_knowledge_topic(
                        knowledge_base_id=selected_base_id,
                        title=title,
                        target_reader=settings.get("default_target_reader", "公众号读者"),
                        core_viewpoint="围绕选中内容提炼核心观点，生成一篇通俗、专业、低风险的公众号文章。",
                        topic_angle="基于用户选中的具体内容生成。",
                        referenced_items=[item.title for item in selected_items],
                        retrieved_knowledge=build_knowledge_context_for_base(selected_base_id, selected_item_ids),
                        duplicate_check_result="基于选中内容生成，建议人工确认是否与历史稿件重复。",
                        writing_style=writing_style,
                        article_length=article_length,
                    )
                    progress.empty()
                    st.session_state["selected_task_id"] = task_id
                    set_flash("文章已生成，进入待审核。")
                    go_to_page("任务详情 / 编辑页", task_id=task_id)
                    st.rerun()
                except Exception as exc:
                    progress.empty()
                    st.error(str(exc))
        topics = st.session_state.get(session_key, [])
        render_knowledge_topic_cards(
            topics,
            knowledge_base_id=selected_base_id,
            writing_style=writing_style,
            article_length=article_length,
            session_key=session_key,
        )


def render_knowledge_management_page() -> None:
    selected_base_text = get_query_param("knowledge_id")
    selected_base_id = int(selected_base_text) if selected_base_text.isdigit() else 0
    if selected_base_id:
        render_knowledge_detail_page(selected_base_id)
        return

    st.subheader("知识库")
    st.caption("把观点、参考资料、合规规则和历史内容收好，后续用于推荐选题和生成文章。")

    top_cols = st.columns([1, 1, 3])
    with top_cols[0]:
        if st.button("新增今日素材", type="primary", use_container_width=True):
            go_to_page("新增今日素材")
            st.rerun()
    with top_cols[1]:
        with st.popover("新建知识库", use_container_width=True):
            with st.form("create_knowledge_base_form"):
                name = st.text_input("知识库名称", placeholder="例：睡眠与焦虑科普")
                description = st.text_area("知识库简介", placeholder="这个知识库适合哪些主题？", height=90)
                submitted = st.form_submit_button("创建知识库", type="primary")
            if submitted:
                try:
                    if not name.strip():
                        raise UserFacingError("请填写知识库名称。")
                    base = orm_create_knowledge_base(name, description)
                    set_flash("知识库已创建。")
                    go_to_page("知识库详情 / 管理", knowledge_id=str(base.id))
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    with top_cols[2]:
        st.info("知识库首页只展示知识库卡片；具体内容在知识库详情里的“已收录内容”查看。")

    bases = list_knowledge_bases()
    if not bases:
        st.warning("还没有知识库，系统会自动创建一个默认知识库。请刷新页面重试。")
        return

    st.markdown("#### 我的知识库")
    for row_start in range(0, len(bases), 3):
        cols = st.columns(3)
        for col, base in zip(cols, bases[row_start : row_start + 3]):
            items = list_knowledge_contents(base.id)
            latest = max((item.updated_at for item in items), default=base.updated_at)
            tags: List[str] = []
            for item in items:
                for tag in parse_tags(item.tags):
                    if tag not in tags:
                        tags.append(tag)
            suitable_topics = "、".join(tags[:5]) or "暂未设置"
            with col:
                with st.container(border=True):
                    st.markdown(f"### {base.name}")
                    st.caption(base.description or "用于收录可复用的内容资料。")
                    render_compact_info_grid(
                        [
                            ("已收录内容", len(items)),
                            ("适合主题", suitable_topics),
                        ],
                        columns=2,
                    )
                    st.caption(f"最近更新：{latest or '暂无'}")
                    button_cols = st.columns(2)
                    with button_cols[0]:
                        if st.button("基于它生成文章", key=f"generate_from_base_{base.id}", use_container_width=True):
                            st.session_state["current_knowledge_base_id"] = base.id
                            set_flash("基于知识库生成流程将在第 3 步接入。现在可以先管理知识库内容。", "info")
                            go_to_page("基于知识库生成", knowledge_id=str(base.id))
                            st.rerun()
                    with button_cols[1]:
                        if st.button("管理", key=f"manage_base_{base.id}", type="primary", use_container_width=True):
                            st.session_state["current_knowledge_base_id"] = base.id
                            go_to_page("知识库详情 / 管理", knowledge_id=str(base.id))
                            st.rerun()


def render_knowledge_detail_page(knowledge_base_id: int) -> None:
    base = orm_get_knowledge_base(knowledge_base_id)
    if base is None:
        st.error("知识库不存在。")
        render_page_link_button("返回知识库", "知识库", primary=True)
        return

    items = list_knowledge_contents(base.id)
    latest = max((item.updated_at for item in items), default=base.updated_at)
    st.subheader("知识库详情 / 管理")
    st.caption("管理这个知识库里的已收录内容。不要上传原始咨询记录、真实身份信息或未经脱敏的个案资料。")

    st.markdown(f"### {base.name}")
    st.write(base.description or "暂无简介。")
    render_compact_info_grid(
        [
            ("已收录内容", len(items)),
            ("最近更新", latest or "暂无"),
        ],
        columns=2,
    )

    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button("新增今日素材", type="primary", use_container_width=True):
            st.session_state["current_knowledge_base_id"] = base.id
            go_to_page("新增今日素材", knowledge_id=str(base.id))
            st.rerun()
    with action_cols[1]:
        with st.popover("上传资料", use_container_width=True):
            upload_tags = st.text_input("资料标签", placeholder="例：焦虑、睡眠、亲子", key=f"detail_upload_tags_{base.id}")
            uploaded_files = st.file_uploader(
                "上传 .txt 或 .md 文件",
                type=["txt", "md"],
                accept_multiple_files=True,
                key=f"detail_file_uploader_{base.id}",
            )
            if st.button("保存上传资料", type="primary", key=f"save_uploaded_files_{base.id}"):
                if not uploaded_files:
                    st.warning("请先选择要上传的 .txt 或 .md 文件。")
                else:
                    try:
                        saved_count = 0
                        for file in uploaded_files:
                            try:
                                content = file.getvalue().decode("utf-8-sig")
                            except UnicodeDecodeError:
                                content = file.getvalue().decode("utf-8", errors="ignore")
                            create_knowledge_content(
                                knowledge_base_id=base.id,
                                title=Path(file.name).stem,
                                content=sanitize_model_text(content),
                                summary=sanitize_model_text(content)[:160],
                                tags=upload_tags,
                                risk_level="",
                            )
                            saved_count += 1
                        set_flash(f"已上传 {saved_count} 条资料。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
    with action_cols[2]:
        if st.button("基于该知识库生成文章", use_container_width=True):
            st.session_state["current_knowledge_base_id"] = base.id
            set_flash("基于知识库生成流程将在第 3 步接入。", "info")
            go_to_page("基于知识库生成", knowledge_id=str(base.id))
            st.rerun()

    with st.expander("编辑知识库信息", expanded=False):
        with st.form(f"edit_knowledge_base_{base.id}"):
            new_name = st.text_input("知识库名称", value=base.name)
            new_description = st.text_area("知识库简介", value=base.description, height=90)
            saved = st.form_submit_button("保存知识库信息", type="primary")
        if saved:
            try:
                if not new_name.strip():
                    raise UserFacingError("知识库名称不能为空。")
                orm_update_knowledge_base(base.id, name=new_name, description=new_description)
                set_flash("知识库信息已保存。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if base.id != 1:
        with st.expander("删除这个知识库", expanded=False):
            st.error("删除后，这个知识库和里面的已收录内容都不可恢复。")
            confirm = st.checkbox("我理解删除后不可恢复", key=f"delete_base_confirm_{base.id}")
            if st.button("删除知识库", type="primary", key=f"delete_base_{base.id}"):
                if not confirm:
                    st.warning("请先勾选“我理解删除后不可恢复”。")
                else:
                    orm_delete_knowledge_base(base.id)
                    set_flash("知识库已删除。")
                    go_to_page("知识库")
                    st.rerun()

    st.markdown("#### 已收录内容")
    if not items:
        st.info("这个知识库还没有内容。可以点击“新增今日素材”或“上传资料”。")
        return

    rows = [
        {
            "标题": item.title,
            "摘要": item.summary or item.content[:80],
            "标签": item.tags,
            "使用状态": item.usage_status,
            "风险": item.risk_level or "未评估",
            "更新时间": item.updated_at,
        }
        for item in items
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    item_ids = [item.id for item in items]
    selected_item_id = st.selectbox(
        "选择要查看的内容",
        item_ids,
        format_func=lambda item_id: next((item.title for item in items if item.id == item_id), str(item_id)),
        key=f"knowledge_detail_item_{base.id}",
    )
    selected_item = get_knowledge_content(int(selected_item_id))
    if selected_item is None:
        st.error("内容不存在。")
        return

    with st.container(border=True):
        st.markdown(f"### {selected_item.title}")
        st.caption(f"标签：{selected_item.tags or '无'}｜使用状态：{selected_item.usage_status}｜风险：{selected_item.risk_level or '未评估'}")
        st.write(selected_item.summary or "暂无摘要。")
        with st.expander("查看完整内容", expanded=False):
            st.text_area("内容", value=selected_item.content, height=300, disabled=True)
        item_action_cols = st.columns(3)
        with item_action_cols[0]:
            if st.button("用它生成文章", key=f"use_item_generate_{selected_item.id}", use_container_width=True):
                st.session_state["current_knowledge_base_id"] = base.id
                st.session_state["selected_knowledge_item_ids"] = [selected_item.id]
                set_flash("选择具体内容生成文章将在第 3 步接入。", "info")
                go_to_page("基于知识库生成", knowledge_id=str(base.id))
                st.rerun()
        with item_action_cols[1]:
            with st.popover("编辑内容", use_container_width=True):
                with st.form(f"edit_knowledge_item_{selected_item.id}"):
                    edit_title = st.text_input("内容标题", value=selected_item.title)
                    edit_summary = st.text_area("摘要", value=selected_item.summary, height=90)
                    edit_tags = st.text_input("标签", value=selected_item.tags)
                    edit_content = st.text_area("内容", value=selected_item.content, height=260)
                    edit_risk = st.selectbox("风险等级", ["", "低", "中", "高"], index=option_index(["", "低", "中", "高"], selected_item.risk_level))
                    edit_saved = st.form_submit_button("保存内容", type="primary")
                if edit_saved:
                    try:
                        update_knowledge_content(
                            selected_item.id,
                            title=edit_title,
                            content=edit_content,
                            summary=edit_summary,
                            tags=edit_tags,
                            risk_level=edit_risk,
                            usage_status=selected_item.usage_status,
                            enabled=bool(selected_item.enabled),
                        )
                        set_flash("内容已保存。")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
        with item_action_cols[2]:
            with st.popover("删除内容", use_container_width=True):
                st.error("删除后，这条内容不可恢复。")
                confirm_item = st.checkbox("我理解删除后不可恢复", key=f"delete_content_confirm_{selected_item.id}")
                if st.button("删除这条内容", type="primary", key=f"delete_content_{selected_item.id}"):
                    if not confirm_item:
                        st.warning("请先勾选“我理解删除后不可恢复”。")
                    else:
                        delete_knowledge_content(selected_item.id)
                        set_flash("内容已删除。")
                        st.rerun()


def render_knowledge_edit_page() -> None:
    st.subheader("新增今日素材")
    st.caption("把今天想到的案例、观点、读者问题、咨询中常见现象或零散笔记粘贴进来，系统会自动整理进知识库。")
    if st.session_state.pop("today_material_should_clear", False):
        st.session_state["today_material_text"] = ""

    bases = list_knowledge_bases()
    if not bases:
        st.warning("还没有知识库，请先在知识库页面创建一个知识库。")
        return
    query_base_text = get_query_param("knowledge_id")
    query_base_id = int(query_base_text) if query_base_text.isdigit() else 0
    default_base_id = (
        query_base_id
        or st.session_state.get("current_knowledge_base_id")
        or bases[0].id
    )
    if default_base_id not in [base.id for base in bases]:
        default_base_id = bases[0].id

    base_options = {base.id: base for base in bases}
    selected_base_id = st.selectbox(
        "选择放入哪个知识库",
        list(base_options.keys()),
        index=list(base_options.keys()).index(default_base_id),
        format_func=lambda base_id: base_options[base_id].name,
        key="today_material_base_id",
    )
    selected_base = base_options[selected_base_id]
    raw_material = st.text_area(
        "今日内容",
        value=st.session_state.get("today_material_text", ""),
        height=280,
        placeholder="直接粘贴今天的新想法、读者问题、观点笔记或已脱敏的常见现象。不要粘贴原始咨询记录或真实身份信息。",
        key="today_material_text",
    )

    action_cols = st.columns([1, 1, 3])
    with action_cols[0]:
        organize_clicked = st.button("AI 整理并加入知识库", type="primary", use_container_width=True)
    with action_cols[1]:
        if st.button("清空", use_container_width=True):
            st.session_state.pop("today_material_review", None)
            st.session_state["today_material_should_clear"] = True
            st.rerun()
    with action_cols[2]:
        st.info("AI 会先整理成确认卡，确认后才会真正加入知识库。")

    if organize_clicked:
        progress = st.empty()
        try:
            progress.info("正在整理今日素材，请稍等...")
            review = organize_today_material(raw_material, selected_base.name)
            review["knowledge_base_id"] = selected_base.id
            review["knowledge_base_name"] = selected_base.name
            st.session_state["today_material_review"] = review
            progress.empty()
            set_flash("素材已整理，请确认后加入知识库。")
            st.rerun()
        except Exception as exc:
            progress.empty()
            st.error(str(exc))

    review = st.session_state.get("today_material_review")
    if not review:
        return

    st.markdown("#### AI 整理结果确认")
    with st.container(border=True):
        st.markdown(f"### {review.get('title', '未命名内容')}")
        st.markdown(f"**建议知识库：** {review.get('suggested_knowledge_base') or review.get('knowledge_base_name')}")
        st.markdown(f"**风险等级：** {review.get('risk_level', '低')}")
        st.markdown("**核心观点：**")
        st.write(review.get("core_viewpoint") or "暂无")
        st.markdown("**适合生成的选题：**")
        topic_ideas = review.get("topic_ideas") or []
        if topic_ideas:
            for idea in topic_ideas:
                st.markdown(f"- {idea}")
        else:
            st.caption("暂无")

        with st.form("today_material_confirm_form"):
            confirmed_title = st.text_input("内容标题", value=str(review.get("title", "")))
            confirmed_summary = st.text_area("内容摘要", value=str(review.get("summary", "")), height=90)
            confirmed_core = st.text_area("核心观点", value=str(review.get("core_viewpoint", "")), height=100)
            confirmed_tags = st.text_input("标签", value=join_tags(review.get("tags", [])))
            confirmed_risk = st.selectbox(
                "风险等级",
                ["低", "中", "高"],
                index=option_index(["低", "中", "高"], str(review.get("risk_level", "低"))),
            )
            confirmed_content = st.text_area("原始内容", value=str(review.get("raw_material", "")), height=220)
            confirm_cols = st.columns(2)
            confirm = confirm_cols[0].form_submit_button("确认加入知识库", type="primary")
            reorganize = confirm_cols[1].form_submit_button("重新整理")

        if confirm:
            try:
                if not confirmed_title.strip():
                    raise UserFacingError("请填写内容标题。")
                if not confirmed_content.strip():
                    raise UserFacingError("内容不能为空。")
                content = "\n\n".join(
                    [
                        confirmed_content.strip(),
                        f"核心观点：{confirmed_core.strip()}" if confirmed_core.strip() else "",
                        "适合生成的选题：\n" + "\n".join(f"- {idea}" for idea in topic_ideas) if topic_ideas else "",
                    ]
                ).strip()
                create_knowledge_content(
                    knowledge_base_id=int(review.get("knowledge_base_id") or selected_base.id),
                    title=confirmed_title,
                    content=content,
                    summary=confirmed_summary,
                    tags=confirmed_tags,
                    risk_level=confirmed_risk,
                    usage_status="unused",
                )
                st.session_state.pop("today_material_review", None)
                st.session_state["today_material_should_clear"] = True
                set_flash("已加入知识库。")
                go_to_page("知识库详情 / 管理", knowledge_id=str(review.get("knowledge_base_id") or selected_base.id))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        if reorganize:
            try:
                refreshed = organize_today_material(confirmed_content, selected_base.name)
                refreshed["knowledge_base_id"] = selected_base.id
                refreshed["knowledge_base_name"] = selected_base.name
                st.session_state["today_material_review"] = refreshed
                set_flash("已重新整理，请再次确认。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def monday_of_current_week() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def render_weekly_plan_page() -> None:
    st.subheader("计划生成")
    st.caption("基于知识库维护每周内容计划。第一版不做云端定时任务，需要手动点击“立即生成”。")

    bases = list_knowledge_bases()
    if not bases:
        st.warning("还没有知识库，请先到“知识库”创建或补充内容。")
        render_page_link_button("去知识库", "知识库", primary=True)
        return

    ensure_weekly_plans_have_knowledge_base()
    base_options = {base.id: base for base in bases}
    available_tags = all_knowledge_tags()
    plans = list_weekly_plans()

    st.markdown("#### 当前计划")
    if not plans:
        st.info("还没有计划。可以先在下方创建一个“每周 3 篇”的内容计划。")
    for plan in plans[:8]:
        plan_id = int(plan["id"])
        topics = list_weekly_topics(plan_id)
        generated_count = len([topic for topic in topics if topic.get("generated_article_task_id")])
        pending_count = len([topic for topic in topics if not topic.get("generated_article_task_id")])
        enabled = int(plan.get("enabled") or 0) == 1
        is_running = plan.get("status") in RUNNING_WEEKLY_STATUSES
        with st.container(border=True):
            header_cols = st.columns([2, 1, 1, 1])
            with header_cols[0]:
                st.markdown(f"### {weekly_plan_display_name(plan)}")
                st.caption(plan.get("weekly_focus") or "暂无主题方向")
            header_cols[1].metric("计划篇数", str(plan.get("article_count") or 3))
            header_cols[2].metric("已生成文章", str(generated_count))
            header_cols[3].metric("待生成文章", str(pending_count))
            meta_cols = st.columns(4)
            effective_base_id = plan_knowledge_base_id(plan)
            meta_cols[0].write(f"**知识库：** {knowledge_base_name(effective_base_id)}")
            meta_cols[1].write(f"**生成时间：** {plan.get('generate_time') or '09:00'}")
            meta_cols[2].write(f"**状态：** {'启用' if enabled else '已暂停'} / {plan.get('status') or '待生成'}")
            meta_cols[3].write(f"**更新时间：** {plan.get('updated_at') or '暂无'}")

            action_cols = st.columns(4)
            with action_cols[0]:
                if st.button("查看本周选题", key=f"view_weekly_plan_{plan_id}", use_container_width=True):
                    st.session_state["selected_weekly_plan_id"] = plan_id
                    go_to_page("每周计划详情页", plan_id=str(plan_id))
                    st.rerun()
            with action_cols[1]:
                if is_running:
                    if st.button("停止生成并恢复", key=f"stop_weekly_plan_{plan_id}", type="primary", use_container_width=True):
                        reset_weekly_plan_running_state(plan_id)
                        clear_active_operation()
                        set_flash("已停止当前生成状态，可以重新生成。")
                        st.rerun()
                else:
                    if st.button(
                        f"立即生成本周 {int(plan.get('article_count') or 3)} 篇稿件",
                        key=f"run_weekly_plan_{plan_id}",
                        type="primary",
                        use_container_width=True,
                        disabled=not enabled,
                    ):
                        progress = st.empty()
                        start_active_operation("weekly_plan", plan_id, f"每周计划「{weekly_plan_display_name(plan)}」生成")
                        try:
                            progress.info(
                                "正在基于知识库生成本周稿件，请稍等... "
                                "如果想中止，请点击右上角 Stop；如果停止后提示仍在，请刷新页面，会出现“停止并恢复页面”。"
                            )
                            run_weekly_plan_to_articles(plan_id)
                            progress.empty()
                            clear_active_operation()
                            st.session_state["selected_weekly_plan_id"] = plan_id
                            set_flash("本周稿件已生成，已进入待审核。")
                            go_to_page("每周计划详情页", plan_id=str(plan_id))
                            st.rerun()
                        except Exception as exc:
                            progress.empty()
                            clear_active_operation()
                            st.error(str(exc))
            with action_cols[2]:
                if st.button(
                    "暂停计划" if enabled else "启用计划",
                    key=f"toggle_weekly_plan_{plan_id}",
                    use_container_width=True,
                ):
                    toggle_weekly_plan_enabled(plan_id, not enabled)
                    set_flash("计划状态已更新。")
                    st.rerun()
            with action_cols[3]:
                with st.popover("修改计划", use_container_width=True):
                    try:
                        current_date = date.fromisoformat(plan.get("week_start_date") or monday_of_current_week().isoformat())
                    except ValueError:
                        current_date = monday_of_current_week()
                    with st.form(f"edit_weekly_plan_{plan_id}"):
                        edit_name = st.text_input("计划名称", value=weekly_plan_display_name(plan))
                        current_base_id = plan_knowledge_base_id(plan) or list(base_options.keys())[0]
                        edit_base_id = st.selectbox(
                            "使用知识库",
                            list(base_options.keys()),
                            index=option_index(list(base_options.keys()), current_base_id),
                            format_func=lambda base_id: base_options[base_id].name,
                        )
                        edit_week_start = st.date_input("本周开始日期", value=current_date)
                        edit_count = st.number_input("每周生成篇数", min_value=1, max_value=6, value=int(plan.get("article_count") or 3), step=1)
                        edit_focus = st.text_area("本周主题方向", value=plan.get("weekly_focus") or "", height=90)
                        edit_tags = st.text_input("重点标签", value=plan.get("selected_tags") or "")
                        edit_style = st.selectbox("文章风格", WRITING_STYLES, index=option_index(WRITING_STYLES, plan.get("writing_style", "")))
                        edit_length = st.selectbox("文章长度", ARTICLE_LENGTHS, index=option_index(ARTICLE_LENGTHS, plan.get("article_length", ""), 1))
                        edit_time = st.text_input("计划生成时间", value=plan.get("generate_time") or "09:00")
                        saved = st.form_submit_button("保存计划", type="primary")
                    if saved:
                        try:
                            update_weekly_plan(
                                plan_id,
                                {
                                    "plan_name": edit_name,
                                    "knowledge_base_id": int(edit_base_id),
                                    "week_start_date": edit_week_start.isoformat(),
                                    "article_count": int(edit_count),
                                    "weekly_focus": edit_focus,
                                    "selected_tags": edit_tags,
                                    "generation_mode": "AI 自动推荐选题",
                                    "writing_style": edit_style,
                                    "article_length": edit_length,
                                    "generate_time": edit_time,
                                    "after_generate_status": "已生成，待审核",
                                },
                            )
                            set_flash("计划已保存。")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

    st.markdown("#### 新建计划")
    with st.expander("创建一个每周内容计划", expanded=not plans):
        with st.form("weekly_plan_form_v2"):
            default_base_id = bases[0].id
            plan_name = st.text_input("计划名称", value="每周公众号内容计划")
            selected_base_id = st.selectbox(
                "使用哪个知识库",
                list(base_options.keys()),
                index=list(base_options.keys()).index(default_base_id),
                format_func=lambda base_id: base_options[base_id].name,
            )
            week_start = st.date_input("本周开始日期", value=monday_of_current_week())
            weekly_focus = st.text_area(
                "本周主题方向",
                height=100,
                placeholder="例：围绕睡眠、焦虑和日常压力管理，做温和、低风险、可执行的科普。",
            )
            article_count = st.number_input("每周生成篇数", min_value=1, max_value=6, value=3, step=1)
            selected_tags = st.multiselect("重点标签", available_tags, default=available_tags[:3])
            extra_tags = st.text_input("补充标签", placeholder="例：职场压力、亲密关系")
            generation_mode = st.selectbox("生成方式", ["AI 自动推荐选题"], index=0)
            writing_style = st.selectbox("文章风格", WRITING_STYLES)
            article_length = st.selectbox("文章长度", ARTICLE_LENGTHS, index=1)
            generate_time = st.text_input("计划生成时间", value="09:00", help="第一版只保存这个时间，暂不做云端定时自动运行。")
            after_generate_status = st.selectbox("生成后状态", ["已生成，待审核"], index=0)
            save_only = st.form_submit_button("保存计划")
            save_and_run = st.form_submit_button("保存并立即生成本周选题", type="primary")

        if save_only or save_and_run:
            try:
                all_tags = selected_tags + [tag for tag in parse_tags(extra_tags) if tag not in selected_tags]
                plan_id = create_weekly_plan(
                    {
                        "plan_name": plan_name,
                        "week_start_date": week_start.isoformat(),
                        "article_count": int(article_count),
                        "weekly_focus": weekly_focus,
                        "selected_tags": join_tags(all_tags),
                        "knowledge_base_id": int(selected_base_id),
                        "generation_mode": generation_mode,
                        "writing_style": writing_style,
                        "article_length": article_length,
                        "generate_time": generate_time,
                        "after_generate_status": after_generate_status,
                        "enabled": True,
                    }
                )
                st.session_state["selected_weekly_plan_id"] = plan_id
                if save_and_run:
                    progress = st.empty()
                    progress.info("正在基于知识库生成本周选题，请稍等...")
                    generate_topics_for_weekly_plan(plan_id)
                    progress.empty()
                    set_flash("计划已保存，并生成了本周选题。")
                    go_to_page("每周计划详情页", plan_id=str(plan_id))
                else:
                    set_flash("计划已保存。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def render_weekly_plan_detail_page() -> None:
    st.subheader("每周计划详情")
    plans = list_weekly_plans()
    if not plans:
        st.warning("还没有每周计划，请先到“计划生成”创建计划。")
        render_page_link_button("去计划生成", "计划生成", primary=True)
        return

    plan_ids = [int(plan["id"]) for plan in plans]
    query_plan_id = get_query_param("plan_id")
    selected_plan_id = int(query_plan_id) if query_plan_id.isdigit() and int(query_plan_id) in plan_ids else st.session_state.get("selected_weekly_plan_id")
    if selected_plan_id not in plan_ids:
        selected_plan_id = plan_ids[0]
    if st.session_state.get("weekly_plan_select") not in plan_ids or (
        query_plan_id.isdigit() and int(query_plan_id) != st.session_state.get("weekly_plan_select")
    ):
        st.session_state["weekly_plan_select"] = selected_plan_id
    selected_plan_id = st.selectbox(
        "选择每周计划",
        plan_ids,
        index=plan_ids.index(selected_plan_id),
        format_func=lambda plan_id: weekly_plan_display_name(get_weekly_plan(plan_id) or {"id": plan_id}),
        key="weekly_plan_select",
    )
    st.session_state["selected_weekly_plan_id"] = selected_plan_id
    if get_query_param("plan_id") != str(selected_plan_id):
        st.query_params["plan_id"] = str(selected_plan_id)

    plan = get_weekly_plan(int(selected_plan_id))
    if plan is None:
        st.error("每周计划不存在。")
        return
    topics = list_weekly_topics(int(selected_plan_id))
    with st.expander("本计划使用的知识库参考", expanded=False):
        st.text_area("知识库参考", value=build_weekly_plan_knowledge_context(plan), height=360, disabled=True)

    st.markdown(f"### {weekly_plan_display_name(plan)}")
    metric_cols = st.columns(6)
    metric_cols[0].metric("周开始日期", plan["week_start_date"] or "未设置")
    metric_cols[1].metric("计划篇数", str(plan["article_count"]))
    metric_cols[2].metric("使用知识库", knowledge_base_name(plan.get("knowledge_base_id")))
    metric_cols[3].metric("计划时间", plan.get("generate_time") or "09:00")
    metric_cols[4].metric("文章风格", plan["writing_style"])
    metric_cols[5].metric("状态", plan["status"])
    st.info(f"本周主题方向：{plan['weekly_focus']}")
    st.caption(f"重点标签：{plan['selected_tags'] or '未选择'}｜生成后状态：{plan.get('after_generate_status') or '已生成，待审核'}")

    top_actions = st.columns([1, 1, 3])
    with top_actions[0]:
        if plan.get("status") in RUNNING_WEEKLY_STATUSES:
            if st.button("停止生成并恢复", type="primary", use_container_width=True, key=f"detail_stop_plan_{selected_plan_id}"):
                reset_weekly_plan_running_state(int(selected_plan_id))
                clear_active_operation()
                set_flash("已停止当前生成状态，可以重新生成。")
                st.rerun()
        else:
            if st.button("重新生成本周选题", type="primary", use_container_width=True):
                progress = st.empty()
                start_active_operation("weekly_plan", selected_plan_id, f"每周计划「{weekly_plan_display_name(plan)}」重新生成选题")
                try:
                    progress.info(
                        "正在重新生成本周选题，请稍等... "
                        "如果想中止，请点击右上角 Stop；如果停止后提示仍在，请刷新页面，会出现“停止并恢复页面”。"
                    )
                    generate_topics_for_weekly_plan(int(selected_plan_id))
                    progress.empty()
                    clear_active_operation()
                    set_flash("本周选题已重新生成。")
                    st.rerun()
                except Exception as exc:
                    progress.empty()
                    clear_active_operation()
                    st.error(str(exc))
    with top_actions[1]:
        render_page_link_button("返回计划生成", "计划生成")

    if not topics:
        st.warning("这个计划还没有选题，请点击“重新生成本周选题”。")
        return

    pending_count = len([topic for topic in topics if not topic.get("generated_article_task_id")])
    batch_label = f"批量生成 {pending_count} 篇文章任务" if pending_count else "批量生成文章任务"
    if pending_count:
        run_action(batch_label, batch_create_articles_for_plan, int(selected_plan_id), button_type="primary", key=f"batch_plan_{selected_plan_id}")
    else:
        st.success("本计划的选题都已经生成文章任务。")

    st.markdown("#### 本周选题")
    for index, topic in enumerate(topics, start=1):
        with st.container(border=True):
            st.markdown(f"### {index}. {topic['title']}")
            st.markdown(f"**目标读者：** {topic['target_reader'] or '未填写'}")
            st.markdown(f"**核心观点：** {topic['core_viewpoint'] or '未填写'}")
            st.markdown(f"**文章角度：** {topic['article_angle'] or '未填写'}")
            st.markdown(f"**风险标签：** {topic['risk_tags'] or '无'}")
            st.markdown(f"**推荐理由：** {topic['reason'] or '未填写'}")
            st.caption(f"状态：{topic['status']}")
            topic_cols = st.columns(2)
            generated_task_id = topic.get("generated_article_task_id", "")
            with topic_cols[0]:
                if generated_task_id and get_task(generated_task_id):
                    render_page_link_button("打开文章任务", "任务详情 / 编辑页", task_id=generated_task_id, primary=True)
                else:
                    run_action(
                        "生成文章任务",
                        create_article_from_weekly_topic,
                        int(topic["id"]),
                        button_type="primary",
                        key=f"generate_topic_{topic['id']}",
                    )
            with topic_cols[1]:
                if generated_task_id:
                    st.caption(f"文章任务编号：{generated_task_id}")


def main() -> None:
    st.set_page_config(page_title=PRODUCT_NAME, layout="wide")
    init_db()
    seed_from_csv_if_empty()
    init_orm_database()

    query_page = get_query_param("page")
    current_page = KEY_TO_PAGE.get(query_page) or st.session_state.get("page", "内容工作台")
    if current_page not in PAGES:
        current_page = "内容工作台"
    st.session_state["page"] = current_page

    query_task_id = get_query_param("task_id")
    if query_task_id:
        st.session_state["selected_task_id"] = query_task_id
        if current_page == "排版发布页":
            st.session_state["selected_publish_task_id"] = query_task_id

    tasks = list_tasks()
    render_sidebar_nav(current_page)
    render_flash()
    render_active_operation_recovery()

    if current_page == "内容工作台":
        render_workspace_page(tasks)
    elif current_page in {"新建文章页", "直接生成一篇"}:
        render_new_article_page()
    elif current_page in {"任务列表页", "历史稿件"}:
        render_task_list_page(tasks)
    elif current_page in {"任务详情 / 编辑页", "文章详情 / 审核页"}:
        render_task_detail_page(tasks)
    elif current_page == "排版发布页":
        render_publish_page(tasks)
    elif current_page == "基于知识库生成":
        render_knowledge_generate_page()
    elif current_page in {"知识库", "知识库管理页", "知识库详情 / 管理"}:
        render_knowledge_management_page()
    elif current_page in {"新增 / 编辑知识页", "新增今日素材"}:
        render_knowledge_edit_page()
    elif current_page in {"计划生成", "每周内容计划页"}:
        render_weekly_plan_page()
    elif current_page == "每周计划详情页":
        render_weekly_plan_detail_page()
    elif current_page == "设置":
        render_settings_page()


if __name__ == "__main__":
    main()
