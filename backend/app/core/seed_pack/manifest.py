"""Seed-pack parsing and identity (plan 218 / ADR-0056).

The parser is the app-side authority for a pack's manifest, item envelopes,
identity grammar, connector binding, caps and content digests. It is pure:
callers hand it a mapping of ``relative path -> raw bytes`` (a git checkout
subset or an extracted archive) and receive validated models plus the pack
digest. Nothing here touches the network, the database or the filesystem.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, cast
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)

from app.core.errors import ValidationError
from app.core.seed_pack.errors import (
    CAP_EXCEEDED,
    CONFIG_INVALID,
    CONNECTOR_UNKNOWN,
    DIGEST_MISMATCH,
    ENDPOINT_DOMAIN_DENIED,
    FORMAT_UNSUPPORTED,
    FORMAT_VERSION_UNSUPPORTED,
    IDENTITY_INVALID,
    ITEM_FILE_INVALID,
    ITEM_FILE_MISSING,
    ITEM_TYPE_MISMATCH,
    LICENSE_NOT_ALLOWED,
    MANIFEST_INVALID,
    MANIFEST_MISSING,
    PACK_NOT_FOUND,
    PRIORITY_MISMATCH,
    SCOPE_UNSUPPORTED,
    SEED_KEY_DUPLICATE,
    SeedPackError,
)

LICENSES: Final = frozenset({"Apache-2.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "MIT"})
SCHEMA_VERSION: Final = "1.0"
MAX_MANIFEST_BYTES: Final = 256 * 1024
MAX_ITEM_FILE_BYTES: Final = 5 * 1024 * 1024
MAX_PACK_BYTES: Final = 64 * 1024 * 1024
MAX_ITEM_FILES: Final = 200
MAX_PRESETS_PER_FILE: Final = 300
MAX_ENDPOINTS_PER_FILE: Final = 100
MAX_CONFIG_ENTRIES: Final = 20
MAX_REPLACES: Final = 100

_KEBAB = r"^[a-z][a-z0-9-]{1,63}$"
_SEED_KEY = re.compile(r"^([a-z][a-z0-9-]{1,63}):([a-z0-9][a-z0-9._/-]{0,119})$")
_SEED_BODY = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,119}$")
_SLUG = r"^[a-z0-9][a-z0-9-]{0,79}$"
_COUNTRY = r"^[A-Z]{2}$"
_REGION = r"^[A-Z][A-Z0-9_-]{1,31}$"
_LANGUAGE = r"^[a-z]{2}$"
_SEMVER = r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"
_SHA256 = r"^[0-9a-f]{64}$"
_WORK_MODES: Final = frozenset({"remote", "hybrid", "onsite"})


def canonical_json(value: Any) -> bytes:
    """Canonical JSON bytes (sorted keys, compact, UTF-8) for content identity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_pack_digest(
    manifest: Mapping[str, Any], item_files: Sequence[tuple[str, bytes]]
) -> str:
    """The contract's pack digest: canonical manifest, then ``\\0path\\0bytes``."""
    digest = hashlib.sha256()
    digest.update(canonical_json(manifest))
    for path, data in item_files:
        digest.update(b"\0")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
    return f"sha256:{digest.hexdigest()}"


def compute_files_digest(files: Mapping[str, bytes]) -> str:
    """Compute a pack digest from a manifest + item-file mapping."""
    manifest = _loads(files.get("manifest.json", b""), code=MANIFEST_INVALID, label="manifest.json")
    if not isinstance(manifest, dict):
        raise SeedPackError(MANIFEST_INVALID, "manifest.json must be an object")
    refs = manifest.get("item_files") or []
    pairs: list[tuple[str, bytes]] = []
    for entry in refs:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise SeedPackError(MANIFEST_INVALID, "manifest.item_files is invalid")
        data = files.get(entry["path"])
        if data is None:
            raise SeedPackError(ITEM_FILE_MISSING, entry["path"])
        pairs.append((entry["path"], data))
    return compute_pack_digest(manifest, pairs)


def _loads(data: bytes, *, code: str, label: str) -> Any:
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeedPackError(code, f"{label}: {exc}") from exc


def _model_error(exc: PydanticValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    return f"{location}: {first.get('msg', 'invalid')}".strip(": ")


def _check_item_path(path: str) -> None:
    if not path.startswith("items/") or not path.endswith(".json"):
        raise SeedPackError(ITEM_FILE_INVALID, f"{path}: path must be items/**.json")
    if path.startswith("/") or "\\" in path or "\x00" in path:
        raise SeedPackError(ITEM_FILE_INVALID, f"{path}: path is not a relative POSIX path")
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise SeedPackError(ITEM_FILE_INVALID, f"{path}: path traversal is forbidden")


def _check_seed_key(value: str, *, prefix: str, label: str) -> None:
    match = _SEED_KEY.match(value)
    if not match or match.group(1) != prefix:
        raise SeedPackError(IDENTITY_INVALID, f"{label}.seed_key must be {prefix}:<body>")


def _unique(values: Iterable[str], *, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise SeedPackError(IDENTITY_INVALID, f"{label}: duplicate {value!r}")
        seen.add(value)


def _validate_locale(
    *,
    label: str,
    category: str | None,
    country: str | None,
    countries: list[str] | None,
    regions: list[str] | None,
    languages: list[str] | None,
    worldwide: bool,
) -> None:
    if country and not re.fullmatch(_COUNTRY, country):
        raise SeedPackError(IDENTITY_INVALID, f"{label}.country: {country!r}")
    if countries:
        _unique(countries, label=f"{label}.countries")
        for value in countries:
            if not re.fullmatch(_COUNTRY, value):
                raise SeedPackError(IDENTITY_INVALID, f"{label}.countries: {value!r}")
        if country and country not in countries:
            raise SeedPackError(IDENTITY_INVALID, f"{label}.countries must include .country")
        if len(countries) > 50:
            raise SeedPackError(CAP_EXCEEDED, f"{label}.countries exceeds 50 entries")
    if regions:
        _unique(regions, label=f"{label}.regions")
        for value in regions:
            if not re.fullmatch(_REGION, value):
                raise SeedPackError(IDENTITY_INVALID, f"{label}.regions: {value!r}")
        if len(regions) > 10:
            raise SeedPackError(CAP_EXCEEDED, f"{label}.regions exceeds 10 entries")
    if languages:
        _unique(languages, label=f"{label}.languages")
        for value in languages:
            if not re.fullmatch(_LANGUAGE, value):
                raise SeedPackError(IDENTITY_INVALID, f"{label}.languages: {value!r}")
        if len(languages) > 20:
            raise SeedPackError(CAP_EXCEEDED, f"{label}.languages exceeds 20 entries")
    if worldwide:
        if countries or regions:
            raise SeedPackError(
                IDENTITY_INVALID, f"{label}: worldwide requires no countries/regions"
            )
        if category is not None and category != "remote":
            raise SeedPackError(
                IDENTITY_INVALID, f'{label}: worldwide is only valid with category "remote"'
            )
    if category == "ats" and not country and not countries:
        raise SeedPackError(
            IDENTITY_INVALID, f'{label}: category "ats" requires country or countries'
        )


def _validate_config(config: dict[str, Any], *, label: str) -> None:
    if len(config) > MAX_CONFIG_ENTRIES:
        raise SeedPackError(CAP_EXCEEDED, f"{label}.config exceeds {MAX_CONFIG_ENTRIES} entries")
    for key, value in config.items():
        if not isinstance(key, str) or not key or len(key) > 80:
            raise SeedPackError(ITEM_FILE_INVALID, f"{label}.config key is invalid")
        if not isinstance(value, (str, int, float, bool)):
            raise SeedPackError(ITEM_FILE_INVALID, f"{label}.config.{key} must be a scalar value")


class ItemFileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=_SHA256)


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_KEBAB)
    schema_version: str
    version: str = Field(pattern=_SEMVER)
    license: str = Field(min_length=1, max_length=40)
    scope: str = "system"
    priority: int = Field(ge=0, le=999)
    min_app_version: str | None = Field(default=None, pattern=_SEMVER)
    description: str = Field(default="", max_length=1000)
    item_files: list[ItemFileRef] = Field(min_length=1, max_length=MAX_ITEM_FILES)
    replaces: list[str] = Field(default_factory=list, max_length=MAX_REPLACES)

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION!r}")
        return value

    @field_validator("license")
    @classmethod
    def _license(cls, value: str) -> str:
        if value not in LICENSES:
            raise ValueError(f"license {value!r} is not allowed")
        return value

    @model_validator(mode="after")
    def _paths(self) -> PackManifest:
        _unique((entry.path for entry in self.item_files), label="manifest.item_files")
        return self


class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=600)
    commit: str | None = Field(default=None, max_length=64)
    retrieved_at: date | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("source.url must be https")
        return value


class ItemMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    item_type: str = Field(min_length=1, max_length=80)
    format: str = Field(min_length=1, max_length=80)
    format_version: int = Field(ge=1)
    dataset_vintage: date
    license: str | None = Field(default=None, max_length=40)
    source: SourceInfo | None = None
    attribution: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _extensions(self) -> ItemMetadata:
        for key in self.__pydantic_extra__ or {}:
            if not key.startswith("x-"):
                raise ValueError(f"metadata key {key!r} is not allowed")
        return self


class ItemEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: ItemMetadata
    items: list[Any]


class AtsPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_key: str
    slug: str = Field(pattern=_SLUG)
    name: str = Field(min_length=1, max_length=200)
    connector_key: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=1, max_length=80)
    category: str
    country: str | None = None
    countries: list[str] | None = None
    regions: list[str] | None = None
    worldwide: bool = False
    languages: list[str] | None = None
    work_modes: list[str] | None = None
    homepage: str | None = Field(default=None, max_length=500)
    openings: int | None = Field(default=None, ge=0)
    verified_at: date | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("category")
    @classmethod
    def _category(cls, value: str) -> str:
        if value not in {"ats", "remote"}:
            raise ValueError('category must be "ats" or "remote"')
        return value

    @field_validator("homepage")
    @classmethod
    def _homepage(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("homepage must be https")
        return value

    def country_lens(self) -> list[str]:
        """The gallery's country set: ``countries`` or the primary country."""
        if self.countries:
            return list(self.countries)
        return [self.country] if self.country else []


class EndpointParam(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    required: bool = False
    type: str | None = Field(default=None, pattern=r"^(string|number|boolean)$")


class EndpointDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_key: str
    label: str = Field(min_length=1, max_length=120)
    connector_key: str = Field(min_length=1, max_length=80)
    platform: str = Field(default="", max_length=80)
    server: str = Field(min_length=1, max_length=400)
    method: str = "GET"
    path: str = Field(min_length=1, max_length=400)
    auth: str = "none"
    params: list[EndpointParam] = Field(default_factory=list, max_length=20)
    countries: list[str] | None = None
    regions: list[str] | None = None
    worldwide: bool = False
    languages: list[str] | None = None
    docs_url: str | None = Field(default=None, max_length=600)

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        if value != "GET":
            raise ValueError("method must be GET in v1")
        return value

    @field_validator("auth")
    @classmethod
    def _auth(cls, value: str) -> str:
        if value not in {"none", "api_key", "bearer", "oauth"}:
            raise ValueError("auth is not a known descriptor")
        return value

    @field_validator("server")
    @classmethod
    def _server(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("server must be https")
        parts = urlsplit(value)
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("server must not carry userinfo/query/fragment")
        return value

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not value.startswith("/") or ".." in value:
            raise ValueError("path must start with / and must not contain ..")
        return value

    @field_validator("docs_url")
    @classmethod
    def _docs(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("docs_url must be https")
        return value


class JobFamilyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_key: str
    key: str = Field(pattern=_KEBAB)
    label: str = Field(min_length=1, max_length=120)
    parent_key: str | None = Field(default=None, pattern=_KEBAB)
    description: str = Field(default="", max_length=2000)


class JobSkillRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_key: str = Field(pattern=_KEBAB)
    required_level: int = Field(default=5, ge=1, le=10)
    importance: str = "important"

    @field_validator("importance")
    @classmethod
    def _importance(cls, value: str) -> str:
        if value not in {"core", "important", "bonus"}:
            raise ValueError("importance must be core|important|bonus")
        return value


class JobTypeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_key: str
    code: str = Field(pattern=_KEBAB)
    title: str = Field(min_length=1, max_length=160)
    family_key: str = Field(pattern=_KEBAB)
    summary: str = Field(default="", max_length=500)
    attributes: dict[str, Any] = Field(default_factory=dict)
    skills: list[JobSkillRef] = Field(default_factory=list, max_length=40)
    interests: list[str] = Field(default_factory=list, max_length=40)


class JobRelationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    seed_key: str
    from_code: str = Field(alias="from", pattern=_KEBAB)
    to_code: str = Field(alias="to", pattern=_KEBAB)
    relation_type: str = Field(alias="type", min_length=1, max_length=40)
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=1000)


class CareerPathItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    seed_key: str
    job_code: str = Field(alias="job", pattern=_KEBAB)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class SkillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_key: str
    key: str = Field(pattern=_KEBAB)
    label: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)
    parent_key: str | None = Field(default=None, pattern=_KEBAB)
    parent_source: str | None = Field(default=None, max_length=20)


class InterestTagItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_key: str
    key: str = Field(pattern=_KEBAB)
    label: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)
    kind: str = "topic"


@dataclass(frozen=True)
class FormatSpec:
    item_type: str
    seed_key_prefix: str
    model: type[BaseModel]
    max_items: int
    catalog: bool = False
    adapter: Any | None = None


FORMATS: Final[dict[tuple[str, int], FormatSpec]] = {
    ("ats_presets", 1): FormatSpec("ats_presets", "ats-preset", AtsPreset, MAX_PRESETS_PER_FILE),
    ("endpoint_descriptors", 1): FormatSpec(
        "endpoint_descriptors", "endpoint", EndpointDescriptor, MAX_ENDPOINTS_PER_FILE
    ),
    ("job_families", 1): FormatSpec("job_families", "job-family", JobFamilyItem, 200, catalog=True),
    ("job_types", 2): FormatSpec("job_types", "job-type", JobTypeItem, 2_000, catalog=True),
    ("job_relations", 1): FormatSpec(
        "job_relations", "job-relation", JobRelationItem, 10_000, catalog=True
    ),
    ("career_paths", 1): FormatSpec(
        "career_paths", "career-path", CareerPathItem, 500, catalog=True
    ),
    ("skills", 1): FormatSpec("skills", "skill", SkillItem, 2_000, catalog=True),
    ("interest_tags", 1): FormatSpec(
        "interest_tags", "interest", InterestTagItem, 1_000, catalog=True
    ),
}
CATALOG_FORMATS: Final[frozenset[str]] = frozenset(
    {"job_families", "job_types", "job_relations", "career_paths", "skills", "interest_tags"}
)
CATALOG_ITEM_TYPES: Final[frozenset[str]] = CATALOG_FORMATS


class Publisher(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_KEBAB)
    name: str = Field(min_length=1, max_length=120)
    homepage: str | None = Field(default=None, max_length=500)
    contact: str | None = Field(default=None, max_length=200)


class IndexedPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_KEBAB)
    path: str = Field(min_length=1, max_length=300)
    manifest: str = Field(min_length=1, max_length=300)
    itemTypes: list[str] = Field(default_factory=list)
    license: str
    version: str = Field(pattern=_SEMVER)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    signature: dict[str, Any] | None = None

    @field_validator("license")
    @classmethod
    def _license(cls, value: str) -> str:
        if value not in LICENSES:
            raise ValueError(f"license {value!r} is not allowed")
        return value

    @model_validator(mode="after")
    def _paths(self) -> IndexedPack:
        if self.manifest != f"{self.path}/manifest.json":
            raise ValueError("manifest must be <path>/manifest.json")
        return self


class RepoIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: int
    kind: str
    publisher: Publisher
    packs: list[IndexedPack] = Field(min_length=1)

    @model_validator(mode="after")
    def _root(self) -> RepoIndex:
        if self.schemaVersion != 1:
            raise ValueError("schemaVersion must be 1")
        if self.kind != "career-seed-repo":
            raise ValueError("kind must be career-seed-repo")
        _unique((pack.id for pack in self.packs), label="packs.id")
        _unique((pack.path for pack in self.packs), label="packs.path")
        for pack in self.packs:
            expected = f"packs/{self.publisher.id}/{pack.path.rsplit('/', 1)[-1]}"
            if pack.path != expected:
                raise ValueError(f"pack {pack.id}: path must be {expected}")
        return self


@dataclass(frozen=True)
class ParsedItem:
    item_type: str
    format: str
    format_version: int
    seed_key: str
    payload: dict[str, Any]
    content_hash: str
    source_file: str


@dataclass(frozen=True)
class ParsedPack:
    manifest: PackManifest
    manifest_raw: dict[str, Any]
    digest: str
    item_files: dict[str, bytes]
    items: tuple[ParsedItem, ...]
    skipped_formats: tuple[tuple[str, int], ...] = ()

    @property
    def by_key(self) -> dict[str, ParsedItem]:
        return {item.seed_key: item for item in self.items}

    @property
    def item_types(self) -> set[str]:
        return {item.item_type for item in self.items}


def parse_repo_index(data: bytes) -> RepoIndex:
    payload = _loads(data, code=MANIFEST_INVALID, label="seed-repo.json")
    try:
        return RepoIndex.model_validate(payload)
    except PydanticValidationError as exc:
        raise SeedPackError(MANIFEST_INVALID, f"seed-repo.json: {_model_error(exc)}") from exc


def default_connectors() -> Mapping[str, Any]:
    from app.extensions.registry import iter_connectors

    return {connector.key: connector for connector in iter_connectors()}


def _host_matches(host: str, domain: str) -> bool:
    host = host.lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    if domain.startswith("*."):
        suffix = domain[1:]
        return host.endswith(suffix) and host != suffix[1:]
    return host == domain


def endpoint_in_connector_domains(connector: Any, server: str) -> bool:
    """True when ``server``'s host sits inside the connector's declared domains."""
    host = urlsplit(server).hostname or ""
    domains = connector.manifest().get("domains") or []
    return bool(host) and any(_host_matches(host, str(domain)) for domain in domains)


def _check_endpoint_domain(connector: Any, server: str, *, label: str) -> None:
    if not endpoint_in_connector_domains(connector, server):
        raise SeedPackError(
            ENDPOINT_DOMAIN_DENIED,
            f"{label}.server is outside the connector's declared domains",
        )


def _validate_item(
    item: AtsPreset | EndpointDescriptor, connectors: Mapping[str, Any], *, label: str
) -> None:
    connector_key = item.connector_key
    connector = connectors.get(connector_key)
    if connector is None:
        raise SeedPackError(CONNECTOR_UNKNOWN, f"{label}.connector_key: {connector_key!r}")
    if isinstance(item, AtsPreset):
        _validate_locale(
            label=label,
            category=item.category,
            country=item.country,
            countries=item.countries,
            regions=item.regions,
            languages=item.languages,
            worldwide=item.worldwide,
        )
        if item.work_modes:
            _unique(item.work_modes, label=f"{label}.work_modes")
            if len(item.work_modes) > 3:
                raise SeedPackError(CAP_EXCEEDED, f"{label}.work_modes exceeds 3 entries")
            for mode in item.work_modes:
                if mode not in _WORK_MODES:
                    raise SeedPackError(IDENTITY_INVALID, f"{label}.work_modes: {mode!r}")
        _validate_config(item.config, label=label)
        try:
            connector.validate_config(dict(item.config))
        except ValidationError as exc:
            raise SeedPackError(CONFIG_INVALID, f"{label}.config: {exc}") from exc
    elif isinstance(item, EndpointDescriptor):
        _validate_locale(
            label=label,
            category=None,
            country=None,
            countries=item.countries,
            regions=item.regions,
            languages=item.languages,
            worldwide=item.worldwide,
        )
        _check_endpoint_domain(connector, item.server, label=label)


def _parse_supported(
    fmt: FormatSpec,
    *,
    item_type: str,
    format_version: int,
    raw_items: Sequence[Any],
    source_file: str,
    connectors: Mapping[str, Any],
) -> list[ParsedItem]:
    parsed: list[ParsedItem] = []
    for position, raw in enumerate(raw_items):
        label = f"{source_file} item {position}"
        if not isinstance(raw, dict):
            raise SeedPackError(ITEM_FILE_INVALID, f"{label}: item must be an object")
        raw_key = raw.get("seed_key")
        if not isinstance(raw_key, str):
            raise SeedPackError(IDENTITY_INVALID, f"{label}.seed_key is required")
        _check_seed_key(raw_key, prefix=fmt.seed_key_prefix, label=label)
        try:
            item = fmt.model.model_validate(raw)
        except PydanticValidationError as exc:
            raise SeedPackError(ITEM_FILE_INVALID, f"{label}: {_model_error(exc)}") from exc
        if fmt.catalog:
            payload = item.model_dump(mode="json", by_alias=True)
        else:
            _validate_item(cast(AtsPreset | EndpointDescriptor, item), connectors, label=label)
            payload = item.model_dump(mode="json")
        parsed.append(
            ParsedItem(
                item_type=item_type,
                format=fmt.item_type,
                format_version=format_version,
                seed_key=raw_key,
                payload=payload,
                content_hash=sha256_hex(canonical_json(raw)),
                source_file=source_file,
            )
        )
    return parsed


def parse_pack(
    files: Mapping[str, bytes],
    *,
    connectors: Mapping[str, Any] | None = None,
    source_priority: int | None = None,
    allow_unknown_formats: bool = False,
) -> ParsedPack:
    """Validate one pack from ``relative path -> raw bytes``."""
    total = sum(len(data) for data in files.values())
    if total > MAX_PACK_BYTES:
        raise SeedPackError(CAP_EXCEEDED, f"pack exceeds {MAX_PACK_BYTES} bytes")

    manifest_bytes = files.get("manifest.json")
    if manifest_bytes is None:
        raise SeedPackError(MANIFEST_MISSING, "manifest.json is required")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise SeedPackError(CAP_EXCEEDED, "manifest exceeds 256 KB")
    manifest_raw = _loads(manifest_bytes, code=MANIFEST_INVALID, label="manifest.json")
    try:
        manifest = PackManifest.model_validate(manifest_raw)
    except PydanticValidationError as exc:
        raise SeedPackError(MANIFEST_INVALID, f"manifest.json: {_model_error(exc)}") from exc

    if manifest.scope != "system":
        raise SeedPackError(SCOPE_UNSUPPORTED, f"scope {manifest.scope!r} is not supported in v1")
    if manifest.license not in LICENSES:
        raise SeedPackError(LICENSE_NOT_ALLOWED, manifest.license)
    if source_priority is not None and int(source_priority) != manifest.priority:
        raise SeedPackError(
            PRIORITY_MISMATCH,
            f"source priority {source_priority} != manifest priority {manifest.priority}",
        )
    if len(manifest.item_files) > MAX_ITEM_FILES:
        raise SeedPackError(CAP_EXCEEDED, f"pack exceeds {MAX_ITEM_FILES} item files")

    resolved = connectors if connectors is not None else default_connectors()
    digest_files: list[tuple[str, bytes]] = []
    items: list[ParsedItem] = []
    skipped: list[tuple[str, int]] = []
    seen_keys: set[str] = set()

    for entry in manifest.item_files:
        _check_item_path(entry.path)
        data = files.get(entry.path)
        if data is None:
            raise SeedPackError(ITEM_FILE_MISSING, entry.path)
        if len(data) > MAX_ITEM_FILE_BYTES:
            raise SeedPackError(CAP_EXCEEDED, f"{entry.path} exceeds 5 MB")
        if sha256_hex(data) != entry.sha256:
            raise SeedPackError(DIGEST_MISMATCH, entry.path)
        digest_files.append((entry.path, data))

        envelope_payload = _loads(data, code=ITEM_FILE_INVALID, label=entry.path)
        try:
            envelope = ItemEnvelope.model_validate(envelope_payload)
        except PydanticValidationError as exc:
            raise SeedPackError(ITEM_FILE_INVALID, f"{entry.path}: {_model_error(exc)}") from exc
        meta = envelope.metadata
        if meta.license is not None and meta.license != manifest.license:
            raise SeedPackError(
                LICENSE_NOT_ALLOWED, f"{entry.path}: metadata.license must match the pack"
            )

        spec = FORMATS.get((meta.format, meta.format_version))
        if spec is None:
            if not allow_unknown_formats:
                known_format = any(key[0] == meta.format for key in FORMATS)
                code = FORMAT_VERSION_UNSUPPORTED if known_format else FORMAT_UNSUPPORTED
                raise SeedPackError(code, f"{entry.path}: {meta.format} v{meta.format_version}")
            skipped.append((meta.format, meta.format_version))
            continue
        if meta.item_type != spec.item_type:
            raise SeedPackError(
                ITEM_TYPE_MISMATCH,
                f"{entry.path}: item_type {meta.item_type!r} != {spec.item_type!r}",
            )
        if len(envelope.items) > spec.max_items:
            raise SeedPackError(
                CAP_EXCEEDED, f"{entry.path}: {len(envelope.items)} items (max {spec.max_items})"
            )
        for item in _parse_supported(
            spec,
            item_type=meta.item_type,
            format_version=meta.format_version,
            raw_items=envelope.items,
            source_file=entry.path,
            connectors=resolved,
        ):
            if item.seed_key in seen_keys:
                raise SeedPackError(SEED_KEY_DUPLICATE, item.seed_key)
            seen_keys.add(item.seed_key)
            items.append(item)

    for replaced in manifest.replaces:
        if not _SEED_BODY.match(replaced):
            raise SeedPackError(IDENTITY_INVALID, f"replaces: {replaced!r}")

    return ParsedPack(
        manifest=manifest,
        manifest_raw=manifest_raw,
        digest=compute_pack_digest(manifest_raw, digest_files),
        item_files=dict(digest_files),
        items=tuple(items),
        skipped_formats=tuple(skipped),
    )


def parse_repo_pack(index: RepoIndex, pack_id: str) -> IndexedPack:
    for pack in index.packs:
        if pack.id == pack_id:
            return pack
    raise SeedPackError(PACK_NOT_FOUND, f"pack {pack_id!r} is not in seed-repo.json")


__all__ = [
    "FORMATS",
    "LICENSES",
    "AtsPreset",
    "EndpointDescriptor",
    "EndpointParam",
    "FormatSpec",
    "IndexedPack",
    "ItemEnvelope",
    "ItemMetadata",
    "PackManifest",
    "ParsedItem",
    "ParsedPack",
    "RepoIndex",
    "canonical_json",
    "compute_pack_digest",
    "default_connectors",
    "endpoint_in_connector_domains",
    "parse_pack",
    "parse_repo_index",
    "parse_repo_pack",
    "sha256_hex",
]
