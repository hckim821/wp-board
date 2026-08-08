"""버전 상태 기계와 deep copy — plan.md §2.4.

```
없음 ──draft 발행──▶ DRAFT ──발행(검증 통과)──▶ PUBLISHED ──신규 발행──▶ ARCHIVED
                      ▲                            │
                      └────── draft 발행(deep copy)─┘
```

불변 규칙

* 템플릿 당 `DRAFT` 최대 1개 / `PUBLISHED` 최대 1개
* `PUBLISHED` / `ARCHIVED` 의 행은 **수정 불가** — API 레벨에서 막는다

MariaDB 에 부분 유니크 인덱스가 없어 위 두 개수 제한은 DDL 로 표현할 수 없다.
그래서 `create_draft` / `publish` 는 **템플릿 행을 `FOR UPDATE` 로 잠근 뒤** 개수를
확인한다. 동시에 두 요청이 들어와도 하나는 기다렸다가 충돌을 보게 된다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.exceptions import ConflictError, NotFoundError, PublishValidationError
from ..models import (
    Item,
    ItemDocument,
    ItemOwner,
    Milestone,
    Owner,
    Phase,
    TemplateDocument,
    Version,
    VersionStatus,
    Template,
)
from ..models.base import ItemOrigin
from ..schemas.validation import ValidationResultOut
from . import item_service
from .board import TEMPLATE_BOARD, Board
from .validation_service import (
    MasterRef,
    MilestoneRef,
    PhaseRef,
    ValidationInput,
    ValidationResult,
    ValidationRow,
    validate,
)


# =============================================================================
# 조회 / 가드
# =============================================================================
def effective_phase_start_no(session: Session, version: Version) -> int:
    """이 버전의 표시 번호 시작값.

    발행된 버전은 **자기 스냅샷**을 쓴다 (plan.md §2.4). 템플릿의 `phase_start_no`
    를 나중에 바꿔도 이미 발행된 버전의 번호는 흔들리지 않아야 하기 때문이다.
    DRAFT 는 스냅샷이 없으므로 템플릿의 현재 값을 따른다.
    """
    if version.phase_start_no is not None:
        return version.phase_start_no
    template = session.get(Template, version.template_id)
    return template.phase_start_no if template else 0


def board_of(session: Session, version: Version) -> Board:
    """이 버전을 **보드**로 감싼다 — `item_service` 가 아는 유일한 형태.

    `sync_master_seq` 가 DRAFT 에서만 참인 것이 핵심이다. PUBLISHED/ARCHIVED 를
    조회하는 것만으로 기준정보의 `seq_no` 가 바뀌면 안 된다.
    """
    return Board(
        spec=TEMPLATE_BOARD,
        scope_id=version.id,
        master_scope_id=version.template_id,
        phase_start_no=effective_phase_start_no(session, version),
        sync_master_seq=version.status == VersionStatus.DRAFT,
    )


def get_template(session: Session, template_id: int) -> Template:
    wp = session.get(Template, template_id)
    if wp is None:
        raise NotFoundError(f"템플릿 {template_id} 를 찾을 수 없습니다.")
    return wp


def get_version(session: Session, version_id: int) -> Version:
    version = session.get(Version, version_id)
    if version is None:
        raise NotFoundError(f"버전 {version_id} 을(를) 찾을 수 없습니다.")
    return version


def _assert_draft(version: Version) -> Version:
    if version.status != VersionStatus.DRAFT:
        raise ConflictError(
            f"{version.status.value} 상태의 버전은 수정할 수 없습니다. "
            "먼저 draft 발행으로 새 DRAFT 를 만드세요."
        )
    return version


def lock_editable_version(session: Session, version_id: int) -> Version:
    """쓰기 경로의 유일한 입구 — **행을 잠근 뒤** 상태를 확인한다.

    잠금 없이 상태만 읽고 통과시키면 검사와 쓰기 사이에 다른 요청이 끼어든다.
    실제로 재현된 두 경로:

    * `임시저장 vs 발행` — 방금 발행된 버전을 임시저장이 덮어쓴다.
    * `폐기 vs 발행` — **PUBLISHED 가 하나도 없는 상태**가 만들어지고, 이후
      draft 발행이 복사할 원본을 찾지 못해 빈 보드를 만든다.

    그래서 `SELECT ... FOR UPDATE` 로 버전 행을 잠그고 상태를 **다시 읽는다.**
    """
    version = session.scalar(
        select(Version)
        .where(Version.id == version_id)
        .with_for_update()
        # `populate_existing` 이 없으면 SQLAlchemy 가 identity map 의 낡은
        # 객체를 그대로 돌려준다. 행은 잠기지만 상태는 예전 값을 읽게 되어
        # 잠금이 무의미해진다.
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise NotFoundError(f"버전 {version_id} 을(를) 찾을 수 없습니다.")
    return _assert_draft(version)


def _lock_template(session: Session, template_id: int) -> Template:
    """템플릿 행을 잠가 버전 개수 검사와 상태 전이를 직렬화한다."""
    wp = session.scalar(
        select(Template)
        .where(Template.id == template_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if wp is None:
        raise NotFoundError(f"템플릿 {template_id} 를 찾을 수 없습니다.")
    return wp


def find_by_status(session: Session, template_id: int, status: VersionStatus) -> Version | None:
    return session.scalar(
        select(Version)
        .where(Version.template_id == template_id, Version.status == status)
        .execution_options(populate_existing=True)
    )


def list_versions(session: Session, template_id: int) -> list[Version]:
    return list(
        session.scalars(
            select(Version)
            .where(Version.template_id == template_id)
            .order_by(Version.version_number.desc())
        )
    )


# =============================================================================
# draft 발행 (deep copy)
# =============================================================================
def create_draft(
    session: Session,
    template_id: int,
    *,
    created_by: str | None = None,
    notes: str | None = None,
) -> Version:
    """현재 PUBLISHED 를 deep copy 해 `version_number + 1` 의 DRAFT 를 만든다.

    PUBLISHED 가 없으면 빈 v1 DRAFT 를 만든다.

    **Phase/Milestone/Owner/문서는 복사하지 않는다.** 그것들은 버전이 아니라
    템플릿에 매인 기준정보이기 때문이다 (plan.md §2.6, §3.2 `template_id` 스코프).
    복사하면 같은 문서가 버전마다 늘어난다. 복사 대상은 행과 그 N:M 연관관계다.
    """
    _lock_template(session, template_id)

    if find_by_status(session, template_id, VersionStatus.DRAFT) is not None:
        raise ConflictError("이미 DRAFT 버전이 존재합니다. 템플릿 당 DRAFT 는 하나뿐입니다.")

    published = find_by_status(session, template_id, VersionStatus.PUBLISHED)

    max_number = session.scalar(
        select(func.max(Version.version_number)).where(
            Version.template_id == template_id
        )
    )
    draft = Version(
        template_id=template_id,
        version_number=(max_number or 0) + 1,
        status=VersionStatus.DRAFT,
        source_version_id=published.id if published else None,
        notes=notes,
        created_by=created_by,
    )
    session.add(draft)
    session.flush()

    if published is not None:
        for src in item_service.load_ordered_items(session, board_of(session, published)):
            copy = Item(
                version_id=draft.id,
                sort_order=src.sort_order,
                phase_id=src.phase_id,
                milestone_id=src.milestone_id,
                title=src.title,
                deliverable=src.deliverable,
                dash_label=src.dash_label,
                gate_code=src.gate_code,
                status=src.status,
                completion_date=src.completion_date,
                origin=ItemOrigin.INHERITED,
                source_item_id=src.id,
            )
            copy.documents = [
                ItemDocument(template_document_id=d.template_document_id, sort_order=d.sort_order)
                for d in src.documents
            ]
            copy.owners = [
                ItemOwner(owner_id=o.owner_id, sort_order=o.sort_order) for o in src.owners
            ]
            session.add(copy)
        session.flush()

    return draft


# =============================================================================
# 검증
# =============================================================================
def build_validation_input(session: Session, version: Version) -> ValidationInput:
    """DB 에서 검증 입력을 모은다.

    `validation_service` 를 순수하게 유지하려고 DB 접근을 전부 여기로 몰았다.
    덕분에 V1~V14 는 DB 없이 테스트된다.
    """
    wp = get_template(session, version.template_id)
    items = item_service.load_ordered_items(session, board_of(session, version))

    phases = [
        PhaseRef(id=p.id, name=p.name, seq_no=p.seq_no, is_active=bool(p.is_active))
        for p in session.scalars(
            select(Phase).where(Phase.template_id == wp.id).order_by(Phase.seq_no, Phase.id)
        )
    ]
    milestones = [
        MilestoneRef(
            id=m.id, phase_id=m.phase_id, name=m.name, seq_no=m.seq_no, is_active=bool(m.is_active)
        )
        for m in session.scalars(
            select(Milestone)
            .where(Milestone.template_id == wp.id)
            .order_by(Milestone.phase_id, Milestone.seq_no, Milestone.id)
        )
    ]
    owners = [
        MasterRef(id=o.id, name=o.name, is_active=bool(o.is_active))
        for o in session.scalars(select(Owner).where(Owner.template_id == wp.id))
    ]
    # 문서도 **템플릿 스코프**다 (§0.5.10) — Owner 와 같은 방식으로 읽는다.
    doc_types = [
        MasterRef(id=d.id, name=d.name, is_active=bool(d.is_active))
        for d in session.scalars(
            select(TemplateDocument).where(TemplateDocument.template_id == wp.id)
        )
    ]

    rows = [
        ValidationRow(
            item_id=item.id,
            row_no=index,
            phase_id=item.phase_id,
            milestone_id=item.milestone_id,
            title=item.title,
            deliverable=item.deliverable,
            document_ids=[d.template_document_id for d in item.documents],
            owner_ids=[o.owner_id for o in item.owners],
        )
        for index, item in enumerate(items, start=1)
    ]

    return ValidationInput(
        rows=rows,
        phases=phases,
        milestones=milestones,
        owners=owners,
        document_types=doc_types,
        phase_start_no=effective_phase_start_no(session, version),
    )


def validate_version(session: Session, version: Version) -> ValidationResult:
    return validate(build_validation_input(session, version))


# =============================================================================
# 발행 / 폐기
# =============================================================================
def publish(
    session: Session,
    version_id: int,
    *,
    published_by: str | None = None,
    notes: str | None = None,
) -> Version:
    """검증 통과 시 `DRAFT → PUBLISHED`, 기존 PUBLISHED 는 ARCHIVED.

    실패하면 `PublishValidationError` 를 던진다. API 레이어가 트랜잭션을
    롤백하므로 **상태도 데이터도 바뀌지 않는다.**

    **검증 → (통과 시) 재계산 → 상태 전이** 순서다. 예전에는 재계산을 먼저
    했는데, 그러면 `/validate` 미리보기와 결과가 갈렸다 — 미리보기는
    `PHASE_SEQ_GAP` 을 보여주고 발행은 성공하는 모순. plan.md §2.5 는 두 경로가
    **같은 상태**를 평가하도록 요구한다.
    """
    # 잠금 순서는 항상 템플릿 → 버전. 반대로 잡는 경로가 생기면 교착이 난다.
    # 템플릿 id 를 알아내려면 먼저 한 번 읽어야 하는데, 이 읽기는 판단에 쓰지 않는다 —
    # 상태 판정은 아래 잠금 뒤의 재조회 결과로만 한다.
    probe = session.get(Version, version_id)
    if probe is None:
        raise NotFoundError(f"버전 {version_id} 을(를) 찾을 수 없습니다.")
    _lock_template(session, probe.template_id)
    version = lock_editable_version(session, version_id)

    result = validate_version(session, version)
    if not result.valid:
        raise PublishValidationError(
            f"발행 검증에 실패했습니다. (오류 {len(result.errors)}건)",
            detail=ValidationResultOut.model_validate(result).model_dump(exclude_none=True),
        )

    # 검증을 통과했으니 번호를 정규화해 저장한다.
    board = board_of(session, version)
    items = item_service.load_ordered_items(session, board)
    item_service.renumber_and_persist(session, board, items)

    now = datetime.now()
    current = find_by_status(session, version.template_id, VersionStatus.PUBLISHED)
    if current is not None and current.id != version.id:
        current.status = VersionStatus.ARCHIVED
        current.archived_at = now

    version.status = VersionStatus.PUBLISHED
    version.published_at = now
    # 표시 파라미터를 버전에 고정한다 (plan.md §2.4 원칙). 이후 템플릿의
    # phase_start_no 가 바뀌어도 이 버전의 번호는 흔들리지 않는다.
    version.phase_start_no = effective_phase_start_no(session, version)
    if published_by:
        version.published_by = published_by
    if notes:
        version.notes = notes

    session.flush()
    return version


def discard(session: Session, version_id: int) -> None:
    """DRAFT 폐기. PUBLISHED/ARCHIVED 는 지울 수 없다.

    상태 검사는 **잠금 하에서** 한다. 잠그지 않으면 `폐기 vs 발행` 이 엇갈려
    PUBLISHED 가 하나도 없는 상태가 만들어진다.

    폐기 후에는 기준정보의 `seq_no` 를 남은 PUBLISHED 기준으로 되돌린다.
    DRAFT 편집 중에 갱신된 번호가 그대로 남으면, 손대지도 않은 PUBLISHED 버전에
    대해 V6/V7 이 헛되이 `PHASE_SEQ_GAP` 을 내기 때문이다.
    """
    probe = session.get(Version, version_id)
    if probe is None:
        raise NotFoundError(f"버전 {version_id} 을(를) 찾을 수 없습니다.")
    _lock_template(session, probe.template_id)

    version = session.scalar(
        select(Version)
        .where(Version.id == version_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise NotFoundError(f"버전 {version_id} 을(를) 찾을 수 없습니다.")
    if version.status != VersionStatus.DRAFT:
        raise ConflictError(
            f"{version.status.value} 상태의 버전은 폐기할 수 없습니다. DRAFT 만 폐기 가능합니다."
        )

    template_id = version.template_id
    session.delete(version)
    session.flush()

    published = find_by_status(session, template_id, VersionStatus.PUBLISHED)
    if published is not None:
        item_service.resync_master_numbering(session, board_of(session, published))
