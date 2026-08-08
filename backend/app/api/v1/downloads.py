"""파일 내보내기 응답의 공통 부분 — 두 라우터가 함께 쓴다.

`versions.py`(템플릿)와 `projects.py`(프로젝트)가 같은 형식의 파일을 내려주므로
MIME 상수와 `Content-Disposition` 조립을 여기 한 곳에 둔다. 한쪽이 다른 쪽의
비공개 헬퍼를 import 하면 두 라우터 사이에 방향 없는 의존이 생긴다.
"""

from __future__ import annotations

from urllib.parse import quote

PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

#: 파일명에 쓸 수 없는 문자. 프로젝트·템플릿 이름은 자유 입력이라 `/` 나 `:` 가
#: 들어올 수 있고, 그대로 헤더에 실으면 브라우저마다 다르게 해석한다.
_UNSAFE_FILENAME = '\\/:*?"<>|\r\n'


def attachment(filename: str) -> str:
    """`Content-Disposition` — 비ASCII 파일명은 **RFC 5987 `filename*`** 로 싣는다.

    한글 이름이 기본이므로 `filename=` 만 쓰면 브라우저가 mojibake 로 저장한다.
    반대로 `filename*` 만 쓰면 아주 오래된 클라이언트가 이름을 잃는다. 그래서
    **둘 다** 보낸다 — ASCII 폴백 + UTF-8 정본. 표준이 정한 대로 `filename*` 가
    있으면 그쪽이 이긴다.
    """
    safe = "".join("_" if c in _UNSAFE_FILENAME else c for c in filename).strip()
    if not safe:
        safe = "download"
    ascii_fallback = safe.encode("ascii", "ignore").decode("ascii").strip()
    if not ascii_fallback or ascii_fallback.lstrip(".") in ("", "_", "pptx", "xlsx"):
        # 확장자만 남았거나 통째로 비ASCII 인 경우 — 알아볼 수 있는 이름을 준다.
        suffix = safe.rsplit(".", 1)[-1] if "." in safe else ""
        ascii_fallback = f"download.{suffix}" if suffix else "download"
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(safe, safe='')}"
    )
