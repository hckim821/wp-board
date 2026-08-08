from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models.base import ItemStatus, ProjectDocStatus
from .item import ItemOut


class ProjectOut(BaseModel):
    """`maker_name` 이 없는 응답은 **정상**이다.

    `MakerResolver` 가 주입되지 않았거나, 호스트에 그 `maker_id` 가 없을 때
    이름만 생략하고 나머지는 그대로 내려간다 (INTEGRATION.md §2.2).
    설비사 테이블로 JOIN 하지 않으므로 고아 참조가 조회를 깨뜨리지 않는다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    maker_id: int
    maker_name: str | None = None
    name: str
    description: str | None = None
    #: 복제 원본. 프로젝트는 스냅샷이라 원본이 바뀌어도 따라가지 않는다.
    source_template_id: int | None = None
    source_version_id: int | None = None
    #: 원본 버전의 표시 번호 (`wp_versions.version_number`). Work Package 헤더가
    #: "어느 포맷의 몇 버전에서 왔는지" 를 보여준다.
    #:
    #: **`null` 이 정상 상태다.** `source_version_id` 에는 물리 FK 가 없어
    #: (`models/project.py` — 원본이 지워져도 출처 이력은 남긴다) 고아 참조가
    #: 생길 수 있고, 그때 조회가 깨지면 안 된다. 설비사 이름과 같은 규칙이다.
    source_version_number: int | None = None
    phase_start_no: int = 0
    is_active: bool = True
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectCreateIn(BaseModel):
    """생성 = 발행된 템플릿 버전 하나를 골라 deep copy (plan.md §0.1).

    `template_id` 를 주면 그 템플릿의 **현재 발행본**을, `template_version_id` 를
    주면 그 버전을 복제한다. 둘 다 주면 서로 맞는지 확인한다.
    """

    maker_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    template_id: int | None = None
    template_version_id: int | None = None
    created_by: str | None = None

    @model_validator(mode="after")
    def _needs_a_source(self):
        if self.template_id is None and self.template_version_id is None:
            raise ValueError("template_id 또는 template_version_id 중 하나는 필요합니다.")
        return self


class ProjectUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    phase_start_no: int | None = None
    is_active: bool | None = None


class ProjectRenameIn(BaseModel):
    """이름만 고치는 좁은 입력 (plan.md §0.6-3, 전체 현황의 인라인 수정).

    `min_length=1` 만으로는 부족하다 — `"   "` 는 길이 검사를 통과하고 저장되면
    화면에서 이름 없는 프로젝트가 된다. 앞뒤 공백을 떼고 나서 비면 422 다.
    """

    name: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _not_blank(self):
        stripped = self.name.strip()
        if not stripped:
            raise ValueError("프로젝트명은 공백일 수 없습니다.")
        self.name = stripped
        return self


class ProjectDetailOut(BaseModel):
    """그리드 로드용 — 프로젝트 + 재계산된 전체 행.

    `version` 필드가 없다. 프로젝트에는 버전 개념이 없다 (plan.md §0.1).
    """

    project: ProjectOut
    items: list[ItemOut] = Field(default_factory=list)


# =============================================================================
# 프로젝트별 문서 링크·상태 (plan.md §0.5-4)
# =============================================================================
class ProjectDocumentOut(BaseModel):
    """프로젝트 문서 한 줄 (plan.md §0.5.10 개편).

    `no` 는 **파생된 표시 번호**다 (§0.5.10 팝업 정밀화) — 저장된 `sort_order` 가
    아니라 **사용 중인 문서만 세어** 매긴 1..N 이며, 꺼진 문서는 `null` 이다.
    등록 탭은 꺼진 문서도 보여줘야 하므로(체크를 다시 켜야 하니까) 이 목록에는
    남아 있고 번호만 비는 것이 옳다.

    `id` 는 프로젝트 로컬 문서의 id 다 (전역 `document_type_id` 는 폐기).
    """

    id: int
    no: int | None = None
    name: str
    is_used: bool = True
    link_url: str | None = None
    doc_status: ProjectDocStatus = ProjectDocStatus.NOT_WRITTEN


class ProjectDocumentListOut(BaseModel):
    documents: list[ProjectDocumentOut] = Field(default_factory=list)
    #: 삭제 캐스케이드로 항목 링크가 바뀌므로 **재계산된 행 목록**을 함께 준다
    #: (§0.5.10). 저장 뒤 그리드가 따로 다시 읽지 않아도 되게 하려는 것이다.
    items: list[ItemOut] = Field(default_factory=list)


class ProjectDocumentSaveIn(BaseModel):
    """`id` 가 `null` 이면 신규. **`no` 를 받지 않는다** — 배열 위치가 정본이다."""

    id: int | None = None
    name: str = Field(max_length=200)
    is_used: bool = True
    link_url: str | None = Field(default=None, max_length=500)
    doc_status: ProjectDocStatus = ProjectDocStatus.NOT_WRITTEN


class ProjectDocumentsSaveIn(BaseModel):
    """**전량 교체.** 배열 순서 = `sort_order`, `deleted_ids` 로 명시 삭제.

    §0.5.10 이전에는 부분 업서트였다 — 목록의 정본이 전역 마스터였기 때문이다.
    이제 문서를 프로젝트가 소유하므로 화면이 들고 있는 것이 전부이고, 삭제도 같은
    저장으로 표현된다.
    """

    documents: list[ProjectDocumentSaveIn] = Field(default_factory=list)
    deleted_ids: list[int] = Field(default_factory=list)


# =============================================================================
# 프로젝트 주요 링크 (plan.md §0.5.5)
# =============================================================================
class ProjectLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    url: str
    sort_order: int


class ProjectLinkListOut(BaseModel):
    links: list[ProjectLinkOut] = Field(default_factory=list)


class ProjectLinkSaveIn(BaseModel):
    """저장 목록의 한 줄. `id` 가 `null` 이면 신규다.

    **`sort_order` 를 받지 않는다.** 순서의 정본은 배열 위치이고 서버가 다시
    매긴다. 둘 다 받으면 어느 쪽이 이기는지가 애매해지고, 낡은 번호가 조용히
    직전 재정렬을 되돌린다.
    """

    id: int | None = None
    description: str = Field(max_length=200)
    url: str = Field(max_length=1000)


class ProjectLinksSaveIn(BaseModel):
    """**전량 교체.** 목록에서 빠진 기존 링크는 삭제된다.

    재정렬·수정·추가·삭제가 한 번의 저장에 섞여 들어오는 것이 이 화면의 정상
    사용이라, 삭제를 별도 엔드포인트로 쪼개면 중간 상태가 저장될 수 있다.
    """

    links: list[ProjectLinkSaveIn] = Field(default_factory=list)


# =============================================================================
# 전체 현황 (plan.md §0.5-3) — 설비사·프로젝트를 한 화면에 모으는 읽기 전용 뷰
# =============================================================================
class StatusCounts(BaseModel):
    """상태별 항목 수. **다섯 키가 항상 모두 나온다** (0 이어도 생략하지 않는다).

    집계 칩이 "완료 0" 을 그리려면 키의 부재와 값 0 을 구분할 수 없어야 한다.
    """

    NOT_STARTED: int = 0
    IN_PROGRESS: int = 0
    DONE: int = 0
    HOLD: int = 0
    NA: int = 0


class OverviewItemOut(BaseModel):
    """미니맵의 셀 하나. 그리드용 `ItemOut` 과 **여전히 다른 축약형**이다.

    셀을 칠하고(`status`) 밴딩하고(`phase_seq`) 팝오버를 띄우는 데 필요한 것만
    담는다. 문서·Owner id·경계 플래그·완료일 같은 그리드 전용 필드는 빠져 있다 —
    미니맵은 프로젝트 수 × 항목 수만큼 셀을 그리므로 `ItemOut` 을 그대로 실으면
    응답이 몇 배가 된다.

    `title` / `deliverable` / `owners` 는 **hover 팝오버 때문에** 들어왔다
    (plan.md §0.5-3 개편). 전체 현황의 팝오버가 프로젝트 대시보드의 카드와 같은
    포맷(담당 · 상태 · action item · deliverable)이어야 하는데, 그 넷 중 셋이
    여기 없었다. 셀을 눌러 프로젝트를 열어야 볼 수 있게 하는 것은 "한 화면에서
    관망한다" 는 이 화면의 목적과 어긋난다.

    `owners` 는 **id 가 아니라 이름 배열**이다. 팝오버는 이름만 쓰고, Owner id 는
    프로젝트 로컬 사본의 id 라 이 화면에서 아무 데도 쓸 수 없다 — 내려보내면
    클라이언트가 그것으로 무언가 조회할 수 있다는 잘못된 인상만 준다.

    `phase_seq` / `milestone_seq` 는 저장된 값이 아니라 **행 순서에서 파생한
    표시 번호**다 (plan.md §2.1/§2.2 — 그리드와 같은 재계산기를 쓴다).
    미배정(회색) 행은 둘 다 `null` 이고, 미니맵에서 무색 밴드로 그려진다.
    """

    no: int
    status: ItemStatus
    phase_seq: int | None = None
    milestone_seq: int | None = None
    dash_label: str | None = None
    #: 카드 표시 폴백(`dash_label` → `deliverable` → `title` 앞부분)은 **화면이**
    #: 적용한다. 서버는 셋을 있는 그대로 내려보낸다 — 서버가 미리 채우면
    #: "라벨이 비어 있다" 는 사실이 응답에서 사라진다 (§0.5-1 과 같은 이유).
    title: str | None = None
    deliverable: str | None = None
    owners: list[str] = Field(default_factory=list)


class OverviewDocumentOut(BaseModel):
    """전체 현황 행의 ④ 문서 링크 구획 (plan.md §0.5-3b).

    `is_used` 를 싣지 않는다 — **사용 체크된 것만** 배열에 담기므로 항상 참이고,
    실어 두면 클라이언트가 다시 거를 수 있다는 인상을 준다.

    `no` 는 **파생된 표시 번호**다. 이 배열은 사용 중인 문서만 담으므로 언제나
    1..N 연속이고 `null` 이 없다. 원문자 코드는 §0.5.10 에서 폐기됐다.
    """

    id: int
    no: int
    name: str
    doc_status: ProjectDocStatus = ProjectDocStatus.NOT_WRITTEN
    link_url: str | None = None


class OverviewProjectOut(BaseModel):
    """`maker_name` 이 `null` 인 것은 **정상**이다 (INTEGRATION.md §2.2).

    설비사 테이블로 JOIN 하지 않으므로 resolver 미주입·고아 참조 어느 쪽도
    이 화면을 깨뜨리지 않는다 — 이름만 빠지고 나머지는 그대로 나온다.
    """

    id: int
    name: str
    maker_id: int
    maker_name: str | None = None
    counts: StatusCounts
    items: list[OverviewItemOut] = Field(default_factory=list)
    #: **사용(`is_used=1`) 중인 문서만.** 저장된 행이 없는 프로젝트는 기본값이
    #: 사용=1 이므로 활성 전역 문서가 전부 들어온다 (§0.5-4 의 lazy 규칙).
    documents: list[OverviewDocumentOut] = Field(default_factory=list)


class OverviewMakerOut(BaseModel):
    """전체 현황의 **설비사 섹션** (plan.md §0.6-3).

    최상위가 프로젝트 배열이 아니라 이것인 이유: 화면이 설비사별 구획이고
    (§0.5-3 개정), **표시 여부 규칙(§0.6-1)이 설비사 단위**라서 그 판단이 서버에
    있어야 하기 때문이다. 프로젝트를 평평하게 내려주면 클라이언트가 그룹핑과
    표시 규칙을 다시 구현하게 되고, 설정 화면과 갈리는 순간 "체크했는데 안
    나온다" 가 된다.

    **`projects` 가 빈 섹션이 나올 수 있다** — 설정에서 체크해 둔 설비사는
    프로젝트가 0개여도 섹션이 나온다 (그래야 거기에 프로젝트를 추가할 수 있다).
    """

    maker_id: int
    #: `null` 이 정상. 폴백 문구(`설비사 #id`)는 화면이 만든다.
    name: str | None = None
    projects: list[OverviewProjectOut] = Field(default_factory=list)


class ProjectsOverviewOut(BaseModel):
    """최상위가 `makers` 다 (§0.6-3 개편).

    이전 판은 `projects` 평면 배열이었다. 설비사 섹션·표시 규칙·빈 섹션이
    들어오면서 그룹핑을 서버가 하게 됐고, 그에 맞춰 계약을 바꿨다.
    """

    makers: list[OverviewMakerOut] = Field(default_factory=list)
