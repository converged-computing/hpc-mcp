import re
from typing import Callable

from fastapi import HTTPException, Request, status
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware


class TokenAuthMiddleware(Middleware):
    """
    Middleware for basic auth token.
    Check for a basic token match. This is for testing only.
    """

    def __init__(self, static_token: str, header_name: str = "authorization"):
        """
        Set a basic authorization header to validate requests.
        """
        self.static_token = static_token
        self.header_name = header_name

    async def __call__(self, request: Request, call_next: Callable):
        """
        Check the header (auth) on a request.
        """
        headers = get_http_headers()
        auth_header = headers.get(self.header_name)

        if not auth_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication header missing",
            )

        # In case they added Bearer or Basic
        for string in ["earer", "asic"]:
            auth_header = re.sub(f"(B|b){string}:", "", auth_header)

        if auth_header != self.static_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid authentication token",
            )

        response = await call_next(request)
        return response
