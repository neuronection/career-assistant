"""Provider error classification (§15 frozen enum + suspected-vendor hints).

Shared family table: ``invalid_key | insufficient_credit |
new_user_quota | region_unavailable | timeout | local_not_running |
unknown`` with the most-specific-first key-prefix hints (no key material
ever leaves the hint). i18n copy stays app-side, keyed off the enum.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

import httpx

from app.ai.providers.presets import guess_preset_for_key

CONNECTION_FAILURE_PATTERN = re.compile(
    r"ECONNREFUSED|connection refused|connect call failed|failed to establish"
    r"|ENOTFOUND|ECONNRESET|network",
    re.IGNORECASE,
)
REGION_PATTERN = re.compile(
    r"region|country|geo|not available in|unavailable in your|unsupported_country",
    re.IGNORECASE,
)
CREDIT_PATTERN = re.compile(
    r"insufficient_quota|insufficient (?:credit|quota|balance)|billing",
    re.IGNORECASE,
)


class ProviderErrorCode(StrEnum):
    INVALID_KEY = "invalid_key"
    INSUFFICIENT_CREDIT = "insufficient_credit"
    NEW_USER_QUOTA = "new_user_quota"
    REGION_UNAVAILABLE = "region_unavailable"
    TIMEOUT = "timeout"
    LOCAL_NOT_RUNNING = "local_not_running"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedProviderError:
    code: ProviderErrorCode
    suspected_vendor: str | None = None


def extract_error_status(message: str) -> int | None:
    match = re.search(r"status (\d{3})", message)
    return int(match.group(1)) if match else None


def classify_provider_error(
    error: Exception,
    *,
    local_provider: bool,
    api_key: str | None = None,
    attempted_preset: str | None = None,
) -> ClassifiedProviderError:
    message = str(error)
    if isinstance(error, httpx.TimeoutException):
        return ClassifiedProviderError(code=ProviderErrorCode.TIMEOUT)
    if (
        isinstance(error, httpx.TransportError) or CONNECTION_FAILURE_PATTERN.search(message)
    ) and local_provider:
        return ClassifiedProviderError(code=ProviderErrorCode.LOCAL_NOT_RUNNING)

    status: int | None = None
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    else:
        status = extract_error_status(message)

    if status == 401:
        classified = ClassifiedProviderError(code=ProviderErrorCode.INVALID_KEY)
        if attempted_preset:
            guess = guess_preset_for_key(api_key)
            if guess and guess != attempted_preset:
                classified = ClassifiedProviderError(
                    code=ProviderErrorCode.INVALID_KEY, suspected_vendor=guess
                )
        return classified
    if status == 402 or CREDIT_PATTERN.search(message):
        return ClassifiedProviderError(code=ProviderErrorCode.INSUFFICIENT_CREDIT)
    if status == 429:
        return ClassifiedProviderError(code=ProviderErrorCode.NEW_USER_QUOTA)
    if status == 403 and REGION_PATTERN.search(message):
        return ClassifiedProviderError(code=ProviderErrorCode.REGION_UNAVAILABLE)
    return ClassifiedProviderError(code=ProviderErrorCode.UNKNOWN)
