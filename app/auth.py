import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWTError
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


logger = logging.getLogger(__name__)

JWKS_CACHE_TTL_SECONDS = 300


class AuthError(Exception):
    """Raised when IAS authentication fails."""


@dataclass(frozen=True)
class IASConfig:
    issuer: str
    audience: str
    required_scope: str

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/oauth2/certs"


class IASAuthMiddleware:
    def __init__(self, app: ASGIApp, config: IASConfig):
        self.app = app
        self.config = config
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cache_expires_at = 0.0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        auth_header = headers.get('authorization')

        if not auth_header or not auth_header.startswith('Bearer '):
            await self._unauthorized(scope, receive, send, 'Missing bearer token')
            return

        token = auth_header.split(' ', 1)[1]

        try:
            payload = await self._verify_token(token)
            scope['ias_payload'] = payload
        except AuthError as exc:
            logger.warning('IAS auth rejected request: %s', exc)
            await self._unauthorized(scope, receive, send, 'Invalid bearer token')
            return

        await self.app(scope, receive, send)

    async def _verify_token(self, token: str) -> dict[str, Any]:
        public_key = await self._get_public_key(token)

        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=['RS256'],
                audience=self.config.audience,
                issuer=self.config.issuer,
            )
        except PyJWTError as exc:
            raise AuthError('JWT validation failed') from exc

        if self.config.required_scope not in payload.get('ias_apis', []):
            raise AuthError(
                f'Missing required ias_apis scope: {self.config.required_scope}'
            )

        return payload

    async def _get_public_key(self, token: str):
        try:
            kid = jwt.get_unverified_header(token)['kid']
        except PyJWTError as exc:
            raise AuthError('JWT header is invalid') from exc

        jwks = await self._get_jwks()
        public_key = self._public_key_from_jwks(jwks, kid)
        if public_key is not None:
            return public_key

        # Retry once with a refreshed cache in case IAS rotated keys.
        jwks = await self._get_jwks(force_refresh=True)
        public_key = self._public_key_from_jwks(jwks, kid)
        if public_key is None:
            raise AuthError('No matching JWKS key found')
        return public_key

    async def _get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not force_refresh
            and self._jwks_cache is not None
            and now < self._jwks_cache_expires_at
        ):
            return self._jwks_cache

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.config.jwks_url)
                response.raise_for_status()
                jwks = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthError('Unable to retrieve IAS JWKS') from exc

        self._jwks_cache = jwks
        self._jwks_cache_expires_at = now + JWKS_CACHE_TTL_SECONDS
        return jwks

    @staticmethod
    def _public_key_from_jwks(jwks: dict[str, Any], kid: str):
        for key in jwks.get('keys', []):
            if key.get('kid') == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(key)
        return None

    @staticmethod
    async def _unauthorized(
        scope: Scope,
        receive: Receive,
        send: Send,
        detail: str,
    ) -> None:
        response = JSONResponse(status_code=401, content={'detail': detail})
        await response(scope, receive, send)


def load_ias_config() -> IASConfig | None:
    allow_unauthenticated = (
        os.getenv('ALLOW_UNAUTHENTICATED', '').strip().lower() == 'true'
    )
    issuer = os.getenv('IAS_ISSUER')
    audience = os.getenv('IAS_AUDIENCE')
    required_scope = os.getenv('IAS_REQUIRED_SCOPE', 'api_read_access')

    if not issuer or not audience:
        if allow_unauthenticated:
            logger.warning(
                'IAS auth is disabled because ALLOW_UNAUTHENTICATED=true. '
                'The endpoint is publicly reachable.'
            )
            return None

        raise RuntimeError(
            'IAS auth is required. Set IAS_ISSUER and IAS_AUDIENCE, or set '
            'ALLOW_UNAUTHENTICATED=true only for deliberate local/test use.'
        )

    return IASConfig(
        issuer=issuer,
        audience=audience,
        required_scope=required_scope,
    )


def wrap_with_ias_auth(app: ASGIApp) -> ASGIApp:
    config = load_ias_config()
    if config is None:
        return app

    logger.info(
        'IAS auth enabled for audience %s with required scope %s',
        config.audience,
        config.required_scope,
    )
    return IASAuthMiddleware(app, config)
