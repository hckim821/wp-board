"""버전 조회 / 임시저장 / 검증 / 발행 / 폐기 API.

쓰기 경로는 전부 `lock_editable_version()` 을 먼저 통과해야 한다 — 버전 행을
잠근 뒤 상태를 다시 읽는다. 잠금 없이 상태만 확인하면 검사와 쓰기 사이에 다른
요청이 발행/폐기를 끝낼 수 있다 (plan.md §2.4 "상태 검사는 잠금 하에서").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ...core.exceptions import WpAPIRoute
from ...deps import WpDeps
from ...schemas.document import DocumentApplyIn, TemplateDocumentListOut, TemplateDocumentOut
from ...schemas.item import ItemListOut, ItemsSaveIn
from ...schemas.validation import ValidationResultOut
from ...schemas.version import PublishIn, VersionDetailOut, VersionOut
from ...services import (
    board_xlsx_service,
    item_service,
    template_document_service,
    version_service,
)
from .downloads import XLSX_MEDIA_TYPE, attachment


def _version_out(version) -> VersionOut:
    out = VersionOut.model_validate(version)
    out.is_editable = version.is_editable
    return out


def build_router(deps: WpDeps) -> APIRouter:
    router = APIRouter(route_class=WpAPIRoute, tags=["versions"])
    session_dep = Depends(deps.session)

    @router.get("/versions/{version_id}", response_model=VersionDetailOut)
    def get_version(version_id: int, session: Session = session_dep):
        """그리드 로드용 — 버전 + 재계산된 전체 행.

        번호와 경계 플래그는 **이 버전의 행 순서**에서 파생한다. 조회는 아무것도
        저장하지 않으므로 PUBLISHED 를 열어봐도 데이터가 바뀌지 않는다.
        """
        version = version_service.get_version(session, version_id)
        board = version_service.board_of(session, version)
        items = item_service.load_ordered_items(session, board)
        return VersionDetailOut(
            version=_version_out(version),
            items=item_service.build_item_views(
                session, board, items
            ),
        )

    @router.get(
        "/versions/{version_id}/board.xlsx",
        response_class=Response,
        responses={200: {"content": {XLSX_MEDIA_TYPE: {}}, "description": "원본 양식 XLSX"}},
    )
    def export_board_xlsx(version_id: int, session: Session = session_dep):
        """보드를 **`docs/Work Package.xlsx` 원본 양식**으로 내보낸다 (§0.5.7).

        **읽기 연산이다.** PUBLISHED/ARCHIVED 도 내보낼 수 있다 — 불변 규칙은
        쓰기를 막는 것이지 읽기를 막는 것이 아니다.
        """
        name, payload = board_xlsx_service.version_board_xlsx(
            session, version_id
        )
        return Response(
            content=payload,
            media_type=XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": attachment(f"{name}.xlsx")},
        )

    # =========================================================================
    # 템플릿 문서 (plan.md §0.5.10) — Phase/Milestone 관리 팝업과 같은 형태
    # =========================================================================
    def _documents_out(session: Session, template_id: int, version_id: int):
        board = version_service.board_of(
            session, version_service.get_version(session, version_id)
        )
        return TemplateDocumentListOut(
            documents=[
                TemplateDocumentOut(id=d.id, no=d.sort_order, name=d.name,
                                    is_active=bool(d.is_active))
                for d in template_document_service.list_documents(session, template_id)
                if d.is_active
            ],
            items=item_service.build_item_views(
                session, board, item_service.load_ordered_items(session, board)
            ),
        )

    @router.get("/versions/{version_id}/documents", response_model=TemplateDocumentListOut)
    def list_documents(version_id: int, session: Session = session_dep):
        """이 버전이 속한 **템플릿**의 문서 (`sort_order` 순).

        문서는 Phase/Milestone 과 같이 버전이 아니라 템플릿에 매인다 — 그래서
        같은 템플릿의 두 버전은 같은 문서를 본다.
        """
        version = version_service.get_version(session, version_id)
        return _documents_out(session, version.template_id, version_id)

    @router.post("/versions/{version_id}/documents/apply",
                 response_model=TemplateDocumentListOut)
    def apply_documents(
        version_id: int, payload: DocumentApplyIn, session: Session = session_dep
    ):
        """팝업 표의 최종 상태를 통째로 적용한다 — **원자적** (`phases/apply` 동형).

        DRAFT 에서만 가능하다. 삭제는 조건부다 — 다른 버전이 그 문서를 쓰고 있으면
        하드 삭제 대신 비활성화한다 (§0.4 정밀화 1과 같은 판단).
        """
        version = version_service.lock_editable_version(session, version_id)
        template_document_service.apply_documents(
            session, version.template_id, version_id, payload.documents, payload.deleted_ids
        )
        session.commit()
        return _documents_out(session, version.template_id, version_id)

    @router.put("/versions/{version_id}/items", response_model=VersionDetailOut)
    def save_items(version_id: int, payload: ItemsSaveIn, session: Session = session_dep):
        """임시저장 — 전량 교체, **검증 없음**.

        필수값 누락도 Phase 미지정도 그대로 저장한다. 참조 무결성(존재하지 않는
        phase_id 등)만 400 으로 막는다 (plan.md §2.5).
        """
        version = version_service.lock_editable_version(session, version_id)
        board = version_service.board_of(session, version)
        item_service.bulk_replace(
            session, board, payload.items
        )
        session.commit()

        items = item_service.load_ordered_items(session, board)
        return VersionDetailOut(
            version=_version_out(version),
            items=item_service.build_item_views(
                session, board, items
            ),
        )

    @router.post(
        "/versions/{version_id}/validate",
        response_model=ValidationResultOut,
        response_model_exclude_none=True,
    )
    def validate_version(version_id: int, session: Session = session_dep):
        """검증만 수행 (발행 전 미리보기). 상태를 바꾸지 않는다."""
        version = version_service.get_version(session, version_id)
        result = version_service.validate_version(
            session, version
        )
        return ValidationResultOut.model_validate(result)

    @router.post("/versions/{version_id}/publish", response_model=VersionDetailOut)
    def publish_version(
        version_id: int, payload: PublishIn | None = None, session: Session = session_dep
    ):
        """발행 — 검증 통과 시 상태 전이.

        실패하면 422 와 함께 `detail` 에 §2.5 형식의 errors/warnings 가 담긴다.
        커밋하지 않으므로 상태도 데이터도 그대로다.
        """
        payload = payload or PublishIn()
        version = version_service.publish(
            session,
            version_id,
            published_by=payload.published_by,
            notes=payload.notes,
        )
        session.commit()

        session.refresh(version)
        board = version_service.board_of(session, version)
        items = item_service.load_ordered_items(session, board)
        return VersionDetailOut(
            version=_version_out(version),
            items=item_service.build_item_views(
                session, board, items
            ),
        )

    @router.delete("/versions/{version_id}", status_code=204)
    def discard_version(version_id: int, session: Session = session_dep):
        """DRAFT 폐기. PUBLISHED/ARCHIVED 는 409."""
        version_service.discard(session, version_id)
        session.commit()

    return router
