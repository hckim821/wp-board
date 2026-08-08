"""설비사(Maker) 관련 — **우리가 소유하는 것은 설정뿐이다.**

설비사 자체는 호스트 프로젝트의 테이블이다 (INTEGRATION.md §2). 이 모듈에는
`Maker` 모델이 없고 앞으로도 없어야 한다 — 이름이 필요하면 `MakerResolver` 포트로
호스트에 위임한다.

여기 있는 것은 호스트 테이블에 **넣을 수 없는** 우리 쪽 부가 상태 하나다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MakerSetting(Base):
    """설비사별 표시 설정 (plan.md §0.6-1).

    `maker_id` 는 호스트 설비사 테이블의 PK 를 가리키는 **논리적 참조**다.
    `wp_projects.maker_id` 와 같은 규칙으로 **물리 FK 가 없다** — 대상 테이블이
    다른 스키마에 있을 수 있어 제약을 걸면 이식 DDL 이 실패한다. UNIQUE 는
    참조 무결성이 아니라 "설비사 하나에 설정 하나" 를 지키기 위한 것이다.

    **행이 없는 것이 정상 상태다.** 없으면 "active 프로젝트가 있으면 표시" 로
    읽는다 (`maker_service.effective_visibility`). 설치 직후 설정을 한 번도
    만지지 않아도 전체 현황이 비지 않게 하려는 것이고, 그러면서 체크 한 번으로
    강제 표시·강제 숨김 양쪽이 가능해진다.
    """

    __tablename__ = "wp_maker_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    maker_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    show_in_overview: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
