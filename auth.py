import time, jwt, os
from typing import Optional
from redis import Redis

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "60"))

class Auth:
    def __init__(self, r: Redis):
        self.r = r

    def login(self, user_id: str, password: str):
        user_key = f"user:{user_id}"
        user = self.r.hgetall(user_key) 
        if not user or user.get("password") != password:
            return None
        payload = {"sub": user_id, "iat": int(time.time()), "exp": int(time.time()) + JWT_EXPIRE_MIN*60}
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        self.r.setex(f"session:{token}", JWT_EXPIRE_MIN*60, user_id)
        return token


    def verify(self, token: str) -> Optional[str]:
        try:
            jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except Exception:
            return None
        uid = self.r.get(f"session:{token}")
        return uid if uid else None
