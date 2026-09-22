"""Safe YAML loading with shallow, extensible configuration contracts."""

from pathlib import Path
from typing import Any, TypeVar, overload

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ConfigError(Exception):
    """Base exception for configuration-loading failures."""


class ConfigFileNotFoundError(ConfigError):
    """The requested configuration file or repository cannot be found."""


class ConfigReadError(ConfigError):
    """A configuration file cannot be read as UTF-8 text."""


class ConfigParseError(ConfigError):
    """A configuration file is not valid safe YAML."""


class ConfigValidationError(ConfigError):
    """A document does not satisfy its configuration contract."""


class YAMLConfig(BaseModel):
    """A versioned mapping; additional YAML fields are preserved as extras.

    Nested contents remain mutable, but each load reads a fresh document.
    Domain-specific validation can be added by subclassing this model.
    """

    model_config = ConfigDict(strict=True, extra="allow")

    version: int


class DataSourcesConfig(YAMLConfig):
    """Data-source identity and structure, without provider-specific schemas."""

    description: str
    strategy: dict[str, Any] = Field(min_length=1)
    sources: dict[str, dict[str, Any]] = Field(min_length=1)


class ScoringRulesConfig(YAMLConfig):
    """Season metadata and scoring sections, without interpreting rules."""

    competition: str
    season: str
    description: str
    metadata: dict[str, Any]
    appearance: dict[str, Any] = Field(min_length=1)
    goals: dict[str, Any] = Field(min_length=1)
    bps: dict[str, Any] = Field(min_length=1)


class FPLRulesConfig(YAMLConfig):
    """Season metadata and squad, transfer and chip configuration sections."""

    competition: str
    season: str
    description: str
    metadata: dict[str, Any]
    initial_squad: dict[str, Any] = Field(min_length=1)
    transfers: dict[str, Any] = Field(min_length=1)
    chips: dict[str, Any] = Field(min_length=1)


ConfigT = TypeVar("ConfigT", bound=YAMLConfig)


@overload
def load_yaml_config(path: Path) -> YAMLConfig: ...


@overload
def load_yaml_config(path: Path, *, model: type[ConfigT]) -> ConfigT: ...


def load_yaml_config(
    path: Path, *, model: type[YAMLConfig] = YAMLConfig
) -> YAMLConfig:
    """Read a UTF-8 YAML mapping and validate its version and selected schema.

    The default contract requires an integer ``version``. Pass a subclass via
    ``model`` for a stricter contract. No document values are defaulted or cached.
    Unknown fields are retained and available through ``model_dump()``.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigFileNotFoundError(f"Configuration file not found: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise ConfigReadError(f"Cannot read configuration file '{path}': {exc}") from exc

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigParseError(f"Invalid YAML in configuration '{path}': {exc}") from exc

    if document is None:
        raise ConfigValidationError(f"Configuration '{path}' is empty or null")
    if not isinstance(document, dict):
        raise ConfigValidationError(f"Configuration '{path}' must have a mapping root")

    try:
        return model.model_validate(document)
    except ValidationError as exc:
        raise ConfigValidationError(
            f"Invalid {model.__name__} configuration '{path}': {exc}"
        ) from exc


def _canonical_path(relative_path: str, project_root: Path | None) -> Path:
    if project_root is None:
        module_path = Path(__file__).resolve()
        source_dir = module_path.parents[2]
        if source_dir.name != "src":
            raise ConfigFileNotFoundError(
                f"Cannot locate '{relative_path}' from installed module '{module_path}'. "
                "Pass project_root pointing to a checkout containing docs/."
            )
        project_root = source_dir.parent
    return Path(project_root) / relative_path


def load_data_sources_config(project_root: Path | None = None) -> DataSourcesConfig:
    """Load docs/01_DATA/data_sources.yaml relative to the explicit root or checkout."""
    return load_yaml_config(
        _canonical_path("docs/01_DATA/data_sources.yaml", project_root),
        model=DataSourcesConfig,
    )


def _season_config_path(directory: str, default_filename: str, season: str | None) -> str:
    """Return an explicit season file; a requested season never falls back."""
    if season is None:
        return f"{directory}/{default_filename}"
    return f"{directory}/{default_filename.removesuffix('.yaml')}/{season.replace('/', '_')}.yaml"


def load_scoring_rules_config(
    project_root: Path | None = None, *, season: str | None = None
) -> ScoringRulesConfig:
    """Load the default rules or the explicitly requested season's rules."""
    return load_yaml_config(
        _canonical_path(
            _season_config_path("docs/03_SIMULATION", "scoring_rules.yaml", season), project_root
        ),
        model=ScoringRulesConfig,
    )


def load_fpl_rules_config(
    project_root: Path | None = None, *, season: str | None = None
) -> FPLRulesConfig:
    """Load default optimizer rules or an explicitly requested season's rules."""
    return load_yaml_config(
        _canonical_path(
            _season_config_path("docs/04_OPTIMIZER", "fpl_rules.yaml", season), project_root
        ),
        model=FPLRulesConfig,
    )
