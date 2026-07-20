"""GET /.well-known/jwks.json — 공개키 배포.

각 앱 백엔드가 시작 시 한 번 받아 캐시하고, 토큰 헤더의 kid 로 키를 골라 자체 검증한다.
이게 앱 간 SSO 를 성립시키는 지점이다(성능 개선이 부수 효과).
"""

from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["jwks"])


@router.get("/.well-known/jwks.json")
async def jwks(request: Request, response: Response) -> dict:
    # 키 회전 시 앱들이 새 kid 를 늦게 알면 검증에 실패한다.
    # 캐시는 짧게 두고, 회전 시에는 이전 공개키를 최소 이 시간 이상 병존시킨다.
    response.headers["Cache-Control"] = "public, max-age=300"
    return request.app.state.keyring.jwks()
