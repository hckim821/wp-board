"""자체 `Base` — 호스트의 declarative base 와 섞지 않는다 (INTEGRATION.md §4).

호스트가 자기 `Base.metadata.create_all()` 을 돌려도 이 모듈의 테이블이 딸려
생성되지 않고, 반대로 이 모듈이 호스트 테이블을 건드릴 일도 없다.

테이블명은 전부 `wp_` 접두를 갖는다.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """이 모듈 전용 declarative base."""


class VersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ItemStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    HOLD = "HOLD"
    NA = "NA"


class ItemOrigin(str, enum.Enum):
    INHERITED = "INHERITED"
    ADDED = "ADDED"


class ProjectDocStatus(str, enum.Enum):
    """프로젝트별 문서 작성 상태 (plan.md §0.5-4).

    행 상태(`ItemStatus`)와 **일부러 다른 집합**이다. 문서에는 보류도 NA 도 없고,
    화면도 세 가지만 보여준다 (작성 전 / 작성중 / 완료).
    """

    NOT_WRITTEN = "NOT_WRITTEN"
    WRITING = "WRITING"
    DONE = "DONE"


def enum_column(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """DB 에 **값 문자열**이 저장되도록 강제한다.

    기본 동작은 파이썬 enum 의 *이름*을 쓰는데, 여기서는 이름과 값이 같아 사고가
    나지 않지만 명시해 두는 편이 schema.sql 과의 대응이 분명하다.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        validate_strings=True,
    )
