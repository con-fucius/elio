"""Generate RS256 keypair and merge ELIO_JWT_* into apps/api/.env (dev only)."""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

api_dir = Path(__file__).resolve().parents[1]
env_path = api_dir / ".env"

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
priv = (
    key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
    .replace("\n", "\\n")
)
pub = (
    key.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
    .replace("\n", "\\n")
)

if not env_path.exists():
    env_path.write_text(
        "ELIO_ENVIRONMENT=development\n"
        "ELIO_DEBUG=true\n"
        "ELIO_LOG_JSON=false\n"
        "ELIO_DATABASE_URL=postgresql+asyncpg://elio:elio@localhost:5432/elio\n"
        "ELIO_AUTH_ENABLED=true\n"
        "ELIO_ALLOW_PASSWORD_LOGIN=true\n"
    )

text = env_path.read_text()
lines = [
    ln
    for ln in text.splitlines()
    if not ln.startswith("ELIO_JWT_PRIVATE_KEY_PEM")
    and not ln.startswith("ELIO_JWT_PUBLIC_KEY_PEM")
]
lines.append(f'ELIO_JWT_PRIVATE_KEY_PEM="{priv}"')
lines.append(f'ELIO_JWT_PUBLIC_KEY_PEM="{pub}"')
env_path.write_text("\n".join(lines) + "\n")
print(f"Wrote JWT keys to {env_path}")
print("Restart the API to load new settings.")
