"""프로젝트 주요 링크 — plan.md §0.5.5.

Confluence 페이지·클라우드 파일처럼 프로젝트가 자유롭게 늘리고 줄이는 외부 링크
목록이다. `project_document_service`(§0.5-4) 와 이름이 비슷하지만 성격이 반대다.

| | 문서 설정 (§0.5-4) | 주요 링크 (§0.5.5) |
|---|---|---|
| 목록의 정본 | 전역 문서 마스터 | **이 화면** |
| 행이 없을 때 | 기본값으로 읽힌다 | 없는 것이다 |
| 저장 | 부분 업서트 | **전량 교체** |

전량 교체인 이유: 화면이 들고 있는 목록이 전부이고, 행 삭제도 같은 저장으로
표현돼야 한다. 부분 업서트로 두면 "지우기" 에 별도 엔드포인트가 필요해지고,
드래그 재정렬과 삭제가 한 번의 저장에 섞이는 이 화면에서는 그 둘을 두 요청으로
쪼개는 순간 중간 상태가 저장될 수 있다.

## 검증은 전부 먼저

URL·설명·스코프를 **모두 확인한 뒤에** 쓴다. 그래서 422 가 나면 아무것도 바뀌지
않는다. 오류에는 `index`/`row_no`/`field` 를 실어 그리드가 문제의 셀을 짚을 수
있게 한다 (`validation_service` 의 V1~V14 와 같은 규약).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.exceptions import UnprocessableEntityError
from ..models import ProjectLink
from ..schemas.project import ProjectLinkSaveIn

#: 인터넷 주소만 허용한다 (plan.md §0.5.5). `file://` 이나 상대 경로를 넣으면
#: 화면의 연결 아이콘이 `window.open` 으로 열 때 아무 일도 일어나지 않거나
#: 호스트 페이지를 벗어난 곳으로 튄다.
ALLOWED_SCHEMES = ("http://", "https://")


def list_links(session: Session, project_id: int) -> list[ProjectLink]:
    return list(
        session.scalars(
            select(ProjectLink)
            .where(ProjectLink.project_id == project_id)
            .order_by(ProjectLink.sort_order, ProjectLink.id)
        )
    )


def _reject(message: str, *, code: str, index: int, field: str, **extra):
    raise UnprocessableEntityError(
        message,
        code=code,
        # `index` 는 0-based 배열 위치, `row_no` 는 화면의 1-based 행 번호다.
        # 그리드는 후자를 쓰고, 클라이언트 배열을 직접 만지는 코드는 전자를 쓴다.
        detail={"index": index, "row_no": index + 1, "field": field, **extra},
    )


def _clean(payload: list[ProjectLinkSaveIn]) -> list[tuple[str, str]]:
    """설명·URL 을 다듬고 검증한다. 통과하면 `(description, url)` 목록."""
    cleaned: list[tuple[str, str]] = []
    for index, entry in enumerate(payload):
        description = (entry.description or "").strip()
        if not description:
            _reject(
                f"{index + 1}행: 설명을 입력하세요.",
                code="LINK_DESCRIPTION_REQUIRED",
                index=index,
                field="description",
            )

        url = (entry.url or "").strip()
        lowered = url.lower()
        if not lowered.startswith(ALLOWED_SCHEMES):
            _reject(
                f"{index + 1}행: 링크는 http:// 또는 https:// 로 시작하는 "
                "인터넷 주소여야 합니다.",
                code="LINK_URL_INVALID",
                index=index,
                field="url",
                url=url,
            )
        # 스킴만 있고 주소가 없는 값(`https://`)도 형식상 접두는 만족한다.
        # 통과시키면 클릭했을 때 아무 데도 가지 않는 링크가 저장된다.
        scheme = next(s for s in ALLOWED_SCHEMES if lowered.startswith(s))
        if not url[len(scheme) :].strip():
            _reject(
                f"{index + 1}행: 링크에 주소가 없습니다.",
                code="LINK_URL_INVALID",
                index=index,
                field="url",
                url=url,
            )

        cleaned.append((description, url))
    return cleaned


def replace_links(
    session: Session, project_id: int, payload: list[ProjectLinkSaveIn]
) -> list[ProjectLink]:
    """**전량 교체.** 배열 순서가 곧 `sort_order` 이고, 빠진 기존 링크는 삭제된다.

    `sort_order` 를 요청에서 받지 않고 여기서 다시 매기는 것이 핵심이다 —
    순서의 정본을 배열 위치 하나로 못박으면 낡은 번호가 직전 재정렬을 되돌리는
    사고가 원천적으로 없다.
    """
    cleaned = _clean(payload)

    existing = {link.id: link for link in list_links(session, project_id)}

    referenced: list[int] = [e.id for e in payload if e.id is not None]
    duplicated = sorted({i for i in referenced if referenced.count(i) > 1})
    if duplicated:
        raise UnprocessableEntityError(
            f"같은 링크가 두 번 들어 있습니다: {duplicated}",
            code="LINK_DUPLICATED",
            detail={"link_ids": duplicated},
        )

    # 스코프 검증. 남의 프로젝트 링크 id 는 "이 프로젝트에 없는 id" 와 같으므로
    # 존재 여부를 따로 묻지 않는다 — 어느 쪽이든 여기서 걸린다.
    for index, entry in enumerate(payload):
        if entry.id is not None and entry.id not in existing:
            _reject(
                f"{index + 1}행: 이 프로젝트의 링크가 아닙니다 (id={entry.id}).",
                code="LINK_OUT_OF_SCOPE",
                index=index,
                field="id",
                link_id=entry.id,
            )

    keep = set(referenced)
    for link_id, link in existing.items():
        if link_id not in keep:
            session.delete(link)

    ordered: list[ProjectLink] = []
    for index, (entry, (description, url)) in enumerate(zip(payload, cleaned), start=1):
        if entry.id is not None:
            link = existing[entry.id]
        else:
            link = ProjectLink(project_id=project_id, sort_order=index)
            session.add(link)
        link.sort_order = index
        link.description = description
        link.url = url
        ordered.append(link)

    session.flush()
    return ordered
