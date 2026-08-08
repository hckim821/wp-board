"""프로젝트 문서 — plan.md §0.5.10 (문서 모델 개편).

## 무엇이 바뀌었나

예전에는 전역 문서(`wp_document_types`)에 프로젝트별 **설정**(사용/링크/상태)만
붙이는 구조였고, 행이 없으면 기본값으로 읽는 lazy 규칙이 있었다. 이제 문서는
**프로젝트가 소유한다** — 생성 시 템플릿에서 복제되고, 이후 이름을 고치거나 행을
더하거나 지울 수 있다 (사용자 확정 ②).

따라서 lazy 규칙은 사라졌다. **있는 행이 전부**이고, 없으면 그 프로젝트에 그 문서가
없는 것이다. 표시 번호는 `sort_order`(1..N 연속)이고 저장이 재부여한다.

## 저장은 전량 교체다

배열 순서가 곧 `sort_order` 이고, `deleted_ids` 로 명시 삭제한다. 삭제하면 그 문서를
쓰던 **항목 링크가 함께 사라진다** (DB 의 CASCADE 가 지킨다) — 그래서 응답에
재계산된 items 를 함께 실어 그리드가 곧바로 갱신되게 한다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.exceptions import UnprocessableEntityError
from ..models import ProjectDocument
from ..schemas.project import ProjectDocumentOut, ProjectDocumentSaveIn
from .document_numbering import display_numbers


def list_documents(session: Session, project_id: int) -> list[ProjectDocument]:
    return list(
        session.scalars(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == project_id)
            .order_by(ProjectDocument.sort_order, ProjectDocument.id)
        )
    )


def by_project(session: Session, project_ids: list[int]) -> dict[int, list[ProjectDocument]]:
    """여러 프로젝트의 문서를 **한 번에** (전체 현황용).

    프로젝트마다 쿼리를 돌면 설비사가 늘수록 관망 화면만 느려진다.
    """
    if not project_ids:
        return {}
    rows = session.scalars(
        select(ProjectDocument)
        .where(ProjectDocument.project_id.in_(project_ids))
        .order_by(ProjectDocument.project_id, ProjectDocument.sort_order, ProjectDocument.id)
    )
    grouped: dict[int, list[ProjectDocument]] = {pid: [] for pid in project_ids}
    for row in rows:
        grouped[row.project_id].append(row)
    return grouped


def to_out(document: ProjectDocument, no: int | None) -> ProjectDocumentOut:
    """`no` 는 **파생값**이다 — 사용 중인 문서만 세어 매긴 번호이거나 `None`.

    `sort_order` 를 그대로 쓰지 않는 이유는 §0.5.10 팝업 정밀화에 있다: 꺼진
    문서가 번호를 차지하면 화면 목록이 `1, 3, 4` 처럼 구멍 난 채로 읽힌다.
    """
    return ProjectDocumentOut(
        id=document.id,
        no=no,
        name=document.name,
        is_used=bool(document.is_used),
        link_url=document.link_url,
        doc_status=document.doc_status,
    )


def list_documents_out(session: Session, project_id: int) -> list[ProjectDocumentOut]:
    """등록 탭·셀 팝업이 그대로 쓰는 형태 (파생 번호 포함)."""
    documents = list_documents(session, project_id)
    numbers = display_numbers(documents)
    return [to_out(d, numbers[d.id]) for d in documents]


def replace_documents(
    session: Session,
    project_id: int,
    payload: list[ProjectDocumentSaveIn],
    deleted_ids: list[int],
) -> list[ProjectDocument]:
    """전량 교체 — 배열 순서 = `sort_order`. **한 트랜잭션이다.**

    검증을 전부 끝낸 뒤에 쓰므로 422 면 아무것도 바뀌지 않는다. 오류에는
    `index`/`row_no`/`field` 를 실어 그리드가 문제의 셀을 짚을 수 있게 한다.
    """
    existing = {d.id: d for d in list_documents(session, project_id)}

    referenced = [entry.id for entry in payload if entry.id is not None]
    duplicated = sorted({i for i in referenced if referenced.count(i) > 1})
    if duplicated:
        raise UnprocessableEntityError(
            f"같은 문서가 두 번 들어 있습니다: {duplicated}",
            code="DOCUMENT_DUPLICATED",
            detail={"document_ids": duplicated},
        )

    for index, entry in enumerate(payload):
        if not (entry.name or "").strip():
            raise UnprocessableEntityError(
                f"{index + 1}행: 문서명을 입력하세요.",
                code="DOCUMENT_EMPTY_NAME",
                detail={"index": index, "row_no": index + 1, "field": "name"},
            )
        if entry.id is not None and entry.id not in existing:
            raise UnprocessableEntityError(
                f"{index + 1}행: 이 프로젝트의 문서가 아닙니다 (id={entry.id}).",
                code="DOCUMENT_OUT_OF_SCOPE",
                detail={"index": index, "row_no": index + 1, "field": "id",
                        "document_id": entry.id},
            )

    unknown_deleted = sorted(set(deleted_ids) - set(existing))
    if unknown_deleted:
        raise UnprocessableEntityError(
            f"이 프로젝트의 문서가 아닙니다: {unknown_deleted}",
            code="DOCUMENT_OUT_OF_SCOPE",
            detail={"document_ids": unknown_deleted},
        )
    both = sorted(set(deleted_ids) & set(referenced))
    if both:
        raise UnprocessableEntityError(
            f"같은 문서를 저장과 삭제에 함께 넣을 수 없습니다: {both}",
            code="DOCUMENT_DELETE_CONFLICT",
            detail={"document_ids": both},
        )

    # 삭제 — 항목 링크는 DB 의 CASCADE 가 함께 지운다 (§0.5.10 삭제 캐스케이드).
    for document_id in deleted_ids:
        session.delete(existing.pop(document_id))

    ordered: list[ProjectDocument] = []
    for index, entry in enumerate(payload, start=1):
        if entry.id is not None:
            document = existing[entry.id]
        else:
            document = ProjectDocument(project_id=project_id, sort_order=index)
            session.add(document)
        document.sort_order = index
        document.name = entry.name.strip()
        document.is_used = 1 if entry.is_used else 0
        document.link_url = entry.link_url
        document.doc_status = entry.doc_status
        ordered.append(document)

    session.flush()
    return ordered


def usage_count(session: Session, board, document_id: int) -> int:
    """이 문서를 쓰는 항목 수. 삭제 경고("N개 행에서 연결 해제")가 함께 보여 준다."""
    from sqlalchemy import func

    spec = board.spec
    link = spec.item_document_cls
    return int(
        session.scalar(
            select(func.count())
            .select_from(link)
            .where(getattr(link, spec.item_document_attr) == document_id)
        )
        or 0
    )
