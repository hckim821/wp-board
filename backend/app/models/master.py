"""기준정보 모델.

스코프 (plan.md §2.6)
  * `Phase` / `Milestone` / `Owner` — **템플릿 단위**.
    프로젝트 계층에는 같은 모양의 로컬 사본이 따로 있다 (`models/project.py`).
  * `TemplateDocument` — **템플릿 단위** (§0.5.10 개편). 예전에는 전역
    `DocumentType` 이었고 호스트 마스터와의 병합 후보였으나, 사용자 결정으로
    포맷 종속이 되면서 그 이음매가 사라졌다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Phase(Base):
    """Phase 기준정보.

    `name` 은 **번호를 뺀 순수 이름**이다 (`Pre-Infrastructure Setup`).
    표시 문자열 `Phase 0. Pre-Infrastructure Setup` 은 조합해서 만든다.

    `seq_no` 는 기준정보 화면용 기본 표시순서다. **특정 버전을 조회할 때의
    번호는 그 버전의 행 순서에서 파생**하므로(`renumber_service`), DRAFT 를
    편집해도 PUBLISHED 버전의 번호가 흔들리지 않는다.
    """

    __tablename__ = "wp_phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_templates.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="phase", cascade="all, delete-orphan", order_by="Milestone.seq_no"
    )


class Milestone(Base):
    """Milestone 기준정보 (Phase 하위).

    `seq_no` 는 표시번호 `1.2` 의 **뒷자리만** 담는다. 앞자리는 소속 Phase 의
    번호에서 파생한다 — 따로 저장하면 Phase 재번호 시 두 값이 어긋난다
    (plan.md §2.1).
    """

    __tablename__ = "wp_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: 조회 편의를 위한 비정규화 컬럼. 정본은 `phase.template_id` 다.
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_templates.id", ondelete="CASCADE"), nullable=False
    )
    phase_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_phases.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    phase: Mapped[Phase] = relationship(back_populates="milestones")


class Owner(Base):
    """Owner 기준정보 (템플릿 스코프). 엑셀 `Owner` 컬럼의 `+` 분리 결과."""

    __tablename__ = "wp_owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_templates.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TemplateDocument(Base):
    """문서 — **템플릿(포맷)이 소유한다** (plan.md §0.5.10).

    전역 `wp_document_types` 를 대체한다. 문서는 이제 Phase/Milestone/Owner 와
    **같은 스코프 규칙**을 따른다: 템플릿이 갖고, 프로젝트 생성 시 복제되며,
    그 뒤로는 서로 무관하다. 원문자 코드 개념은 사라졌고 **표시 번호는
    `sort_order`(1..N 연속)** 다 — apply 가 재부여한다.

    Phase/Milestone 과 마찬가지로 **버전이 아니라 템플릿에 매인다.** 그래서
    draft 생성 시 복제하지 않는다 (복제하면 버전마다 같은 문서가 늘어난다).
    대신 삭제가 조건부다 — 다른 버전이 쓰고 있으면 비활성화한다 (§0.4 정밀화 1).
    """

    __tablename__ = "wp_template_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_templates.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 표시 번호. 1..N 연속을 apply 가 보장한다.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
