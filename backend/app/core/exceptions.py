"""도메인 예외와, 그것을 HTTP 응답으로 옮기는 라우트 클래스.

**왜 예외 핸들러가 아니라 라우트 클래스인가**: `add_exception_handler()` 는
`FastAPI` 앱에만 달 수 있다. 이 모듈은 앱을 소유하지 않으므로(INTEGRATION.md §4)
호스트에게 "핸들러도 등록해 주세요" 라고 요구하면 마운트 계약이 두 줄에서
늘어난다. `APIRouter(route_class=WpAPIRoute)` 로 감싸면 변환이 라우터 안에서
끝나고, 호스트는 `include_router` 한 줄이면 된다.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute


class WpError(Exception):
    """이 모듈이 던지는 모든 도메인 예외의 기반."""

    status_code = 400
    code = "WP_ERROR"

    def __init__(self, message: str, *, detail: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        if code:
            self.code = code

    def to_payload(self) -> dict[str, Any]:
        """오류 본문은 항상 **평평하다**: `{code, message, ...부가정보}`.

        `detail` 이 dict 면 한 겹 펼쳐 담는다. 그렇게 하지 않으면 클라이언트가
        `body.detail.detail.errors` 를 파야 하는데, `POST /validate` 는 같은
        내용을 §2.5 형식 그대로 돌려주므로 파서를 두 벌 만들게 된다.
        """
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if isinstance(self.detail, dict):
            payload.update(self.detail)
        elif self.detail is not None:
            payload["detail"] = self.detail
        return payload


class NotFoundError(WpError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(WpError):
    """상태 전이 위반 — 예: PUBLISHED 버전 수정 시도, DRAFT 중복 생성."""

    status_code = 409
    code = "CONFLICT"


class BadRequestError(WpError):
    """참조 무결성 등 요청 자체의 오류. 임시저장도 이것만은 통과시키지 않는다."""

    status_code = 400
    code = "BAD_REQUEST"


class UnprocessableEntityError(WpError):
    """요청은 형식상 맞지만 도메인 규칙이 거부하는 경우.

    §2.3 경계 규칙 위반(블록 중간 행에서 새 Phase 생성)이나, 결과 보드의 블록
    연속성이 깨지는 reorder 가 여기 해당한다. 400(요청이 틀림)도 409(상태 전이)도
    아니라서 별도로 둔다.
    """

    status_code = 422
    code = "UNPROCESSABLE"


class PublishValidationError(WpError):
    """발행 검증 실패. §2.5 형식의 valid/errors/warnings 를 담는다."""

    status_code = 422
    code = "VALIDATION_FAILED"


def _handler_factory(original: Callable[[Request], Coroutine[Any, Any, Response]]):
    async def wrapped(request: Request) -> Response:
        try:
            return await original(request)
        except WpError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.to_payload()) from exc

    return wrapped


class WpAPIRoute(APIRoute):
    """도메인 예외를 HTTP 응답으로 옮기는 라우트. 호스트 앱 설정을 요구하지 않는다."""

    def get_route_handler(self):
        return _handler_factory(super().get_route_handler())
