"""설비사(Maker) 포트 — INTEGRATION.md §2.2.

설비사 테이블은 **호스트 프로젝트 소유**다. 이 모듈은 설비사 테이블을 만들지도,
그쪽으로 JOIN 하지도 않는다. 쿼리는 `maker_id` 값까지만 다루고, 이름 같은 부가
정보가 필요하면 이 포트로 호스트에 위임한다.

핵심 계약 세 가지

1. **미주입이 정상 상태다.** resolver 가 없으면 API 는 `maker_id` 만 반환하고
   `maker_name` 을 생략하며, `list_makers()` 는 빈 목록으로 간주한다. 예외를
   던지지 않는다.
2. **고아 참조가 조회를 깨뜨리지 않는다.** `maker_id` 가 호스트에 없으면 이름을
   비우고 넘어간다. 물리 FK 가 없으므로 정합성은 호스트 책임이다.
3. `exists()` 검증은 resolver 가 주입된 경우에만 수행한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MakerResolver(Protocol):
    """호스트가 구현해 주입하는 설비사 조회 포트."""

    def resolve(self, maker_ids: list[int]) -> dict[int, str]:
        """`maker_id` → 표시 이름. **찾지 못한 id 는 결과에서 빠진다** (예외 아님)."""
        ...

    def exists(self, maker_id: int) -> bool:
        """생성/수정 시 참조 검증용."""
        ...

    def list_makers(self) -> list[tuple[int, str]]:
        """설비사 **전체** 목록 `(id, 표시 이름)` — 설정 화면과 전체 현황용
        (plan.md §0.6-2, INTEGRATION.md §2.2).

        `resolve()` 로는 대신할 수 없다. 그쪽은 이미 아는 id 의 이름을 채우는
        것이고, 이쪽은 **아직 프로젝트가 하나도 없는 설비사까지** 알아야 한다 —
        설정 화면에서 체크해 두면 프로젝트 0개인 설비사도 전체 현황에 섹션이
        나와야 하기 때문이다.

        표시 이름은 **호스트가 정한다** (예: `maker_ko or maker`). 이 모듈은
        호스트 스키마를 모른다.
        """
        ...


def resolve_names(resolver: MakerResolver | None, maker_ids: list[int]) -> dict[int, str]:
    """resolver 미주입·조회 실패를 모두 흡수하는 안전한 래퍼.

    호스트 구현이 예외를 던지더라도 **보드 조회는 성공해야 한다**. 설비사 이름은
    부가 정보이지 이 모듈의 정합성 요건이 아니다.
    """
    if resolver is None or not maker_ids:
        return {}
    try:
        return resolver.resolve(sorted(set(maker_ids)))
    except Exception:  # noqa: BLE001 — 호스트 구현 장애가 조회를 깨뜨리지 않게 한다
        return {}


def maker_exists(resolver: MakerResolver | None, maker_id: int) -> bool:
    """resolver 가 없으면 **검증하지 않는다** (= 통과)."""
    if resolver is None:
        return True
    return bool(resolver.exists(maker_id))


def list_makers(resolver: MakerResolver | None) -> list[tuple[int, str]]:
    """`(id, 이름)` 전체 목록. 못 얻으면 **빈 목록**이다 — 예외를 던지지 않는다.

    흡수하는 경우가 셋이다.

    1. **resolver 미주입** — 정상 상태다 (§2.2). 설정 화면은 빈 표에 안내 문구를
       띄우고, 전체 현황은 프로젝트가 실제로 가진 `maker_id` 로 폴백한다.
    2. **`list_makers` 가 없는 구현** — 이 메서드는 §0.6 에서 **뒤늦게** 포트에
       추가됐다. 그 전에 두 메서드짜리 Protocol 에 맞춰 구현한 호스트가 그대로
       살아 있을 수 있고, 그런 호스트에서 설정 화면이 `AttributeError` 로 500 을
       내는 것은 이 모듈이 감수할 위험이 아니다. `getattr` 로 확인하고 없으면
       빈 목록으로 취급한다 — **기존 기능(보드·프로젝트)은 전혀 영향받지 않고**
       새 화면만 "설비사 목록을 제공하지 않는 호스트" 로 동작한다.
    3. **호스트 구현이 예외를 던짐** — `resolve_names` 와 같은 이유로 흡수한다.

    반환값은 `(id, name)` 쌍의 리스트다. 호스트가 그 형태가 아닌 것을 돌려주면
    조용히 통과시키지 않고 빈 목록으로 떨어뜨린다 — 절반만 해석된 목록이
    화면에 나오는 것보다 "목록 없음" 이 낫다.
    """
    if resolver is None:
        return []

    method = getattr(resolver, "list_makers", None)
    if not callable(method):
        return []

    try:
        rows = method()
    except Exception:  # noqa: BLE001 — 호스트 구현 장애가 화면을 깨뜨리지 않게 한다
        return []

    makers: list[tuple[int, str]] = []
    try:
        for row in rows:
            maker_id, name = row
            makers.append((int(maker_id), str(name)))
    except (TypeError, ValueError):
        return []
    return makers
