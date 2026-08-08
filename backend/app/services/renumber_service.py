"""순서 재계산(renumbering) — plan.md §2.2 / §2.3.

**이 모듈은 순수 함수만 갖는다.** DB 도 FastAPI 도 import 하지 않으므로 단위
테스트가 DB 없이 돌아가고, "서버가 최종 권한" 이라는 규칙이 한 곳에만 존재한다.

## 왜 번호를 저장하지 않고 매번 계산하는가

Phase/Milestone 번호는 **행 순서상 최초 등장 순서**로 결정된다. 그런데
`wp_phases` / `wp_milestones` 는 WP 스코프라 여러 버전이 공유한다. 만약 표시
번호를 그 테이블의 `seq_no` 에서만 읽는다면, DRAFT 를 편집해 재번호가 일어날 때
**PUBLISHED 버전의 화면 번호까지 바뀐다** — "PUBLISHED 는 불변" 규칙 위반이다.

그래서 조회 시 번호는 항상 **그 버전의 행 목록**에서 파생한다. 기준정보의
`seq_no` 는 기준정보 관리 화면용 기본 표시순서로만 쓰이며, 편집 가능한 버전을
재계산할 때 함께 갱신된다.

## 블록 연속성(contiguity)

같은 Phase 의 행은 반드시 붙어 있어야 하고, Milestone 은 Phase 블록 내부에서
붙어 있어야 한다. 지키는 방법은 연산마다 다르다.

* **행 추가** — 신규 행은 **미배정(회색)** 이다 (plan.md §0.2). 미배정 행은
  연속성 검사에 보이지 않으므로 어디에 넣어도 안전하다.
* **드래그(`reorder`)** — 각 행이 **자기 소속을 그대로 들고** 위치만 바꾼다.
  소속을 재유도하지 않으므로 블록 내부 순열은 정의상 연속을 유지한다.
* **소속 변경(`membership`) · 블록을 가로지르는 순열** — 결과를 `find_contiguity_breaks`
  로 검사해 위반 시 거부한다.

## 미배정(회색) 행은 **투명(transparent)** 하다 — plan.md §0.2

`phase_id` 가 `None` 인 행은 연속성 판정에서 **없는 것처럼 취급한다.**
`P0 P0 [회색] P0` 은 위반이 아니다. Milestone 도 한 단계 아래에서 똑같다.

왜 이 규칙이 필요한가: 이전 설계는 추가된 행이 위 행의 소속을 상속했다. 드래그가
블록 내부로 제한된 지금, 그러면 새 행이 항상 기존 블록 **안에** 갇혀
**기존 Phase 사이에 새 항목·새 Phase 를 넣을 방법이 아예 없어진다.** 회색 행이 그
자유도를 여는데, 회색 행이 블록을 쪼개는 것으로 판정되면 애초에 놓을 자리가 없다.
그래서 투명성은 편의가 아니라 §0.2 가 성립하기 위한 전제다.

투명성의 따름정리 하나: **회색 행은 어디로 옮겨도 연속성이 변하지 않는다.**
필터링된 수열이 그대로이기 때문이다 (`reorder` 의 블록 제한이 회색 행에는 적용되지
않는 근거 — plan.md §0.2-2).

> 예전에는 드래그도 "새 앞행에서 소속을 물려받는" 방식이었다. 그러면 다른 Phase
> 영역으로 끌었을 때 **아무 경고 없이 그 행의 Phase 가 재배정된다.** 순서만 바꾸려던
> 사용자에게는 분류가 멋대로 바뀐 것으로 보인다. plan.md §2.2 가 이 규칙을 바꿔
> 드래그를 자기 블록 안으로 제한했고, 그와 함께 재유도 로직(`apply_position_change`,
> LIS 기반 `detect_moved_ids`, `moved_item_id`)이 통째로 사라졌다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RowRef:
    """재계산 입력 — 순서 계산에 필요한 최소 정보만 담는다."""

    item_id: int | None
    phase_id: int | None = None
    milestone_id: int | None = None


@dataclass(frozen=True)
class RowNumbering:
    """재계산 결과 (행 1건).

    `is_*_block_start/end` 와 `can_create_*` 를 **서버가 계산해 내려준다**.
    §2.3 경계 규칙이 셀 에디터마다 재구현되지 않도록 하기 위해서다.
    """

    item_id: int | None
    sort_order: int
    phase_id: int | None
    milestone_id: int | None
    phase_no: int | None
    milestone_no: int | None
    is_phase_block_start: bool
    is_phase_block_end: bool
    is_milestone_block_start: bool
    is_milestone_block_end: bool
    #: 이 행에서 새 Phase 를 만들어도 보드가 연속인가 (plan.md §0.2-4).
    #: **`is_*_block_start/end` 에서 파생하지 않는다** — 회색 행은 양쪽 다 True 인
    #: 경계이지만, 한 블록 한가운데 놓인 회색 행에서 만들면 그 블록이 쪼개진다.
    can_create_phase: bool
    can_create_milestone: bool

    def milestone_display_no(self) -> str | None:
        """표시번호 `1.2`. 앞자리는 소속 Phase 에서 **파생**한다 (저장하지 않는다)."""
        if self.phase_no is None or self.milestone_no is None:
            return None
        return f"{self.phase_no}.{self.milestone_no}"


@dataclass(frozen=True)
class RenumberResult:
    rows: list[RowNumbering]
    #: phase_id → 새 seq_no
    phase_seq: dict[int, int] = field(default_factory=dict)
    #: milestone_id → 새 seq_no (Phase 내부 1부터)
    milestone_seq: dict[int, int] = field(default_factory=dict)

    def sort_order_of(self, item_id: int) -> int:
        for row in self.rows:
            if row.item_id == item_id:
                return row.sort_order
        raise KeyError(item_id)


def renumber(rows: list[RowRef], phase_start_no: int = 0) -> RenumberResult:
    """`sort_order` 오름차순 행 목록에 번호를 부여한다.

    plan.md §2.2 의 알고리즘 그대로다. 다만 **미지정(NULL) 행 처리**를 덧붙였다:
    임시저장은 `phase_id`/`milestone_id` 가 비어 있는 행을 허용하므로, 그런 행은
    번호를 받지 못하고(`None`) **번호를 소비하지도 않는다.** 미지정 행이 중간에
    끼었다고 뒤 Phase 번호가 밀리면 곤란하기 때문이다.
    """
    phase_no: dict[int, int] = {}
    next_phase = phase_start_no
    ms_no: dict[tuple[int, int], int] = {}
    next_ms: dict[int, int] = {}

    for row in rows:
        pid = row.phase_id
        if pid is None:
            continue
        if pid not in phase_no:
            phase_no[pid] = next_phase
            next_phase += 1
            next_ms[pid] = 1

        mid = row.milestone_id
        if mid is None:
            continue
        key = (pid, mid)
        if key not in ms_no:
            ms_no[key] = next_ms[pid]
            next_ms[pid] += 1

    # milestone_id 는 FK 로 Phase 하나에 매인다. 한 milestone_id 가 두 Phase 아래
    # 나타나는 건 데이터 오류이며 V3(MILESTONE_PHASE_MISMATCH)가 잡는다.
    # 여기서는 최초 등장 값을 채택해 재계산 자체가 실패하지 않도록 한다.
    milestone_seq: dict[int, int] = {}
    for (_pid, mid), seq in ms_no.items():
        milestone_seq.setdefault(mid, seq)

    numbered: list[RowNumbering] = []
    for i, row in enumerate(rows):
        pid, mid = row.phase_id, row.milestone_id

        above, below = _phase_neighbours(rows, i)

        # 미지정(회색) 행은 **언제나 자기 혼자 블록**이다. 배정된 행의 경계 판정은
        # 회색 행을 건너뛴 이웃을 본다 — `P0 [회색] P0` 의 뒤쪽 P0 는 블록의
        # 시작이 아니라 같은 블록의 연속이다 (§0.2-1 투명성).
        if pid is None:
            phase_start = phase_end = True
        else:
            phase_start = above is None or above != pid
            phase_end = below is None or below != pid

        ms_above, ms_below = _milestone_neighbours(rows, i)
        if pid is None or mid is None:
            ms_start = ms_end = True
        else:
            ms_start = ms_above is None or ms_above != mid
            ms_end = ms_below is None or ms_below != mid

        numbered.append(
            RowNumbering(
                item_id=row.item_id,
                sort_order=i + 1,
                phase_id=pid,
                milestone_id=mid,
                phase_no=phase_no.get(pid) if pid is not None else None,
                milestone_no=ms_no.get((pid, mid)) if pid is not None and mid is not None else None,
                is_phase_block_start=phase_start,
                is_phase_block_end=phase_end,
                is_milestone_block_start=ms_start,
                is_milestone_block_end=ms_end,
                can_create_phase=(above is None or below is None or above != below),
                # Phase 가 없으면 소속시킬 Phase 자체가 없다 (§0.2-6).
                can_create_milestone=(
                    pid is not None
                    and (ms_above is None or ms_below is None or ms_above != ms_below)
                ),
            )
        )

    return RenumberResult(rows=numbered, phase_seq=dict(phase_no), milestone_seq=milestone_seq)


# =============================================================================
# 이웃 탐색 — 회색 행을 건너뛴다 (§0.2-1)
# =============================================================================
def _phase_neighbours(rows: list[RowRef], index: int) -> tuple[int | None, int | None]:
    """`index` 행의 **위·아래 가장 가까운 배정된 Phase**. 회색 행은 건너뛴다.

    `index` 행 자신은 제외한다. 이 한 쌍이 두 가지를 동시에 결정한다.

    * 경계 플래그 — 자기 phase 와 같은가 다른가
    * `can_create_phase` — 위·아래가 **서로** 같으면 새 Phase 가 그 블록을
      쪼갠다. 하나라도 없으면(리스트 끝) 쪼갤 것이 없다.
    """
    above = next((rows[j].phase_id for j in range(index - 1, -1, -1)
                  if rows[j].phase_id is not None), None)
    below = next((rows[j].phase_id for j in range(index + 1, len(rows))
                  if rows[j].phase_id is not None), None)
    return above, below


def _milestone_neighbours(rows: list[RowRef], index: int) -> tuple[int | None, int | None]:
    """같은 규칙을 **자기 Phase 블록 안에서** 적용한다.

    다른 Phase 가 나오면 거기서 멈춘다 — Milestone 블록은 Phase 블록을 넘지
    못하므로, 블록 밖의 Milestone 은 이웃이 아니다. 연속인 보드에서 한 Phase 의
    행들은 (회색 행을 건너뛰면) 한 덩어리이므로 이 탐색은 정확히 그 덩어리를 훑는다.
    """
    phase_id = rows[index].phase_id
    if phase_id is None:
        return None, None

    def scan(indices) -> int | None:
        for j in indices:
            other = rows[j]
            if other.phase_id is None:
                continue                        # 회색 행은 투명
            if other.phase_id != phase_id:
                return None                     # Phase 블록의 끝
            if other.milestone_id is not None:
                return other.milestone_id
        return None

    return scan(range(index - 1, -1, -1)), scan(range(index + 1, len(rows)))


# =============================================================================
# 위치 헬퍼
#
# 소속을 유도하는 함수는 이제 하나도 없다. 행 추가는 회색 행을 만들고(§0.2),
# 드래그는 소속을 들고 다니며(§2.2), 소속 변경은 `membership` 이 명시적으로 받는다.
# 그래서 "서버가 소속을 추측한다" 는 경로 자체가 존재하지 않는다.
# =============================================================================
def reposition(rows: list[RowRef], new_order: list[int]) -> list[RowRef]:
    """새 순서대로 행을 늘어놓는다 — **각 행은 자기 소속을 그대로 들고 간다.**

    이 함수에 소속을 바꾸는 코드가 없다는 것이 `reorder` 의 유일한 보장이다.
    블록 내부 순열이면 결과는 정의상 연속이고 (같은 소속의 행들이 서로 자리만
    바꿀 뿐이므로), 블록을 가로지르는 순열은 `find_contiguity_breaks` 가 잡는다.
    """
    by_id = {r.item_id: r for r in rows}
    return [
        RowRef(item_id=i, phase_id=by_id[i].phase_id, milestone_id=by_id[i].milestone_id)
        for i in new_order
    ]


@dataclass(frozen=True)
class ContiguityBreak:
    """블록이 두 조각으로 갈라진 지점."""

    index: int
    item_id: int | None
    kind: str          # "phase" | "milestone"
    ref_id: int


def find_contiguity_breaks(rows: list[RowRef]) -> list[ContiguityBreak]:
    """같은 Phase(혹은 Milestone)가 두 번째 덩어리로 다시 나타나는 지점을 찾는다.

    두 경로가 이 검사를 쓴다.

    * `membership` — 소속을 **명시적으로** 지정받으므로 구조적 보장이 없다.
    * `reorder` — UI 는 블록 내부 순열만 만들지만, 호스트의 다른 클라이언트는
      블록을 가로지르는 순서를 보낼 수 있다. 그 요청은 **이 검사가 유일한
      방어선**이다. 예전처럼 소속을 재유도해 "고쳐" 주지 않기 때문이다.

    **미지정(회색) 행은 투명하다** (plan.md §0.2-1). 검사에서 아예 걸러내므로
    `P0 P0 [회색] P0` 은 위반이 아니다. 이것은 "미지정 행은 어차피 발행 때 V1/V2 가
    잡으니 넘어간다" 는 소극적 예외가 아니라, §0.2 가 서 있는 **적극적 규칙**이다 —
    회색 행이 블록을 쪼개는 것으로 판정되면 기존 Phase 사이에 놓을 자리가 없어져
    "사이에 추가" 자체가 불가능해진다.

    걸러낸 뒤의 판정은 단순하다: 같은 Phase(Milestone)가 **두 번째 덩어리로 다시
    등장하면** 그 지점이 break 다. 보고되는 `index` 는 원본 리스트 기준이다.
    """
    breaks: list[ContiguityBreak] = []

    assigned = [(i, r) for i, r in enumerate(rows) if r.phase_id is not None]

    seen_phase: set[int] = set()
    previous: int | None = None
    for index, row in assigned:
        if row.phase_id != previous:
            if row.phase_id in seen_phase:
                breaks.append(ContiguityBreak(index, row.item_id, "phase", row.phase_id))
            seen_phase.add(row.phase_id)
            previous = row.phase_id

    # Milestone 은 한 단계 아래에서 같은 규칙. `milestone_id` 가 없는 행도 이
    # 층위에서는 투명하다 — `P0/M1, P0/(없음), P0/M1` 역시 위반이 아니다.
    seen_ms: set[tuple[int, int]] = set()
    previous_key: tuple[int, int] | None = None
    for index, row in assigned:
        if row.milestone_id is None:
            continue
        key = (row.phase_id, row.milestone_id)
        if key != previous_key:
            if key in seen_ms:
                breaks.append(
                    ContiguityBreak(index, row.item_id, "milestone", row.milestone_id)
                )
            seen_ms.add(key)
            previous_key = key

    return breaks
