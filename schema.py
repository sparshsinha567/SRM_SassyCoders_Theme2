"""
Data contract for the Smart Guided Troubleshooting Engine.
Mirrors Appendix A of the Theme 2 brief exactly so judged output validates
against the reference schema without modification.
"""
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class BaseDeeplink(BaseModel):
    deeplink: str


class Deeplink(BaseDeeplink):
    description: str
    message: Optional[str] = ""
    classes: Optional[Dict[str, str]] = None
    originalType: Optional[str] = None


class Condition(str, Enum):
    greater = "greater"
    equal = "equal"
    less = "less"


class ResultTypes(str, Enum):
    boolean = "boolean"
    intNum = "integer"
    string = "str"
    floatNum = "float"


class actionCategory(str, Enum):
    auto = "auto"
    manual = "manual"
    critical = "critical"


class ValidationDeepLink(BaseDeeplink):
    key: str
    resultType: Optional[ResultTypes] = None
    condition: Optional[Condition] = None
    value: Optional[str] = None


class StepGroup(BaseModel):
    steps: List[str]
    validationDeeplink: Optional[ValidationDeepLink] = None
    actionableDeeplink: Optional[Deeplink] = None

    def __init__(self, **data):
        if "validationDeepLink" in data and "validationDeeplink" not in data:
            data["validationDeeplink"] = data.pop("validationDeepLink")
        super().__init__(**data)

    @property
    def validationDeepLink(self) -> Optional[ValidationDeepLink]:
        return self.validationDeeplink


class Action(BaseModel):
    actionName: str
    description: str
    stepGroups: List[StepGroup]
    category: Optional[actionCategory] = actionCategory.manual


class Goal(BaseModel):
    goal: str
    title: str
    actions: List[Action]
    score: float


class ContextDeepLinkResponse(BaseModel):
    """RAG response containing a list of Goal objects."""
    contexts: List[Goal] = []


# Alias for backward compatibility
ContextDeeplinkResponse = ContextDeepLinkResponse


# --- Additional models used by this reference implementation only ---
# (Not part of the graded contract, but useful for internal plumbing.)

class TroubleshootRequest(BaseModel):
    query: str
    siis_response: Optional[str] = Field(default=None, alias="siis_response")

    class Config:
        populate_by_name = True


class ResponseMeta(BaseModel):
    latency_ms: float
    cache_hit: bool
    cache_hit_type: str
    model: str
    cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    fallback: Optional[str] = None
    confidence_margin: Optional[float] = None


class TroubleshootResponse(BaseModel):
    query: str
    query_variations: List[str] = []
    response: ContextDeeplinkResponse
    meta: ResponseMeta
