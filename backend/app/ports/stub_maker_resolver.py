"""[DEV ONLY] `wp_dev_makers` 를 읽는 스텁 resolver.

**이 파일은 `wp_dev_makers` 테이블을 참조하는 유일한 코드여야 한다**
(INTEGRATION.md §2.3). 이식 시 `db/dev_seed.sql` 과 함께 삭제 대상이다.

운영에서는 호스트가 자기 설비사 테이블을 읽는 `MakerResolver` 구현체를
`create_wp_router(maker_resolver=...)` 로 주입한다.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


class StubMakerResolver:
    """개발용. 실제 호스트 테이블 대신 `wp_dev_makers` 를 조회한다."""

    def __init__(self, session_factory: Callable[[], Session]):
        self._session_factory = session_factory

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        if not maker_ids:
            return {}
        with self._session_factory() as session:
            stmt = text("SELECT id, name FROM `wp_dev_makers` WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            rows = session.execute(stmt, {"ids": list(maker_ids)}).all()
        return {int(r[0]): r[1] for r in rows}

    def exists(self, maker_id: int) -> bool:
        with self._session_factory() as session:
            found = session.execute(
                text("SELECT 1 FROM `wp_dev_makers` WHERE id = :id"), {"id": maker_id}
            ).first()
        return found is not None

    def list_makers(self) -> list[tuple[int, str]]:
        """설비사 전체 (plan.md §0.6-2). 운영에서는 호스트가 `makers` 를 읽어
        `maker_ko or maker` 같은 표시명을 만들어 돌려준다.

        비활성 설비사는 뺀다 — 설정 화면에 지금 쓰지 않는 설비사가 나올 이유가 없다.
        """
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    "SELECT id, name FROM `wp_dev_makers` "
                    "WHERE is_active = 1 ORDER BY name, id"
                )
            ).all()
        return [(int(r[0]), r[1]) for r in rows]
