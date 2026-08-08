"""대시보드 시각 문법의 **백엔드 사본** — plan.md §0.5.

## 왜 중복 정의하는가

정본은 §0.5 이고, 화면과 PPTX 는 그것을 각자의 언어로 구현한 두 소비자다. 백엔드가
프론트의 `theme/dashboard.ts` 를 읽을 방법은 없으므로 (다른 언어·다른 배포 단위,
게다가 프론트는 페더레이션 remote 라 런타임에 존재하지 않을 수도 있다) 값을 여기에
한 번 더 적는다. §0.5.6 이 그렇게 하라고 정한 이유이기도 하다.

**중복은 드리프트를 부른다.** 그래서 `tests/test_dashboard_pptx.py` 가
`frontend/src/theme/dashboard.ts` 를 직접 파싱해 아래 값들과 대조한다 — 한쪽만
고치면 스위트가 깨진다. 규율이 아니라 테스트로 잠근다.

## ownerKind 휴리스틱

Owner 는 자유 입력 기준정보이고 타입 컬럼이 없다. 같은 보드에 `설비사` 와
`설비사 PM` 이 함께 있을 수 있으며 둘을 가르는 것은 문자열뿐이다. 그래서

* Owner 가 **2명 이상이면 공동** — 이건 추측이 아니라 구조적 사실이다.
* 1명이면 **이름 휴리스틱**으로 분류한다.

휴리스틱은 **표시 전용**이다. 이 값으로 무언가를 저장하지 않고 어떤 규칙도 여기에
의존하지 않으므로, 틀려도 대가는 막대 색 하나뿐이다.
"""

from __future__ import annotations

from ..models.base import ItemStatus

# =============================================================================
# Phase 밴드
# =============================================================================
#: §0.5 팔레트. Phase 가 넷보다 많아지면 순환한다.
DASH_PHASE_COLORS = ("8F7CC3", "40539B", "337FB9", "15958A")

#: 미배정 — 여섯 번째 색이 아니라 **무색 밴드**다 (§0.5).
DASH_UNASSIGNED = "CBD5E1"


def phase_color(phase_seq: int | None) -> str:
    """**표시 번호**로 밴딩한다 — 재번호가 일어나도 색이 따라간다."""
    if phase_seq is None or phase_seq < 0:
        return DASH_UNASSIGNED
    return DASH_PHASE_COLORS[phase_seq % len(DASH_PHASE_COLORS)]


# =============================================================================
# 카드 배경 = 상태
# =============================================================================
#: `(배경, 테두리, 글자)`. 진행전은 채움이 없어 **테두리로만** 보이므로 다른
#: 상태보다 진한 선을 쓴다 (§0.5-3 "테두리 있는 빈 박스").
#:
#: 2026-08-08 사용자 결정으로 셋이 바뀌었다 (프론트 `theme/dashboard.ts` 와 동시):
#:
#: * **진행중이 초록** — 종전 amber 는 "주의" 로 읽혔는데, 주의가 필요한 것은 보류다.
#: * **완료가 짙은 회색** — 다 본 항목이 시선을 끌 이유가 없다. 종전 emerald 는
#:   진행중보다 눈에 띄어 순서가 거꾸로였다.
#: * **NA 는 짙은 배경 + 밝은 글자** — '차단됨' 을 표현한다. 종전의 흐림 처리는
#:   좌측 주관 바까지 같이 죽여 "비활성" 과 구분되지 않았다.
DASH_STATUS_STYLE: dict[ItemStatus, tuple[str, str, str]] = {
    ItemStatus.NOT_STARTED: ("FFFFFF", "94A3B8", "334155"),
    ItemStatus.IN_PROGRESS: ("D1FAE5", "34D399", "065F46"),
    ItemStatus.DONE: ("CBD5E1", "94A3B8", "1E293B"),
    ItemStatus.HOLD: ("FEE2E2", "FCA5A5", "991B1B"),
    ItemStatus.NA: ("334155", "1E293B", "CBD5E1"),
}

STATUS_LABEL: dict[ItemStatus, str] = {
    ItemStatus.NOT_STARTED: "진행전",
    ItemStatus.IN_PROGRESS: "진행중",
    ItemStatus.DONE: "완료",
    ItemStatus.HOLD: "보류",
    ItemStatus.NA: "해당없음",
}

#: 범례 순서 — 진행전 · 진행중 · 완료 · 보류 · 해당없음.
DASH_STATUS_ORDER = (
    ItemStatus.NOT_STARTED,
    ItemStatus.IN_PROGRESS,
    ItemStatus.DONE,
    ItemStatus.HOLD,
    ItemStatus.NA,
)


# =============================================================================
# 주관 (카드 좌측 세로 바)
# =============================================================================
#: `(key, 라벨, 색)` — 범례도 이 순서를 쓴다.
OWNER_KINDS = (
    ("INTERNAL_DEV", "사내 개발부서", "337FB9"),
    ("DSEP", "DSEP 인프라 담당자", "202D72"),
    ("MAKER", "설비사", "15958A"),
    ("JOINT", "공동", "F4A72D"),
    ("NONE", "미지정", "CBD5E1"),
)

OWNER_COLOR = {key: color for key, _label, color in OWNER_KINDS}

#: 미지정 주관 slate. **상태 범례 스와치의 고정 막대 색**이기도 하다 — 그 묶음은
#: 배경만 달라지고 나머지는 같아야 하기 때문이다 (§0.5 범례 개정).
UNASSIGNED_OWNER_COLOR = OWNER_COLOR["NONE"]


def owner_kind(names: list[str] | None) -> str:
    """Owner 이름 목록 → 주관 분류. `theme/dashboard.ts:ownerKindFromNames` 와 같은 규칙."""
    listed = [n for n in (names or []) if n]
    if not listed:
        return "NONE"
    if len(listed) > 1:
        return "JOINT"
    name = listed[0]
    if "공동" in name or "+" in name:
        return "JOINT"
    if "DSEP" in name:
        return "DSEP"
    if "설비사" in name:
        return "MAKER"
    return "INTERNAL_DEV"


def owner_color(names: list[str] | None) -> str:
    return OWNER_COLOR[owner_kind(names)]


# =============================================================================
# 덱 크롬 — `docs/DSEP_AI_Project_Board_Guide.pptx` 에서 뽑은 값
#
# 위쪽 팔레트(Phase·상태·주관)와 **출처가 다르다.** 저 셋은 plan.md §0.5 가 못박은
# 값이고 화면과 픽셀 단위로 맞아야 하지만, 아래는 정본 덱의 제목·구분선·본문색처럼
# **PPT 에만 있는** 색이다. 화면에는 대응물이 없으므로 프론트와 대조하지 않는다.
# =============================================================================
#: 제목·강조 남색.
DECK_INK = "1E2761"
#: 눈썹줄(제목 위 작은 글씨) 청록.
DECK_EYEBROW = "0E8F84"
#: 보조 텍스트·푸터 회색.
DECK_MUTED = "5B6472"
#: 카드·행 테두리.
DECK_BORDER = "AEB9D6"
#: 본문 글자.
DECK_BODY = "1F2937"


def tint(hex_color: str, amount: float = 0.86) -> str:
    """`hex_color` 를 흰색 쪽으로 섞은 연한 색 (마일스톤 헤더 배경).

    정본 덱은 Phase 4개분 틴트를 손으로 지정해 두었지만, 우리 보드는 Phase 가
    넷을 넘을 수 있다. 그래서 값을 베끼는 대신 **같은 결과를 내는 규칙**을 쓴다 —
    §0.5 팔레트에 이 함수를 적용하면 덱의 틴트와 눈으로 구분되지 않는 색이 나오고,
    다섯 번째 Phase 도 저절로 따라온다.
    """
    channels = (hex_color[0:2], hex_color[2:4], hex_color[4:6])
    mixed = (
        round(int(c, 16) * (1 - amount) + 255 * amount) for c in channels
    )
    return "".join(f"{min(255, max(0, v)):02X}" for v in mixed)


# =============================================================================
# 카드 문구
# =============================================================================
def dashboard_text(
    dash_label: str | None,
    deliverable: str | None,
    title: str | None,
    max_title_chars: int = 28,
) -> str:
    """`dash_label` → `deliverable` → `title` 앞부분 (§0.5-1).

    **폴백은 소비자가 적용한다** — 서버 응답은 셋을 그대로 내려보내고, 화면과
    이 내보내기가 각자 같은 규칙으로 고른다. 값이 셋 다 비면 빈 문자열이다.
    """
    label = (dash_label or "").strip()
    if label:
        return label
    delivered = (deliverable or "").strip()
    if delivered:
        return delivered
    head = (title or "").strip()
    if not head:
        return ""
    return f"{head[:max_title_chars]}…" if len(head) > max_title_chars else head
