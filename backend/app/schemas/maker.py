"""설비사 설정 스키마 — plan.md §0.6.

이 모듈에는 설비사를 **만들거나 이름을 고치는** 입력이 없다. 설비사 자체는
호스트 소유이고 (INTEGRATION.md §2), 우리가 쓰는 것은 표시 설정 하나뿐이다.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MakerProjectOut(BaseModel):
    """설정 화면이 설비사 밑에 펼쳐 보여주는 프로젝트 한 줄.

    **비활성 프로젝트도 들어온다.** 전체 현황(`project_service.overview`)은 활성만
    그리므로, 한 번 끈 프로젝트를 다시 켤 수 있는 화면이 하나는 있어야 한다.
    그 화면이 여기다 — `GET /projects` 의 기본값(활성만)을 쓰지 않는 이유이기도 하다.

    `is_active` 는 **표시 여부**이지 존재 여부가 아니다. 끈다고 행이 사라지지 않고,
    실제 삭제는 관리자가 `db/delete_project.py` 를 직접 실행할 때만 일어난다
    (README §관리자 도구).
    """

    id: int
    name: str
    is_active: bool


class MakerSummaryOut(BaseModel):
    """설정 화면의 한 줄.

    `show_in_overview` 와 `explicit` 를 **둘 다** 내려주는 것이 요점이다.

    * `show_in_overview` — §0.6-1 규칙을 적용한 **유효값**. 전체 현황이 실제로
      쓰는 값이며, 화면이 다시 계산하지 않는다.
    * `explicit` — 설정 행이 있는가. 거짓이면 그 유효값은 "프로젝트가 있어서
      켜진 것" 이라는 뜻이고, 프로젝트가 사라지면 저절로 꺼진다. 화면은 이 둘을
      구분해 보여줘야 사용자가 "왜 켜져 있는지" 를 알 수 있다.

    `name` 이 `null` 인 것은 **정상**이다 — resolver 미주입이거나 호스트가 모르는
    id 다. 폴백 문구(`설비사 #id`)는 화면이 만든다.
    """

    maker_id: int
    name: str | None = None
    show_in_overview: bool
    explicit: bool
    has_projects: bool
    #: 이 설비사의 프로젝트 — **활성·비활성 전부**. 설정 화면이 설비사 행 아래에
    #: 펼쳐 스위치를 그린다. `has_projects` 와 겹쳐 보이지만 다른 질문의 답이다:
    #: `has_projects` 는 "활성 프로젝트가 있는가"(자동 표시 규칙의 입력)이고,
    #: 이쪽은 "무엇을 켜고 끌 수 있는가" 다.
    projects: list[MakerProjectOut] = Field(default_factory=list)


class MakersOut(BaseModel):
    makers: list[MakerSummaryOut] = Field(default_factory=list)


class MakerSettingSaveIn(BaseModel):
    maker_id: int
    show_in_overview: bool


class MakerProjectVisibilityIn(BaseModel):
    """프로젝트 표시 on/off 한 줄. `id` 는 `wp_projects.id` 다.

    `PUT /projects/{id}` 로도 같은 컬럼을 쓸 수 있지만 그쪽은 한 건씩 커밋한다.
    설정 화면은 설비사 체크와 프로젝트 스위치를 **한 번의 저장**으로 넘기므로,
    둘이 한 트랜잭션에 들어가야 절반만 반영되는 상태가 생기지 않는다.
    """

    id: int
    is_active: bool


class MakerSettingsSaveIn(BaseModel):
    """**부분 목록을 보내도 된다.** 목록에 없는 설비사는 손대지 않는다.

    설비사 목록의 정본은 호스트이지 이 요청이 아니다. "목록에 없으면 삭제" 로
    두면, 화면이 목록을 받은 뒤 호스트에 설비사가 하나 추가되는 것만으로 그
    설비사의 설정이 저장 때마다 날아간다.

    `projects` 도 같은 규칙이다 — 보낸 것만 바뀐다. 빈 배열은 "프로젝트는 건드리지
    말라" 이지 "전부 끄라" 가 아니다.
    """

    settings: list[MakerSettingSaveIn] = Field(default_factory=list)
    projects: list[MakerProjectVisibilityIn] = Field(default_factory=list)
