"""프로젝트 계층 — plan.md §0.1.

프로젝트는 **발행된 템플릿 버전의 스냅샷**이다. 생성 시 항목·phase·milestone·owner
를 전부 복제하고, 그 뒤로는 템플릿과 완전히 독립이다.

* 템플릿을 다시 발행해도 기존 프로젝트는 바뀌지 않는다 (전파 없음).
* 프로젝트를 편집해도 템플릿은 바뀌지 않는다.
* **버전이 없다.** draft/발행/폐기/이력이 없고, 편집이 곧 저장이다.

그래서 이 모듈에는 `Version` 에 대응하는 것이 없고, 대신 `Project` 자신이 행의
스코프 역할을 한다. 그리드 동작(재계산 §2.2, 경계 §2.3, 회색 행 §0.2)은 템플릿과
같은 순수 서비스를 공유한다 — 다른 것은 스코프 컬럼뿐이다.

**문서도 복제한다** (§0.5.10 개편). 예전에는 전역이라 유일한 예외였는데, 사용자
확정으로 포맷 종속이 되면서 Phase/Milestone/Owner 와 같은 규칙에 들어왔다.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, ItemOrigin, ItemStatus, ProjectDocStatus, enum_column


class Project(Base):
    """설비사별 프로젝트.

    `maker_id` 는 **호스트 설비사 테이블의 PK 를 가리키는 논리적 참조**다
    (INTEGRATION.md §2.1). 물리 FK 도, `relationship` 도 없다. 설비사 이름이
    필요하면 `MakerResolver` 포트로 호스트에 위임한다 — 이 모듈은 절대 설비사
    테이블로 JOIN 하지 않는다. **모듈 전체에서 maker 를 아는 곳은 여기뿐이다.**

    `source_template_id` / `source_version_id` 에 물리 FK 가 없는 것은
    `Item.source_item_id` 와 같은 이유다 — 원본이 지워져도 출처 이력은 남아야 한다.
    프로젝트는 스냅샷이므로 원본 삭제가 내용에 영향을 주지 않는다.
    """

    __tablename__ = "wp_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    maker_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 생성 시점의 표시 번호 시작값 스냅샷 (plan.md §0.1).
    phase_start_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["ProjectItem"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectItem.sort_order",
    )


class ProjectPhase(Base):
    """Phase (프로젝트 로컬 사본). 템플릿의 `Phase` 와 같은 모양, 스코프만 다르다."""

    __tablename__ = "wp_project_phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_phase_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    milestones: Mapped[list["ProjectMilestone"]] = relationship(
        back_populates="phase", cascade="all, delete-orphan", order_by="ProjectMilestone.seq_no"
    )


class ProjectMilestone(Base):
    """Milestone (프로젝트 로컬 사본).

    `seq_no` 는 표시번호 `1.2` 의 **뒷자리만** 담는다. 앞자리는 소속 Phase 에서
    파생한다 (plan.md §2.1) — 템플릿과 같은 규칙이다.
    """

    __tablename__ = "wp_project_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: 조회 편의를 위한 비정규화 컬럼. 정본은 `phase.project_id` 다.
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_projects.id", ondelete="CASCADE"), nullable=False
    )
    phase_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_project_phases.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_milestone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    phase: Mapped[ProjectPhase] = relationship(back_populates="milestones")


class ProjectOwner(Base):
    """Owner (프로젝트 로컬 사본)."""

    __tablename__ = "wp_project_owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    source_owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectItem(Base):
    """프로젝트의 행.

    `phase_id` / `milestone_id` 가 nullable 인 것은 템플릿과 같은 이유이고, 여기서는
    한 가지가 더 있다 — **프로젝트에는 발행이 없으므로 회색 행이 그대로 남아 있어도
    된다** (plan.md §0.2-7). 템플릿에서는 발행 시 V1/V2 가 잡지만, 프로젝트에는
    그 관문 자체가 없다.
    """

    __tablename__ = "wp_project_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_projects.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("wp_project_phases.id", ondelete="RESTRICT"), nullable=True
    )
    milestone_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("wp_project_milestones.id", ondelete="RESTRICT"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    deliverable: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: plan.md §0.5-1. 생성 시 템플릿 행의 값을 그대로 복제한다.
    dash_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    gate_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[ItemStatus] = mapped_column(
        enum_column(ItemStatus, "item_status"), nullable=False, default=ItemStatus.NOT_STARTED
    )
    completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    origin: Mapped[ItemOrigin] = mapped_column(
        enum_column(ItemOrigin, "item_origin"), nullable=False, default=ItemOrigin.INHERITED
    )
    #: 복제 원본(템플릿 행) 추적용. 물리 FK 없음 — 원본 삭제와 무관하게 이력 보존.
    source_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="items")
    documents: Mapped[list["ProjectItemDocument"]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
        order_by="ProjectItemDocument.sort_order",
    )
    owners: Mapped[list["ProjectItemOwner"]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
        order_by="ProjectItemOwner.sort_order",
    )


class ProjectItemDocument(Base):
    """프로젝트 행 ↔ 문서 (N:M).

    **프로젝트 로컬 문서를 가리킨다** (§0.5.10 개편). 예전에는 전역
    `wp_document_types` 를 가리켰고 그것이 문서를 복제하지 않는 유일한 예외였는데,
    문서가 포맷 종속이 되면서 Owner·Phase 와 같은 규칙으로 정리됐다 — 프로젝트가
    자기 사본을 갖는다.
    """

    __tablename__ = "wp_project_item_documents"

    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_project_items.id", ondelete="CASCADE"), primary_key=True
    )
    project_document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_project_documents.id", ondelete="CASCADE"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    item: Mapped[ProjectItem] = relationship(back_populates="documents")


class ProjectDocument(Base):
    """프로젝트 문서 (plan.md §0.5.10 개편).

    예전에는 전역 문서를 가리키는 설정 행이었다 (`document_type_id` + 사용/링크/
    상태). 이제는 **문서 그 자체**다 — 프로젝트 생성 시 템플릿 문서에서 복제되고,
    이후 이름을 고치거나 행을 더하거나 지울 수 있다 (사용자 확정 ②).

    그래서 "행이 없으면 기본값" 이라는 §0.5-4 의 lazy 규칙도 사라졌다. 있는 행이
    전부이고, 없으면 그 프로젝트에 그 문서가 없는 것이다.

    표시 번호는 `sort_order`(1..N 연속) 이며 저장이 재부여한다.
    """

    __tablename__ = "wp_project_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_used: Mapped[bool] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    #: 작성 상태와 무관하게 NULL 허용 — 완료된 문서의 링크를 아직 못 받았을 수 있다.
    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doc_status: Mapped[ProjectDocStatus] = mapped_column(
        enum_column(ProjectDocStatus, "project_doc_status"),
        nullable=False,
        default=ProjectDocStatus.NOT_WRITTEN,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectLink(Base):
    """프로젝트 주요 링크 (plan.md §0.5.5).

    Confluence 페이지·클라우드 파일처럼 프로젝트가 **자유롭게 늘리고 줄이는**
    외부 링크 목록이다. `ProjectDocument`(§0.5-4) 와 헷갈리기 쉬운데 성격이
    반대다 — 그쪽은 전역 문서 마스터가 정한 집합에 링크·상태를 붙이는 것이고,
    행이 없어도 기본값으로 읽힌다. 이쪽은 마스터가 없고, 있는 행이 전부다.

    `sort_order` 는 화면의 drag 순서이며 **서버가 다시 매긴다.** 저장이 배열
    순서를 정본으로 삼는 전량 교체라, 클라이언트가 실어 보낸 번호를 그대로
    믿으면 정본이 둘이 된다 (`Item.sort_order` 와 같은 태도).

    프로젝트 삭제 시 CASCADE 로 함께 지워진다. 링크는 프로젝트 밖에서 의미를
    갖지 않으므로 이력을 남길 이유가 없다.
    """

    __tablename__ = "wp_project_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_projects.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectItemOwner(Base):
    """프로젝트 행 ↔ Owner (N:M). Owner 는 프로젝트 로컬 사본을 가리킨다."""

    __tablename__ = "wp_project_item_owners"

    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_project_items.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wp_project_owners.id", ondelete="RESTRICT"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    item: Mapped[ProjectItem] = relationship(back_populates="owners")
