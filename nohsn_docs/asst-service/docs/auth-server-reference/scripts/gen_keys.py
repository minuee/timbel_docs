"""RS256 키쌍 생성.

    python scripts/gen_keys.py keys/private.pem

개인키는 인증서버에만 둔다(권한 600, 형상관리 금지).
공개키는 /.well-known/jwks.json 으로 자동 배포되므로 따로 배포할 필요가 없다.
"""

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "keys/private.pem")
    target.parent.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    target.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    target.chmod(0o600)

    public_path = target.with_name(target.stem + "_public.pem")
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    print(f"개인키: {target}\n공개키: {public_path} (키 회전 시 JWT_RETIRED_PUBLIC_KEYS 에 사용)")


if __name__ == "__main__":
    main()
