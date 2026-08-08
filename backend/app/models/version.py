from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, VersionStatus, enum_column


class Version(Base):
    """템플릿 버전. 상태 기계는 `DRAFT → PUBLISHED → ARCHIVED` (plan.md §2.4).

    **버전은 템플릿 계층에만 있다** (plan.md §0.1). 프로젝트는 생성이 곧 확정이라
    이 모델에 대응하는 것이 없다.

    "템플릿 당 DRAFT 1개 / PUBLISHED 1개" 는 DB 제약으로 표현할 수 없어
    `version_service` 가 WP 행 잠금과 함께 보장한다.
    """

    __tablename__ = "wp_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_templates.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[VersionStatus] = mapped_column(
        enum_column(VersionStatus, "version_status"), nullable=False, default=VersionStatus.DRAFT
    )
    source_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("wp_versions.id", ondelete="SET NULL"), nullable=True
    )
    #: 발행 시점의 `phase_start_no` 스냅샷 (plan.md §2.4).
    #: 버전은 자기 표시 파라미터를 스스로 들고 있어야 한다 — WP 의 값을 나중에
    #: 바꿔도 발행된 버전의 번호가 흔들리지 않도록. DRAFT 는 NULL.
    phase_start_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    template: Mapped["Template"] = relationship(back_populates="versions")  # noqa: F821
    items: Mapped[list["Item"]] = relationship(  # noqa: F821
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="Item.sort_order",
    )

    @property
    def is_editable(self) -> bool:
        return self.status == VersionStatus.DRAFT
