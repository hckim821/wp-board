"""두 계층이 공유하는 **보드(board)** 추상 — plan.md §0.1.

## 왜 이것이 있는가

템플릿 버전과 프로젝트는 저장 위치가 다를 뿐, 그리드 위에서 하는 일이 같다 —
재계산(§2.2), 경계 판정(§2.3), 회색 행(§0.2), 블록 내 드래그, 소속 변경.
§0 이 프로젝트 계층을 들이면서 선택지는 둘이었다.

1. `item_service` 를 통째로 복사해 `project_item_service` 를 만든다.
2. 스코프만 파라미터로 받는 **하나의** 구현을 둔다.

1번은 **두 벌이 조용히 갈라진다.** 이 저장소가 `schema.sql` / 마이그레이션 / ORM
을 테스트로 묶어 두는 이유와 같은 문제다. 재계산 규칙이 프로젝트에서만 틀리면
사용자는 "템플릿에서는 되는데" 라고 말하게 되고, 그때 고칠 곳이 두 곳이라는 사실을
먼저 발견해야 한다. 그래서 2번을 택했다.

## 무엇이 다르고 무엇이 같은가

| | 템플릿 | 프로젝트 |
|---|---|---|
| 행의 스코프 | `Item.version_id` | `ProjectItem.project_id` |
| 기준정보 스코프 | `Phase.template_id` | `ProjectPhase.project_id` |
| Owner 링크 대상 | `wp_owners` | `wp_project_owners` (로컬 사본) |
| 문서 링크 대상 | `wp_template_documents` | `wp_project_documents` (복제본) |
| `phase_start_no` | 발행 버전은 스냅샷, DRAFT 는 템플릿 값 | 프로젝트의 스냅샷 |
| 기준정보 `seq_no` 갱신 | DRAFT 일 때만 | 항상 (버전이 없으므로) |

`BoardSpec` 이 첫 두 열(어느 모델·어느 컬럼)을, `Board` 가 나머지(그 요청에서의
실제 스코프 값과 정책)를 담는다. `item_service` 는 이 둘만 보고 동작한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import (
    Item,
    ItemDocument,
    ItemOwner,
    Milestone,
    Owner,
    Phase,
    ProjectDocument,
    ProjectItem,
    ProjectItemDocument,
    ProjectItemOwner,
    ProjectMilestone,
    ProjectOwner,
    ProjectPhase,
    TemplateDocument,
)


@dataclass(frozen=True)
class BoardSpec:
    """어느 테이블 묶음을 쓰는가 — 계층마다 하나씩, 상수다."""

    #: 사람이 읽는 계층 이름. 오류 메시지에 쓴다 ("이 버전에 없는 …" vs "이 프로젝트에 …").
    scope_label: str
    item_cls: type
    item_document_cls: type
    item_owner_cls: type
    phase_cls: type
    milestone_cls: type
    owner_cls: type
    #: 문서 기준정보. §0.5.10 이전에는 전역 하나였고 스코프 밖이었다.
    document_cls: type
    #: 링크 행에서 문서를 가리키는 컬럼명 (`template_document_id` / `project_document_id`).
    item_document_attr: str
    #: 행에서 스코프를 가리키는 컬럼명 (`version_id` / `project_id`).
    item_scope_attr: str
    #: 기준정보에서 스코프를 가리키는 컬럼명 (`template_id` / `project_id`).
    master_scope_attr: str

    def item_scope(self) -> Any:
        return getattr(self.item_cls, self.item_scope_attr)

    def master_scope(self, model: type) -> Any:
        return getattr(model, self.master_scope_attr)


TEMPLATE_BOARD = BoardSpec(
    scope_label="버전",
    item_cls=Item,
    item_document_cls=ItemDocument,
    item_owner_cls=ItemOwner,
    phase_cls=Phase,
    milestone_cls=Milestone,
    owner_cls=Owner,
    document_cls=TemplateDocument,
    item_document_attr="template_document_id",
    item_scope_attr="version_id",
    master_scope_attr="template_id",
)

PROJECT_BOARD = BoardSpec(
    scope_label="프로젝트",
    item_cls=ProjectItem,
    item_document_cls=ProjectItemDocument,
    item_owner_cls=ProjectItemOwner,
    phase_cls=ProjectPhase,
    milestone_cls=ProjectMilestone,
    owner_cls=ProjectOwner,
    document_cls=ProjectDocument,
    item_document_attr="project_document_id",
    item_scope_attr="project_id",
    master_scope_attr="project_id",
)


@dataclass(frozen=True)
class Board:
    """한 요청이 다루는 **구체적인** 보드.

    `item_service` 의 모든 쓰기 연산이 이것을 받는다. `Version` 도 `Project` 도
    직접 알지 못하므로, 새 계층이 생겨도 서비스는 그대로다.
    """

    spec: BoardSpec
    #: 행이 매달린 대상의 id (`version.id` / `project.id`).
    scope_id: int
    #: 기준정보가 매달린 대상의 id (`template.id` / `project.id`).
    master_scope_id: int
    #: 표시 번호 시작값. 어디서 왔는지는 호출부가 정한다 (버전 스냅샷 / 프로젝트 스냅샷).
    phase_start_no: int
    #: 재계산 결과를 기준정보 `seq_no` 에 반영할 것인가.
    #: 템플릿은 DRAFT 일 때만 — PUBLISHED/ARCHIVED 를 **읽는 것만으로** 기준정보가
    #: 바뀌면 안 된다. 프로젝트는 편집 가능한 상태가 하나뿐이라 항상 참이다.
    sync_master_seq: bool

    @property
    def is_project(self) -> bool:
        return self.spec is PROJECT_BOARD
