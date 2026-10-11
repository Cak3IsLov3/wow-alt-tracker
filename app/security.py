import base64
import hashlib

from cryptography.fernet import Fernet


class TokenCipher:
    """Versleutelt OAuth-tokens voordat ze de database in gaan."""

    def __init__(self, key: str = "", fallback_secret: str = ""):
        if not key:
            digest = hashlib.sha256(fallback_secret.encode()).digest()
            key = base64.urlsafe_b64encode(digest).decode()
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()
