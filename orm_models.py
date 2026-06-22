from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional, Sequence

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, create_engine, event, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from generate import BASE_DIR


DATABASE_PATH = BASE_DIR / "data" / "tasks.db"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(String(19), default=now_text)
    updated_at: Mapped[str] = mapped_column(String(19), default=now_text, onupdate=now_text)


class KnowledgeBase(TimestampMixin, Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), default="默认知识库")
    description: Mapped[str] = mapped_column(Text, default="")

    items: Mapped[list["KnowledgeItem"]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeItem(TimestampMixin, Base):
    __tablename__ = "knowledge_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    risk_level: Mapped[str] = mapped_column(String(20), default="")
    usage_status: Mapped[str] = mapped_column(String(40), default="unused")

    # Legacy columns kept so old pages can keep working during the staged V2 migration.
    legacy_type: Mapped[str] = mapped_column("type", String(60), default="topic_material")
    enabled: Mapped[bool] = mapped_column(default=True)

    knowledge_base: Mapped[Optional[KnowledgeBase]] = relationship(back_populates="items")


class ArticleDraft(TimestampMixin, Base):
    __tablename__ = "article_drafts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    legacy_task_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    digest: Mapped[str] = mapped_column(Text, default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(60), default="direct")
    knowledge_base_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    referenced_items: Mapped[str] = mapped_column(Text, default="[]")
    risk_level: Mapped[str] = mapped_column(String(20), default="")
    risk_report: Mapped[str] = mapped_column(Text, default="")
    cover_prompt: Mapped[str] = mapped_column(Text, default="")
    duplicate_check_result: Mapped[str] = mapped_column(Text, default="")
    topic_angle: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(60), default="draft_input")
    published_at: Mapped[str] = mapped_column(String(19), default="")

    knowledge_base: Mapped[Optional[KnowledgeBase]] = relationship()
    revisions: Mapped[list["RevisionHistory"]] = relationship(
        back_populates="article_draft",
        cascade="all, delete-orphan",
    )
    generated_images: Mapped[list["GeneratedImage"]] = relationship(
        back_populates="article_draft",
        cascade="all, delete-orphan",
    )


class GeneratedImage(TimestampMixin, Base):
    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    article_draft_id: Mapped[int] = mapped_column(
        ForeignKey("article_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_role: Mapped[str] = mapped_column(String(40), default="inline")
    slot_key: Mapped[str] = mapped_column(String(80), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(80), default="dummy")
    model: Mapped[str] = mapped_column(String(120), default="")
    local_path: Mapped[str] = mapped_column(Text, default="")
    public_url: Mapped[str] = mapped_column(Text, default="")
    alt_text: Mapped[str] = mapped_column(Text, default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    insert_position: Mapped[str] = mapped_column(String(80), default="not_inserted")
    aspect_ratio: Mapped[str] = mapped_column(String(40), default="16:9")
    style_preset: Mapped[str] = mapped_column(String(120), default="温和治愈插画")
    visual_params: Mapped[str] = mapped_column(Text, default="{}")
    selected: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(60), default="prompt_ready")
    error_message: Mapped[str] = mapped_column(Text, default="")

    article_draft: Mapped[ArticleDraft] = relationship(back_populates="generated_images")


class TopicHistory(TimestampMixin, Base):
    __tablename__ = "topic_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    topic_title: Mapped[str] = mapped_column(Text, default="")
    topic_angle: Mapped[str] = mapped_column(Text, default="")
    knowledge_base_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    referenced_items: Mapped[str] = mapped_column(Text, default="[]")
    generated_article_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("article_drafts.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(40), default="suggested")

    knowledge_base: Mapped[Optional[KnowledgeBase]] = relationship()
    generated_article: Mapped[Optional[ArticleDraft]] = relationship()


class RevisionHistory(Base):
    __tablename__ = "revision_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    article_draft_id: Mapped[int] = mapped_column(
        ForeignKey("article_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    old_title: Mapped[str] = mapped_column(Text, default="")
    old_markdown: Mapped[str] = mapped_column(Text, default="")
    user_feedback: Mapped[str] = mapped_column(Text, default="")
    new_title: Mapped[str] = mapped_column(Text, default="")
    new_markdown: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(19), default=now_text)

    article_draft: Mapped[ArticleDraft] = relationship(back_populates="revisions")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String(19), default=now_text)
    usage_count: Mapped[int] = mapped_column(default=0)


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_app_settings_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String(19), default=now_text, onupdate=now_text)


engine = create_engine(
    f"sqlite:///{DATABASE_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def orm_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _table_columns(session: Session, table_name: str) -> set[str]:
    rows = session.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    return {str(row["name"]) for row in rows}


def _table_exists(session: Session, table_name: str) -> bool:
    row = session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).first()
    return row is not None


def _ensure_column(session: Session, table_name: str, column_name: str, definition: str) -> None:
    if column_name not in _table_columns(session, table_name):
        session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def _ensure_knowledge_item_columns(session: Session) -> None:
    if not _table_exists(session, "knowledge_items"):
        return
    _ensure_column(session, "knowledge_items", "knowledge_base_id", "INTEGER")
    _ensure_column(session, "knowledge_items", "summary", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(session, "knowledge_items", "risk_level", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(session, "knowledge_items", "usage_status", "TEXT NOT NULL DEFAULT 'unused'")


def _ensure_generated_image_columns(session: Session) -> None:
    if not _table_exists(session, "generated_images"):
        return
    columns = {
        "negative_prompt": "TEXT NOT NULL DEFAULT ''",
        "provider": "TEXT NOT NULL DEFAULT 'dummy'",
        "model": "TEXT NOT NULL DEFAULT ''",
        "local_path": "TEXT NOT NULL DEFAULT ''",
        "public_url": "TEXT NOT NULL DEFAULT ''",
        "alt_text": "TEXT NOT NULL DEFAULT ''",
        "caption": "TEXT NOT NULL DEFAULT ''",
        "insert_position": "TEXT NOT NULL DEFAULT 'not_inserted'",
        "aspect_ratio": "TEXT NOT NULL DEFAULT '16:9'",
        "style_preset": "TEXT NOT NULL DEFAULT '温和治愈插画'",
        "visual_params": "TEXT NOT NULL DEFAULT '{}'",
        "selected": "BOOLEAN NOT NULL DEFAULT 1",
        "status": "TEXT NOT NULL DEFAULT 'prompt_ready'",
        "error_message": "TEXT NOT NULL DEFAULT ''",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in columns.items():
        _ensure_column(session, "generated_images", column, definition)


def _ensure_default_settings(session: Session) -> None:
    defaults = {
        "default_article_style": "温和科普",
        "default_article_length": "中等1200字",
        "default_target_reader": "对该主题感兴趣的公众号读者",
        "ip_role": "心理医生",
        "ip_name": "",
        "raphael_url": "https://publish.raphael.app",
        "image_generation_enabled": "false",
        "image_provider": "dummy",
        "image_model": "",
        "image_storage_provider": "manual_url",
        "image_public_base_url": "",
        "default_cover_aspect_ratio": "2.35:1",
        "default_inline_aspect_ratio": "16:9",
        "default_image_style_preset": "温和治愈插画",
        "default_image_count": "1",
        "image_requires_approval": "true",
    }
    for key, value in defaults.items():
        existing = session.scalar(select(AppSettings).where(AppSettings.key == key))
        if existing is None:
            session.add(AppSettings(key=key, value=value))


def ensure_default_knowledge_base(session: Session) -> KnowledgeBase:
    default_base = session.scalar(select(KnowledgeBase).order_by(KnowledgeBase.id.asc()))
    if default_base is not None:
        return default_base
    default_base = KnowledgeBase(
        name="默认知识库",
        description="用于收录日常观点、参考资料、合规规则和历史内容。",
    )
    session.add(default_base)
    session.flush()
    return default_base


def _seed_compliance_item(session: Session, knowledge_base_id: int) -> None:
    existing = session.scalar(select(KnowledgeItem).where(KnowledgeItem.title == "基础合规规则"))
    if existing is not None:
        return
    session.add(
        KnowledgeItem(
            knowledge_base_id=knowledge_base_id,
            title="基础合规规则",
            content=(
                "公众号科普内容应避免诊断结论、药物建议、疗效承诺、真实个案身份信息和焦虑制造。"
                "所有内容生成后都需要人工审核，再复制到排版工具和公众号后台。"
            ),
            summary="通用内容安全边界，生成文章和选题时默认参考。",
            tags="合规、风险边界、人工审核",
            risk_level="低",
            usage_status="unused",
            legacy_type="compliance",
            enabled=True,
        )
    )


def _sync_old_knowledge_items(session: Session, knowledge_base_id: int) -> None:
    items = session.scalars(select(KnowledgeItem)).all()
    for item in items:
        changed = False
        if item.knowledge_base_id is None:
            item.knowledge_base_id = knowledge_base_id
            changed = True
        if not item.summary:
            item.summary = item.content[:160].strip()
            changed = True
        if not item.usage_status:
            item.usage_status = "unused"
            changed = True
        if changed:
            item.updated_at = now_text()


LEGACY_STATUS_TO_DRAFT_STATUS = {
    "待输入": "draft_input",
    "已生成": "ai_generated",
    "已生成，待审核": "doctor_review_pending",
    "待修改": "revision_requested",
    "待审核": "doctor_review_pending",
    "审核通过": "approved",
    "排版中": "layout_ready",
    "已发布": "published",
}


def _sync_legacy_tasks_to_article_drafts(session: Session) -> None:
    if not _table_exists(session, "tasks"):
        return
    rows = session.execute(text("SELECT * FROM tasks")).mappings().all()
    for row in rows:
        task_id = str(row.get("task_id") or "")
        if not task_id:
            continue
        existing = session.scalar(select(ArticleDraft).where(ArticleDraft.legacy_task_id == task_id))
        if existing is not None:
            continue
        markdown = str(row.get("polished_markdown") or row.get("original_markdown") or row.get("markdown") or row.get("article_draft") or "")
        title = str(row.get("title") or row.get("article_topic") or "未命名稿件")
        status = LEGACY_STATUS_TO_DRAFT_STATUS.get(str(row.get("status") or ""), "draft_input")
        published_at = str(row.get("published_at") or "")
        draft = ArticleDraft(
            legacy_task_id=task_id,
            title=title,
            digest=str(row.get("digest") or ""),
            markdown=markdown,
            source_type="legacy_task",
            referenced_items=json.dumps(
                {"retrieved_knowledge": str(row.get("retrieved_knowledge") or "")},
                ensure_ascii=False,
            ),
            risk_level=str(row.get("risk_level") or ""),
            risk_report=str(row.get("risk_report") or row.get("risk_review") or ""),
            cover_prompt=str(row.get("cover_image_prompt") or ""),
            duplicate_check_result="",
            topic_angle=str(row.get("doctor_viewpoint") or ""),
            status=status,
            published_at=published_at,
            created_at=str(row.get("created_at") or now_text()),
            updated_at=str(row.get("updated_at") or now_text()),
        )
        session.add(draft)


def _sync_tags(session: Session) -> None:
    usage: dict[str, int] = {}
    for item in session.scalars(select(KnowledgeItem)).all():
        for raw_tag in (item.tags or "").replace(",", "、").replace("，", "、").split("、"):
            tag = raw_tag.strip()
            if not tag:
                continue
            usage[tag] = usage.get(tag, 0) + 1
    for name, count in usage.items():
        tag = session.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            session.add(Tag(name=name, usage_count=count))
        else:
            tag.usage_count = count


def init_orm_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with orm_session() as session:
        _ensure_knowledge_item_columns(session)
        _ensure_generated_image_columns(session)
        knowledge_base = ensure_default_knowledge_base(session)
        _sync_old_knowledge_items(session, knowledge_base.id)
        _seed_compliance_item(session, knowledge_base.id)
        _ensure_default_settings(session)
        _sync_legacy_tasks_to_article_drafts(session)
        _sync_tags(session)


def create_knowledge_base(name: str, description: str = "") -> KnowledgeBase:
    with orm_session() as session:
        base = KnowledgeBase(name=name.strip(), description=description.strip())
        session.add(base)
        session.flush()
        session.expunge(base)
        return base


def list_knowledge_bases() -> list[KnowledgeBase]:
    with orm_session() as session:
        bases = session.scalars(select(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc())).all()
        for base in bases:
            session.expunge(base)
        return bases


def get_knowledge_base(base_id: int) -> Optional[KnowledgeBase]:
    with orm_session() as session:
        base = session.get(KnowledgeBase, base_id)
        if base is not None:
            session.expunge(base)
        return base


def update_knowledge_base(base_id: int, *, name: str, description: str = "") -> None:
    with orm_session() as session:
        base = session.get(KnowledgeBase, base_id)
        if base is None:
            raise ValueError("知识库不存在。")
        base.name = name.strip()
        base.description = description.strip()
        base.updated_at = now_text()


def delete_knowledge_base(base_id: int) -> None:
    with orm_session() as session:
        for item in session.scalars(select(KnowledgeItem).where(KnowledgeItem.knowledge_base_id == base_id)).all():
            session.delete(item)
        base = session.get(KnowledgeBase, base_id)
        if base is not None:
            session.delete(base)


def create_knowledge_content(
    *,
    knowledge_base_id: int,
    title: str,
    content: str,
    summary: str = "",
    tags: str = "",
    risk_level: str = "",
    usage_status: str = "unused",
) -> KnowledgeItem:
    with orm_session() as session:
        item = KnowledgeItem(
            knowledge_base_id=knowledge_base_id,
            title=title.strip(),
            content=content.strip(),
            summary=summary.strip(),
            tags=tags.strip(),
            risk_level=risk_level.strip(),
            usage_status=usage_status,
            legacy_type="topic_material",
            enabled=True,
        )
        session.add(item)
        session.flush()
        _sync_tags(session)
        session.expunge(item)
        return item


def update_knowledge_content(
    item_id: int,
    *,
    title: str,
    content: str,
    summary: str = "",
    tags: str = "",
    risk_level: str = "",
    usage_status: str = "unused",
    enabled: bool = True,
) -> None:
    with orm_session() as session:
        item = session.get(KnowledgeItem, item_id)
        if item is None:
            raise ValueError("已收录内容不存在。")
        item.title = title.strip()
        item.content = content.strip()
        item.summary = summary.strip()
        item.tags = tags.strip()
        item.risk_level = risk_level.strip()
        item.usage_status = usage_status
        item.enabled = enabled
        item.updated_at = now_text()
        _sync_tags(session)


def list_knowledge_contents(knowledge_base_id: Optional[int] = None) -> list[KnowledgeItem]:
    with orm_session() as session:
        stmt = select(KnowledgeItem).order_by(KnowledgeItem.updated_at.desc(), KnowledgeItem.id.desc())
        if knowledge_base_id is not None:
            stmt = stmt.where(KnowledgeItem.knowledge_base_id == knowledge_base_id)
        items = session.scalars(stmt).all()
        for item in items:
            session.expunge(item)
        return items


def get_knowledge_content(item_id: int) -> Optional[KnowledgeItem]:
    with orm_session() as session:
        item = session.get(KnowledgeItem, item_id)
        if item is not None:
            session.expunge(item)
        return item


def delete_knowledge_content(item_id: int) -> None:
    with orm_session() as session:
        item = session.get(KnowledgeItem, item_id)
        if item is not None:
            session.delete(item)
        _sync_tags(session)


def create_article_draft(
    *,
    title: str,
    digest: str = "",
    markdown: str = "",
    source_type: str = "direct",
    knowledge_base_id: Optional[int] = None,
    referenced_items: str = "[]",
    risk_level: str = "",
    risk_report: str = "",
    cover_prompt: str = "",
    duplicate_check_result: str = "",
    topic_angle: str = "",
    status: str = "draft_input",
) -> ArticleDraft:
    with orm_session() as session:
        draft = ArticleDraft(
            title=title.strip(),
            digest=digest.strip(),
            markdown=markdown.strip(),
            source_type=source_type,
            knowledge_base_id=knowledge_base_id,
            referenced_items=referenced_items,
            risk_level=risk_level,
            risk_report=risk_report,
            cover_prompt=cover_prompt,
            duplicate_check_result=duplicate_check_result,
            topic_angle=topic_angle,
            status=status,
        )
        session.add(draft)
        session.flush()
        session.expunge(draft)
        return draft


def list_article_drafts(statuses: Optional[Sequence[str]] = None) -> list[ArticleDraft]:
    with orm_session() as session:
        stmt = select(ArticleDraft).order_by(ArticleDraft.updated_at.desc(), ArticleDraft.id.desc())
        if statuses:
            stmt = stmt.where(ArticleDraft.status.in_(list(statuses)))
        drafts = session.scalars(stmt).all()
        for draft in drafts:
            session.expunge(draft)
        return drafts


def get_article_draft_by_legacy_task(legacy_task_id: str) -> Optional[ArticleDraft]:
    with orm_session() as session:
        draft = session.scalar(select(ArticleDraft).where(ArticleDraft.legacy_task_id == legacy_task_id))
        if draft is not None:
            session.expunge(draft)
        return draft


def upsert_article_draft_from_legacy_task(
    *,
    legacy_task_id: str,
    title: str,
    digest: str = "",
    markdown: str = "",
    source_type: str = "knowledge_base",
    knowledge_base_id: Optional[int] = None,
    referenced_items: str = "[]",
    risk_level: str = "",
    risk_report: str = "",
    cover_prompt: str = "",
    duplicate_check_result: str = "",
    topic_angle: str = "",
    status: str = "doctor_review_pending",
) -> ArticleDraft:
    with orm_session() as session:
        draft = session.scalar(select(ArticleDraft).where(ArticleDraft.legacy_task_id == legacy_task_id))
        if draft is None:
            draft = ArticleDraft(legacy_task_id=legacy_task_id)
            session.add(draft)
        draft.title = title.strip()
        draft.digest = digest.strip()
        draft.markdown = markdown.strip()
        draft.source_type = source_type
        draft.knowledge_base_id = knowledge_base_id
        draft.referenced_items = referenced_items
        draft.risk_level = risk_level
        draft.risk_report = risk_report
        draft.cover_prompt = cover_prompt
        draft.duplicate_check_result = duplicate_check_result
        draft.topic_angle = topic_angle
        draft.status = status
        draft.updated_at = now_text()
        session.flush()
        session.expunge(draft)
        return draft


def get_article_draft(draft_id: int) -> Optional[ArticleDraft]:
    with orm_session() as session:
        draft = session.get(ArticleDraft, draft_id)
        if draft is not None:
            session.expunge(draft)
        return draft


def list_generated_images(article_draft_id: int) -> list[GeneratedImage]:
    with orm_session() as session:
        stmt = (
            select(GeneratedImage)
            .where(GeneratedImage.article_draft_id == article_draft_id)
            .order_by(GeneratedImage.image_role.asc(), GeneratedImage.slot_key.asc(), GeneratedImage.id.asc())
        )
        images = session.scalars(stmt).all()
        for image in images:
            session.expunge(image)
        return images


def get_generated_image(image_id: int) -> Optional[GeneratedImage]:
    with orm_session() as session:
        image = session.get(GeneratedImage, image_id)
        if image is not None:
            session.expunge(image)
        return image


def get_generated_image_by_slot(article_draft_id: int, slot_key: str) -> Optional[GeneratedImage]:
    with orm_session() as session:
        image = session.scalar(
            select(GeneratedImage).where(
                GeneratedImage.article_draft_id == article_draft_id,
                GeneratedImage.slot_key == slot_key,
            )
        )
        if image is not None:
            session.expunge(image)
        return image


def create_generated_image(
    *,
    article_draft_id: int,
    image_role: str,
    slot_key: str,
    prompt: str = "",
    negative_prompt: str = "",
    provider: str = "dummy",
    model: str = "",
    local_path: str = "",
    public_url: str = "",
    alt_text: str = "",
    caption: str = "",
    insert_position: str = "not_inserted",
    aspect_ratio: str = "16:9",
    style_preset: str = "温和治愈插画",
    visual_params: str = "{}",
    selected: bool = True,
    status: str = "prompt_ready",
    error_message: str = "",
) -> GeneratedImage:
    with orm_session() as session:
        image = GeneratedImage(
            article_draft_id=article_draft_id,
            image_role=image_role,
            slot_key=slot_key,
            prompt=prompt.strip(),
            negative_prompt=negative_prompt.strip(),
            provider=provider,
            model=model,
            local_path=local_path,
            public_url=public_url,
            alt_text=alt_text.strip(),
            caption=caption.strip(),
            insert_position=insert_position,
            aspect_ratio=aspect_ratio,
            style_preset=style_preset,
            visual_params=visual_params or "{}",
            selected=selected,
            status=status,
            error_message=error_message,
        )
        session.add(image)
        session.flush()
        session.expunge(image)
        return image


def update_generated_image(image_id: int, **updates: object) -> None:
    allowed = {
        "image_role",
        "slot_key",
        "prompt",
        "negative_prompt",
        "provider",
        "model",
        "local_path",
        "public_url",
        "alt_text",
        "caption",
        "insert_position",
        "aspect_ratio",
        "style_preset",
        "visual_params",
        "selected",
        "status",
        "error_message",
    }
    with orm_session() as session:
        image = session.get(GeneratedImage, image_id)
        if image is None:
            return
        for key, value in updates.items():
            if key in allowed:
                setattr(image, key, value)
        image.updated_at = now_text()


def delete_generated_image(image_id: int) -> None:
    with orm_session() as session:
        image = session.get(GeneratedImage, image_id)
        if image is not None:
            session.delete(image)


def replace_generated_images(article_draft_id: int, image_records: Sequence[dict[str, object]]) -> None:
    with orm_session() as session:
        for image in session.scalars(
            select(GeneratedImage).where(GeneratedImage.article_draft_id == article_draft_id)
        ).all():
            session.delete(image)
        for record in image_records:
            session.add(
                GeneratedImage(
                    article_draft_id=article_draft_id,
                    image_role=str(record.get("image_role", "inline")),
                    slot_key=str(record.get("slot_key", "")),
                    prompt=str(record.get("prompt", "")).strip(),
                    negative_prompt=str(record.get("negative_prompt", "")).strip(),
                    provider=str(record.get("provider", "dummy")),
                    model=str(record.get("model", "")),
                    local_path=str(record.get("local_path", "")),
                    public_url=str(record.get("public_url", "")),
                    alt_text=str(record.get("alt_text", "")).strip(),
                    caption=str(record.get("caption", "")).strip(),
                    insert_position=str(record.get("insert_position", "not_inserted")),
                    aspect_ratio=str(record.get("aspect_ratio", "16:9")),
                    style_preset=str(record.get("style_preset", "温和治愈插画")),
                    visual_params=str(record.get("visual_params", "{}")),
                    selected=bool(record.get("selected", True)),
                    status=str(record.get("status", "prompt_ready")),
                    error_message=str(record.get("error_message", "")),
                )
            )


def create_topic_history(
    *,
    topic_title: str,
    topic_angle: str = "",
    knowledge_base_id: Optional[int] = None,
    referenced_items: str = "[]",
    generated_article_id: Optional[int] = None,
    status: str = "suggested",
) -> TopicHistory:
    with orm_session() as session:
        topic = TopicHistory(
            topic_title=topic_title.strip(),
            topic_angle=topic_angle.strip(),
            knowledge_base_id=knowledge_base_id,
            referenced_items=referenced_items,
            generated_article_id=generated_article_id,
            status=status,
        )
        session.add(topic)
        session.flush()
        session.expunge(topic)
        return topic


def list_topic_history(limit: int = 60, knowledge_base_id: Optional[int] = None) -> list[TopicHistory]:
    with orm_session() as session:
        stmt = select(TopicHistory).order_by(TopicHistory.created_at.desc(), TopicHistory.id.desc())
        if knowledge_base_id is not None:
            stmt = stmt.where(TopicHistory.knowledge_base_id == knowledge_base_id)
        stmt = stmt.limit(limit)
        topics = session.scalars(stmt).all()
        for topic in topics:
            session.expunge(topic)
        return topics


def update_topic_history_generated_article(topic_id: int, generated_article_id: int, status: str = "generated") -> None:
    with orm_session() as session:
        topic = session.get(TopicHistory, topic_id)
        if topic is None:
            return
        topic.generated_article_id = generated_article_id
        topic.status = status
        topic.updated_at = now_text()


def create_revision_history(
    *,
    article_draft_id: int,
    old_title: str,
    old_markdown: str,
    user_feedback: str,
    new_title: str,
    new_markdown: str,
) -> RevisionHistory:
    with orm_session() as session:
        revision = RevisionHistory(
            article_draft_id=article_draft_id,
            old_title=old_title,
            old_markdown=old_markdown,
            user_feedback=user_feedback,
            new_title=new_title,
            new_markdown=new_markdown,
        )
        session.add(revision)
        session.flush()
        session.expunge(revision)
        return revision


def get_app_settings_map() -> dict[str, str]:
    with orm_session() as session:
        settings = session.scalars(select(AppSettings)).all()
        return {setting.key: setting.value for setting in settings}


def list_tags() -> list[Tag]:
    with orm_session() as session:
        tags = session.scalars(select(Tag).order_by(Tag.usage_count.desc(), Tag.name.asc())).all()
        for tag in tags:
            session.expunge(tag)
        return tags
