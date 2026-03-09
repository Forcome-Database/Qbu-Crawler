from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import config

security = HTTPBearer()


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(security),
):
    if not config.API_KEY:
        raise HTTPException(500, "API_KEY not configured on server")
    if credentials.credentials != config.API_KEY:
        raise HTTPException(401, "Invalid API key")
