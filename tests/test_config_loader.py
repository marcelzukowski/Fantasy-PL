"""CORE-003 configuration contracts, errors and repository path handling."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fpl_engine.config import loader
from fpl_engine.config.loader import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigReadError,
    ConfigValidationError,
    DataSourcesConfig,
    FPLRulesConfig,
    ScoringRulesConfig,
    YAMLConfig,
    load_data_sources_config,
    load_fpl_rules_config,
    load_scoring_rules_config,
    load_yaml_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CONFIGS = [
    (load_data_sources_config, DataSourcesConfig, "docs/01_DATA/data_sources.yaml"),
    (load_scoring_rules_config, ScoringRulesConfig, "docs/03_SIMULATION/scoring_rules.yaml"),
    (load_fpl_rules_config, FPLRulesConfig, "docs/04_OPTIMIZER/fpl_rules.yaml"),
]


def write_config(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_generic_mapping_preserves_nested_content(tmp_path):
    path = write_config(
        tmp_path,
        "version: 1\nsettings:\n  label: 'Zażółć'\n  values: [null, false, 0, 1.5]\n",
    )
    config = load_yaml_config(path)

    assert isinstance(config, YAMLConfig)
    assert config.version == 1
    assert config.model_dump() == yaml.safe_load(path.read_text(encoding="utf-8"))
    assert config.settings["values"] == [None, False, 0, 1.5]


def test_missing_file_reports_path_and_cause(tmp_path):
    path = tmp_path / "missing.yaml"
    with pytest.raises(ConfigFileNotFoundError) as error:
        load_yaml_config(path)
    assert isinstance(error.value, ConfigError)
    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, FileNotFoundError)


def test_unreadable_file_reports_path_and_cause(tmp_path, monkeypatch):
    path = write_config(tmp_path, "version: 1\n")

    def deny_read(self, *args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_text", deny_read)
    with pytest.raises(ConfigReadError) as error:
        load_yaml_config(path)
    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, PermissionError)


def test_invalid_encoding_reports_read_error(tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ConfigReadError) as error:
        load_yaml_config(path)
    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, UnicodeError)


@pytest.mark.parametrize(
    "text",
    [
        "version: [1\n",
        "version: 1\n---\nversion: 2\n",
        "!!python/object/apply:builtins.list []\n",
        "```yaml\nversion: 1\n```\n",
    ],
)
def test_invalid_or_unsafe_yaml_reports_parse_error(tmp_path, text):
    path = write_config(tmp_path, text)
    with pytest.raises(ConfigParseError) as error:
        load_yaml_config(path)
    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, yaml.YAMLError)


@pytest.mark.parametrize("text", ["", "# comment only\n", "null\n", "[]", "[1, 2]", "42", "hello"])
def test_empty_or_non_mapping_document_fails(tmp_path, text):
    path = write_config(tmp_path, text)
    with pytest.raises(ConfigValidationError) as error:
        load_yaml_config(path)
    assert str(path) in str(error.value)


@pytest.mark.parametrize("text", ["{}", "settings: {}", "version: '1'", "version: true", "version: 1.0", "version: null", "version: []"])
def test_missing_or_invalid_version_is_not_coerced(tmp_path, text):
    path = write_config(tmp_path, text)
    with pytest.raises(ConfigValidationError) as error:
        load_yaml_config(path)
    assert str(path) in str(error.value)
    assert isinstance(error.value.__cause__, ValidationError)


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_canonical_document_loads_completely_without_modifying_source(load, model, relative_path):
    path = PROJECT_ROOT / relative_path
    before = path.read_bytes()
    expected = yaml.safe_load(before)

    config = load()

    assert isinstance(config, model)
    assert config.version == expected["version"]
    assert config.description == expected["description"]
    if "season" in expected:
        assert config.season == expected["season"]
        assert config.competition == expected["competition"]
        assert config.metadata == expected["metadata"]
    assert config.model_dump() == expected
    assert path.read_bytes() == before


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_canonical_loader_is_independent_of_cwd(load, model, relative_path, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert isinstance(load(), model)
    assert isinstance(load(project_root=PROJECT_ROOT), model)


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_explicit_project_root_uses_its_own_document(load, model, relative_path, tmp_path, monkeypatch):
    document = yaml.safe_load((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    document["version"] = 99
    document["new_section"] = {"nested": [1, None, "future schema"]}
    destination = tmp_path / relative_path
    destination.parent.mkdir(parents=True)
    destination.write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.chdir(destination.parent)

    assert load(project_root=tmp_path).model_dump() == document


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_explicit_root_does_not_fall_back_to_checkout(load, model, relative_path, tmp_path):
    with pytest.raises(ConfigFileNotFoundError) as error:
        load(project_root=tmp_path)
    assert str(tmp_path / relative_path) in str(error.value)


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_canonical_required_fields_are_enforced(load, model, relative_path, tmp_path):
    original = yaml.safe_load((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    for field in model.model_fields:
        document = original.copy()
        del document[field]
        path = write_config(tmp_path, yaml.safe_dump(document))
        with pytest.raises(ConfigValidationError) as error:
            load_yaml_config(path, model=model)
        assert field in str(error.value)
        assert str(path) in str(error.value)


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_canonical_field_types_are_enforced(load, model, relative_path, tmp_path):
    original = yaml.safe_load((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    for field in model.model_fields:
        document = original.copy()
        document[field] = []
        path = write_config(tmp_path, yaml.safe_dump(document))
        with pytest.raises(ConfigValidationError) as error:
            load_yaml_config(path, model=model)
        assert field in str(error.value)


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_other_canonical_documents_are_rejected(load, model, relative_path, tmp_path):
    destination = tmp_path / relative_path
    destination.parent.mkdir(parents=True)
    for _, other_model, other_path in CANONICAL_CONFIGS:
        if other_model is model:
            continue
        destination.write_bytes((PROJECT_ROOT / other_path).read_bytes())
        with pytest.raises(ConfigValidationError):
            load(project_root=tmp_path)


def test_loads_do_not_share_mutable_state(tmp_path):
    path = write_config(tmp_path, "version: 1\nsettings:\n  values: [1, 2]\n")
    before = path.read_bytes()
    first = load_yaml_config(path)
    second = load_yaml_config(path)
    first.settings["values"].append(3)

    assert second.settings["values"] == [1, 2]
    assert load_yaml_config(path).settings["values"] == [1, 2]
    assert path.read_bytes() == before


def test_custom_schema_can_extend_loader(tmp_path):
    class CustomConfig(YAMLConfig):
        label: str

    path = write_config(tmp_path, "version: 1\nlabel: example\nunknown: [1, 2]\n")
    config = load_yaml_config(path, model=CustomConfig)
    assert isinstance(config, CustomConfig)
    assert config.label == "example"
    assert config.model_dump()["unknown"] == [1, 2]


@pytest.mark.parametrize("load, model, relative_path", CANONICAL_CONFIGS)
def test_installed_module_requires_explicit_root(load, model, relative_path, tmp_path, monkeypatch):
    installed_path = tmp_path / "site-packages/fpl_engine/config/loader.py"
    monkeypatch.setattr(loader, "__file__", str(installed_path))
    with pytest.raises(ConfigFileNotFoundError) as error:
        load()
    assert str(installed_path) in str(error.value)
    assert "project_root" in str(error.value)
    assert isinstance(load(project_root=PROJECT_ROOT), model)
