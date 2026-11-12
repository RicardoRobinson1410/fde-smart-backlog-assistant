"""LLM execution helpers using LangChain LCEL."""

from __future__ import annotations
import warnings
from typing import TYPE_CHECKING

warnings.filterwarnings("ignore", category=UserWarning, module="langchain_core")
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backlog_assistant.config import ScenarioConfig
from backlog_assistant.models import ExistingBacklogItem, LLMExtractionPayload
from backlog_assistant.prompts import build_system_prompt, build_user_prompt


def call_langchain_structured(
    doc_text: str,
    existing_items: list[ExistingBacklogItem],
    source_name: str,
    cfg: ScenarioConfig,
    api_key: str,
    model_id: str | None = None,
) -> LLMExtractionPayload:
    """Execute LangChain LCEL chain (`ChatPromptTemplate | ChatOpenAI.with_structured_output`)."""
    prompt = ChatPromptTemplate.from_messages([("system", "{system_prompt}"), ("human", "{user_prompt}")])
    llm = ChatOpenAI(
        api_key=api_key,
        model=model_id or cfg.subagent_models.extractor_agent,
        temperature=cfg.temperature,
        timeout=cfg.timeout_seconds,
        max_retries=cfg.max_retries,
    )
    chain = prompt | llm.with_structured_output(LLMExtractionPayload)
    res = chain.invoke({
        "system_prompt": build_system_prompt(cfg),
        "user_prompt": build_user_prompt(doc_text, existing_items, cfg, source_name),
    })
    return LLMExtractionPayload.model_validate(res)
