"""Scenario-driven configuration loader supporting JSON presets, env vars, and runtime overrides."""

from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()
DEFAULT_CONFIG_PATH = Path("config/scenario_config.json")


class PathsConfig(BaseModel):
    baseline_backlog: str = "data/existing_backlog.json"
    samples_dir: str = "data/samples"
    expected_outputs_dir: str = "data/expected_outputs"


class GitHubConfig(BaseModel):
    enabled: bool = False
    repo: str = "RicardoRobinson1410/fde-smart-backlog-assistant"
    issue_labels: list[str] = Field(default_factory=lambda: ["fde-generated", "backlog-assistant"])


class ScenarioConfig(BaseModel):
    """Centralized, hot-swappable variables defining the problem domain, persona, and rubric."""
    scenario_id: str = "smart_backlog_assistant"
    project_title: str = "Smart Backlog Assistant (FDE Edition)"
    domain_name: str = "Enterprise Cloud & FinTech Engineering"
    domain_description: str = "Transforms unstructured notes and PDFs into structured, deduplicated stories."
    agent_role: str = "Staff Forward Deployed Engineer (FDE) and Agile Technical Product Manager"
    output_item_label: str = "User Story"
    id_prefix: str = "STORY"
    story_template: str = "As a <persona>, I want <goal>, so that <measurable benefit>"
    min_acceptance_criteria: int = 3
    categories: list[str] = Field(default_factory=lambda: ["Feature", "Security/Compliance", "Reliability/Tech Debt", "Performance"])
    priority_levels: list[str] = Field(default_factory=lambda: ["P0 - Critical", "P1 - High", "P2 - Medium", "P3 - Low"])
    priority_rubric: dict[str, str] = Field(default_factory=dict)
    estimation_scale: list[int] = Field(default_factory=lambda: [1, 2, 3, 5, 8, 13])
    custom_constraints: list[str] = Field(default_factory=list)
    llm_model: str = "gpt-4o-mini"
    temperature: float = 0.1
    max_retries: int = 2
    timeout_seconds: int = 45
    paths: PathsConfig = Field(default_factory=PathsConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)

    def with_overrides(self, overrides: dict[str, Any] | None = None) -> ScenarioConfig:
        """Return a new ScenarioConfig with dotted or top-level key overrides applied."""
        if not overrides:
            return self
        data = self.model_dump()
        for key, value in overrides.items():
            if "." in key:
                sec, sub = key.split(".", 1)
                if sec in data and isinstance(data[sec], dict):
                    data[sec][sub] = value
            elif key in data:
                data[key] = value
        return ScenarioConfig.model_validate(data)


def load_scenario_config(config_path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> ScenarioConfig:
    """Load ScenarioConfig from JSON file, apply environment variables, then apply explicit overrides."""
    resolved = Path(config_path or os.getenv("SCENARIO_CONFIG_PATH") or DEFAULT_CONFIG_PATH)
    cfg = ScenarioConfig.model_validate(json.loads(resolved.read_text(encoding="utf-8")) if resolved.exists() else {})
    env_map = {
        "OPENAI_MODEL": "llm_model",
        "FDE_DOMAIN_NAME": "domain_name",
        "FDE_AGENT_ROLE": "agent_role",
        "FDE_ID_PREFIX": "id_prefix",
        "GITHUB_REPO": "github.repo",
    }
    env_overrides = {field: os.getenv(k, "").strip() for k, field in env_map.items() if os.getenv(k, "").strip()}
    return cfg.with_overrides(env_overrides).with_overrides(overrides)
