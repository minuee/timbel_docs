"""RS256 키쌍 로드 + JWKS 직렬화.

개인키는 인증서버 밖으로 나가지 않는다. 공개키만 /.well-known/jwks.json 으로 배포하고
각 앱 백엔드가 그것으로 자체 검증한다(= SSO 성립 메커니즘).
"""

import base64
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from .config import Settings


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _jwk(kid: str, public_key: RSAPublicKey) -> dict:
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }


@dataclass(frozen=True)
class KeyRing:
    kid: str
    private_key: RSAPrivateKey
    #: kid -> 공개키. 서명용 활성 키 + 회전 후 아직 살아있는 토큰을 위한 이전 키들
    public_keys: dict[str, RSAPublicKey]

    @classmethod
    def from_settings(cls, settings: Settings) -> "KeyRing":
        pem = Path(settings.jwt_private_key_path).read_bytes()
        private_key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(private_key, RSAPrivateKey):
            raise ValueError("RS256 서명에는 RSA 개인키가 필요하다")

        public_keys = {settings.jwt_kid: private_key.public_key()}
        for entry in filter(None, (e.strip() for e in settings.jwt_retired_public_keys.split(","))):
            kid, _, path = entry.partition(":")
            retired = serialization.load_pem_public_key(Path(path).read_bytes())
            public_keys[kid.strip()] = retired

        return cls(kid=settings.jwt_kid, private_key=private_key, public_keys=public_keys)

    @property
    def private_pem(self) -> bytes:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_key_for(self, kid: str | None) -> RSAPublicKey | None:
        if kid is None:
            return None
        return self.public_keys.get(kid)

    def jwks(self) -> dict:
        # 활성 키를 맨 앞에 둔다. 키 회전 시에는 두 kid 가 병존해야
        # 이미 발급된 토큰이 죽지 않는다.
        ordered = [self.kid] + [k for k in self.public_keys if k != self.kid]
        return {"keys": [_jwk(k, self.public_keys[k]) for k in ordered]}
