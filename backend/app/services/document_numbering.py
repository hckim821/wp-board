"""문서 표시 번호 — plan.md §0.5.10 (팝업 정밀화).

**표시 번호는 저장값이 아니라 파생값이다.** `sort_order` 는 사용자가 드래그로 정한
저장 순서이고, 화면에 보이는 번호는 그 순서를 훑으며 **세는 대상에만** 1..N 을
붙인 결과다.

| 계층 | 세는 대상 | 꺼진 문서 |
|---|---|---|
| 템플릿 | 전부 | (해당 없음 — `is_used` 가 없다) |
| 프로젝트 | **`is_used` 인 것만** | `no = None` |

## 왜 사용 문서에만 번호를 주는가

프로젝트에서 문서를 끄면 그 문서는 그리드 셀·전체 현황·내보내기 어디에도 나오지
않는다. 그런데 번호는 계속 차지하고 있으면 사용자에게 보이는 목록이 `1, 3, 4` 처럼
구멍 난 채로 읽힌다 — 없는 2번을 찾게 된다. 세는 대상을 사용 문서로 좁히면 보이는
번호가 항상 촘촘하다.

Phase/Milestone 의 표시 번호가 **행 순서에서 파생**되는 것과 같은 태도다 (§2.2):
저장된 `seq_no` 를 그대로 쓰지 않고, 그 화면에서 실제로 보이는 것만 세어 매긴다.

## 계층을 구분하지 않는 이유

`is_used` 가 없는 모델(`TemplateDocument`)은 `getattr` 기본값 1 로 **전부 세어진다.**
그래서 호출부가 계층을 알 필요가 없고, 두 계층에 규칙이 두 벌 생기지 않는다.
"""

from __future__ import annotations


def display_numbers(documents) -> dict[int, int | None]:
    """`sort_order` 순 문서 목록 → `{id: 표시 번호 | None}`.

    입력이 **이미 정렬돼 있어야 한다** — 이 함수는 순서를 정하지 않고 세기만 한다.
    정렬은 조회 쪽(`ORDER BY sort_order, id`)의 책임이다.
    """
    numbers: dict[int, int | None] = {}
    counted = 0
    for document in documents:
        if getattr(document, "is_used", 1):
            counted += 1
            numbers[document.id] = counted
        else:
            numbers[document.id] = None
    return numbers
