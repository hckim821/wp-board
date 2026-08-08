from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Template(Base):
    """WP 템플릿 — **중앙 기준 데이터** (plan.md §0.1).

    이전 이름은 `WorkPackage` 였고 `maker_id` 를 가졌다. §0 이 시나리오를 정정하면서
    템플릿은 설비사에 매이지 않는 중앙 관리 대상이 되었다. 설비사별 인스턴스는
    `Project` 이며, **호스트 설비사 참조는 이제 `Project.maker_id` 한 곳뿐**이다
    (INTEGRATION.md §2.1).

    버전 관리(DRAFT → PUBLISHED → ARCHIVED, plan.md §2.4)는 이 계층에만 있다.
    """

    __tablename__ = "wp_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase_start_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    versions: Mapped[list["Version"]] = relationship(  # noqa: F821
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="Version.version_number",
    )
