"""템플릿 문서 — plan.md §0.5.10.

문서는 **템플릿(포맷)이 소유한다.** Phase/Milestone 과 같은 자리에 있으므로 관리
방식도 같다: 팝업 하나에서 추가·이름변경·순서변경·삭제를 하고, `apply` 가 **집합
전체**를 원자적으로 받는다 (§0.4 의 phases/apply 동형).

## 삭제가 조건부인 이유

문서는 버전이 아니라 **템플릿**에 매인다 (Phase/Milestone 과 같다). 그래서 DRAFT 에서
지운 문서를 PUBLISHED 가 여전히 쓰고 있을 수 있다. 그 경우 하드 삭제하면 발행본이
깨지므로 **비활성화**한다 — §0.4 "구현 시 확정된 정밀화 1" 과 같은 판단이며, 사용자
관점의 결과(이 보드에서 사라진다)는 어느 쪽이든 같다.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.exceptions import UnprocessableEntityError
from ..models import Item, ItemDocument, TemplateDocument
from ..schemas.document import DocumentApplyEntry


def list_documents(session: Session, template_id: int) -> list[TemplateDocument]:
    return list(
        session.scalars(
            select(TemplateDocument)
            .where(TemplateDocument.template_id == template_id)
            .order_by(TemplateDocument.sort_order, TemplateDocument.id)
        )
    )


def _reject(message: str, *, code: str, **detail):
    raise UnprocessableEntityError(message, code=code, detail=detail)


def usage_outside(session: Session, document_id: int, version_id: int) -> int:
    """이 문서를 **다른 버전**의 행이 쓰는 수. 하드 삭제 가부를 가른다."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(ItemDocument)
            .join(Item, Item.id == ItemDocument.item_id)
            .where(
                ItemDocument.template_document_id == document_id,
                Item.version_id != version_id,
            )
        )
        or 0
    )


def apply_documents(
    session: Session,
    template_id: int,
    version_id: int,
    entries: list[DocumentApplyEntry],
    deleted_ids: list[int],
) -> list[TemplateDocument]:
    """팝업 표의 최종 상태를 통째로 받는다 — **원자적**이다.

    배열 순서가 곧 `sort_order`(1..N). `entries` + `deleted_ids` 가 기존 전체 집합과
    정확히 일치해야 한다 (`phases/apply` 와 같은 집합 일치 규칙) — 화면이 보지 못한
    문서를 조용히 남기거나 지우지 않기 위해서다.
    """
    existing = {d.id: d for d in list_documents(session, template_id)}

    referenced = [e.id for e in entries if e.id is not None]
    duplicated = sorted({i for i in referenced if referenced.count(i) > 1})
    if duplicated:
        _reject(f"같은 문서가 두 번 들어 있습니다: {duplicated}",
                code="DOCUMENT_DUPLICATED", document_ids=duplicated)

    for index, entry in enumerate(entries):
        if not (entry.name or "").strip():
            _reject(f"{index + 1}행: 문서명을 입력하세요.",
                    code="DOCUMENT_EMPTY_NAME", index=index, row_no=index + 1, field="name")
        if entry.id is not None and entry.id not in existing:
            _reject(f"{index + 1}행: 이 템플릿의 문서가 아닙니다 (id={entry.id}).",
                    code="DOCUMENT_OUT_OF_SCOPE", index=index, row_no=index + 1,
                    field="id", document_id=entry.id)

    names = [e.name.strip() for e in entries]
    dupe_names = sorted({n for n in names if names.count(n) > 1})
    if dupe_names:
        _reject(f"문서명이 중복됩니다: {dupe_names}",
                code="DOCUMENT_DUPLICATE_NAME", names=dupe_names)

    unknown = sorted(set(deleted_ids) - set(existing))
    if unknown:
        _reject(f"이 템플릿의 문서가 아닙니다: {unknown}",
                code="DOCUMENT_OUT_OF_SCOPE", document_ids=unknown)

    # 집합 일치 — 기존 전체가 목록 ∪ 삭제로 정확히 덮여야 한다.
    covered = set(referenced) | set(deleted_ids)
    missing = sorted(set(existing) - covered)
    if missing or (set(referenced) & set(deleted_ids)):
        _reject(
            "문서 목록이 기존 집합과 일치하지 않습니다.",
            code="DOCUMENT_SET_MISMATCH",
            missing=missing,
            both=sorted(set(referenced) & set(deleted_ids)),
            expected=sorted(existing),
        )

    for document_id in deleted_ids:
        document = existing.pop(document_id)

        # **이 버전의 링크는 어느 쪽이든 지운다.** 사용자는 이 보드에서 문서를
        # 없앤 것이고, 비활성화는 *다른 버전*을 보호하려는 장치일 뿐이다. 링크를
        # 남겨 두면 비활성 문서가 이 보드의 행에 계속 붙어 보인다.
        session.query(ItemDocument).filter(
            ItemDocument.template_document_id == document_id,
            ItemDocument.item_id.in_(
                select(Item.id).where(Item.version_id == version_id)
            ),
        ).delete(synchronize_session=False)

        if usage_outside(session, document_id, version_id):
            # 다른 버전이 여전히 쓰고 있다 — 지우면 그 발행본이 깨진다
            # (§0.4 정밀화 1과 같은 판단). 하드 삭제 대신 비활성화한다.
            document.is_active = 0
        else:
            session.delete(document)

    ordered: list[TemplateDocument] = []
    for index, entry in enumerate(entries, start=1):
        if entry.id is not None:
            document = existing[entry.id]
        else:
            document = TemplateDocument(template_id=template_id, sort_order=index, name="")
            session.add(document)
        document.sort_order = index
        document.name = entry.name.strip()
        document.is_active = 1
        ordered.append(document)

    session.flush()
    return ordered
