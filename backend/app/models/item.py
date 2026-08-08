from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, ItemOrigin, ItemStatus, enum_column


class Item(Base):
    """행 (Work Package 항목).

    `phase_id` / `milestone_id` 가 nullable 인 것은 **의도된 설계**다.
    임시저장은 검증 없이 화면 상태를 그대로 저장하므로 미지정 행이 존재할 수
    있어야 한다 (plan.md §2.5). 발행 시 V1/V2 가 이를 막는다.
    """

    __tablename__ = "wp_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: 표시 순서 = 엑셀 `No` 컬럼. renumber 대상.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("wp_phases.id", ondelete="RESTRICT"), nullable=True
    )
    milestone_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("wp_milestones.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    deliverable: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 대시보드 카드의 key action 요약 단어 (plan.md §0.5-1). NULL 이 정상 —
    #: 화면이 dash_label → deliverable → title 앞부분 순으로 폴백한다.
    dash_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    gate_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[ItemStatus] = mapped_column(
        enum_column(ItemStatus, "item_status"), nullable=False, default=ItemStatus.NOT_STARTED
    )
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    origin: Mapped[ItemOrigin] = mapped_column(
        enum_column(ItemOrigin, "item_origin"), nullable=False, default=ItemOrigin.INHERITED
    )
    #: deep copy 추적용. 원본 삭제와 무관하게 이력을 남기려고 물리 FK 를 걸지 않았다.
    source_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    version: Mapped["Version"] = relationship(back_populates="items")  # noqa: F821
    documents: Mapped[list["ItemDocument"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="ItemDocument.sort_order"
    )
    owners: Mapped[list["ItemOwner"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="ItemOwner.sort_order"
    )


class ItemDocument(Base):
    """행 ↔ 문서 (N:M). 엑셀 `관련 문서` 의 다중값을 정규화한 결과.

    문서는 **템플릿 스코프**이므로(§0.5.10) 이 링크도 같은 템플릿 안에서만
    성립한다. 문서를 지우면 링크가 CASCADE 로 함께 사라진다 — 삭제 캐스케이드가
    DB 에서도 지켜진다.
    """

    __tablename__ = "wp_item_documents"

    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_items.id", ondelete="CASCADE"), primary_key=True
    )
    template_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_template_documents.id", ondelete="CASCADE"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    item: Mapped[Item] = relationship(back_populates="documents")


class ItemOwner(Base):
    """행 ↔ Owner (N:M). 엑셀 `Owner` 의 `+` 다중값을 정규화한 결과."""

    __tablename__ = "wp_item_owners"

    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_items.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_owners.id", ondelete="RESTRICT"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    item: Mapped[Item] = relationship(back_populates="owners")
