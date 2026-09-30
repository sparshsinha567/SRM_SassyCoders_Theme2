import json
import re
from typing import List, Optional

from llm_client import llm_complete
from retrieval import DeeplinkIndex, DeeplinkEntry
from schema import Goal, Action, StepGroup, Deeplink, actionCategory, ContextDeeplinkResponse, ValidationDeepLink

_URL_RE = re.compile(r"(https?://\S+|www\.\S+|\[[^\]]+\]\([^)]+\))", re.IGNORECASE)

_SYSTEM = """You convert a customer device complaint (plus optional internal
reference text) into a single troubleshooting Goal as JSON, following this
EXACT contract:

{
  "goal": "Follow these steps to perform this <Topic> Troubleshooting",
  "title": "<2 to 3 words, sentence case, e.g. Swipe navigation settings>",
  "score": <float 0.0-1.0 confidence>,
  "actions": [
    {
      "actionName": "<Title Case, exactly one physical screen/feature>",
      "description": "<exactly 5 to 7 words, starting with 'It will'>",
      "category": "auto" | "manual" | "critical",
      "stepGroups": [ { "steps": ["<imperative UI step, one action per step, no URLs>", ...] } ]
    }
  ]
}

Rules:
- Absolute prohibition of web URLs (http, https, www., markdown links). Zero URL leaks.
- "critical" category (factory reset, restart, firmware update, safe mode) must be the LAST action.
- "manual" category (physical cleaning, hardware repair, service center) cannot carry deeplinks.
- "auto" category represents standard device settings screens.
- If reference text is provided, extract applicable troubleshooting, diagnostic, configuration, and resolution steps purely from the provided text to resolve or investigate the customer's reported symptoms (e.g. multi-window layouts, screen rotation, diagnostic resets, safe mode, customer support). Do not invent outside URLs or unrelated steps. Only return {"goal": "", "title": "", "score": 0.0, "actions": []} if the reference text is completely blank or completely unrelated to mobile devices.
- Respond with ONLY the JSON object. No prose, no markdown fences."""


def _clean_json_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def extract_goal(query: str, siis_response: Optional[str] = None, return_usage: bool = False):
    prompt = f'query: "{query}"'
    if siis_response:
        prompt += f'\nreference_text: "{siis_response}"'
    prompt += "\n\nExtract the structured Goal JSON."

    if return_usage:
        raw, usage = llm_complete(_SYSTEM, prompt, return_usage=True)
    else:
        raw = llm_complete(_SYSTEM, prompt)
        usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": "stub"}

    try:
        parsed = json.loads(_clean_json_markdown(raw))
    except json.JSONDecodeError:
        parsed = {"goal": "", "title": "", "score": 0.0, "actions": []}

    return (parsed, usage) if return_usage else parsed


def _strip_urls(text: str) -> str:
    return _URL_RE.sub("", text).strip()


def _enforce_description_length(desc: str) -> str:
    """Clamps and pads description to exactly 5 to 7 words total, starting with 'It will'.
    Strips any existing 'it will' prefix first so real content words are never overwritten."""
    desc = _strip_urls(desc).strip()
    # Strip any existing 'it will' prefix (case-insensitive) to isolate true content words
    content = re.sub(r"^it\s+will\s+", "", desc, flags=re.IGNORECASE).strip()
    raw_content_words = [w.rstrip(".!?,;") for w in content.split() if w.strip()]

    # If no content words were left, supply fallback
    if not raw_content_words:
        raw_content_words = ["guide", "steps", "to", "resolve"]

    # Prepend clean 'It will' to genuine content words without positional overwriting
    words = ["It", "will"] + raw_content_words

    # Pad if under 5 words total
    fallback_padding = ["guide", "steps", "to", "resolve", "safely"]
    if len(words) < 5:
        words.extend(fallback_padding[: 5 - len(words)])

    # Clamp if over 7 words total
    if len(words) > 7:
        words = words[:7]

    return " ".join(words)


def _enforce_title_syntax(title: str, query: str = "") -> str:
    """Enforces title to 2-3 words in sentence case (e.g. 'Swipe navigation settings')."""
    words = re.findall(r"[A-Za-z0-9]+", _strip_urls(title))
    if len(words) < 2 and query:
        query_words = re.findall(r"[A-Za-z0-9]+", _strip_urls(query))
        words = query_words if len(query_words) >= 2 else words + ["settings"]
    if len(words) < 2:
        words = words + ["settings"] if words else ["device", "issue"]
    words = words[:3]
    return words[0].capitalize() + " " + " ".join(w.lower() for w in words[1:])


def _enforce_goal_syntax(goal: str, title: str, query: str = "") -> str:
    """Enforces exact syntax: Follow these steps to perform this <Topic> Troubleshooting"""
    prefix = "Follow these steps to perform this "
    suffix_troubleshoot = " Troubleshooting"
    suffix_config = " Configuration"

    clean_goal = _strip_urls(goal).strip()
    if clean_goal.startswith(prefix) and (
        clean_goal.endswith(suffix_troubleshoot) or clean_goal.endswith(suffix_config)
    ):
        return clean_goal

    topic_source = title if title else query
    topic_words = re.findall(r"[A-Za-z0-9]+", topic_source)
    topic = " ".join(w.capitalize() for w in topic_words[:4]) if topic_words else "Device"
    return f"{prefix}{topic}{suffix_troubleshoot}"


MIN_MATCH_CONFIDENCE = 0.40


def _enforce_one_action_one_screen(actions: List[Action]) -> tuple[List[Action], int]:
    """Programmatically enforces the 'One Action = One Screen' constraint:
    1. Detects intra-action step group screen disagreements: if step groups in one action
       resolve to different screens, tracks disagreement counter and splits divergent groups
       into distinct Action cards rather than silently overwriting them.
    2. Inter-action de-duplication: when two distinct auto actions target the exact same URI,
       merges their step groups into the primary action so no user rationales are lost.
    """
    disagreement_count = 0
    split_actions: List[Action] = []

    # 1. Intra-Action Screen Resolution
    for action in actions:
        if action.category != actionCategory.auto or len(action.stepGroups) <= 1:
            split_actions.append(action)
            continue

        # Check for screen divergence among step groups
        primary_dl = next((sg.actionableDeeplink.deeplink for sg in action.stepGroups if sg.actionableDeeplink), None)
        divergent_groups = []
        conforming_groups = []

        for sg in action.stepGroups:
            sg_dl = sg.actionableDeeplink.deeplink if sg.actionableDeeplink else None
            if sg_dl and primary_dl and sg_dl != primary_dl:
                disagreement_count += 1
                divergent_groups.append(sg)
            else:
                conforming_groups.append(sg)

        if divergent_groups:
            # Keep conforming groups in primary action
            action.stepGroups = conforming_groups if conforming_groups else [divergent_groups[0]]
            split_actions.append(action)
            # Spawn distinct action cards for divergent step groups (preserving both screens)
            for div_sg in (divergent_groups if conforming_groups else divergent_groups[1:]):
                split_actions.append(
                    Action(
                        actionName=f"{action.actionName} (Secondary)",
                        description=action.description,
                        category=action.category,
                        stepGroups=[div_sg],
                    )
                )
        else:
            split_actions.append(action)

    # 2. Inter-Action Screen Merging (merge steps instead of dropping rationale)
    merged_actions: List[Action] = []
    uri_to_action: dict[str, Action] = {}

    for action in split_actions:
        primary_dl = next((sg.actionableDeeplink.deeplink for sg in action.stepGroups if sg.actionableDeeplink), None)
        if primary_dl and action.category == actionCategory.auto and primary_dl not in ("voiceassist://dummy_positive", "bixby://dummy_positive"):
            if primary_dl in uri_to_action:
                # Merge step groups into the existing action so no steps are lost
                uri_to_action[primary_dl].stepGroups.extend(action.stepGroups)
            else:
                uri_to_action[primary_dl] = action
                merged_actions.append(action)
        else:
            merged_actions.append(action)

    return merged_actions, disagreement_count


def resolve_and_order(
    raw_goal: dict,
    deeplink_index: DeeplinkIndex,
    query: str = "",
    return_margin: bool = False,
):
    """Resolves step groups to catalog deeplinks, enforces confidence thresholding,
    and programmatically guarantees the 'One Action = One Screen' contract."""
    if not raw_goal.get("actions"):
        return (None, None) if return_margin else None

    actions: List[Action] = []
    match_confidences: List[float] = []
    match_margins: List[float] = []
    placeholder = getattr(deeplink_index, "placeholder_uri", "voiceassist://dummy_positive")

    for raw_action in raw_goal["actions"]:
        category_str = raw_action.get("category", "manual")
        try:
            category = actionCategory(category_str)
        except ValueError:
            category = actionCategory.manual

        step_groups: List[StepGroup] = []
        for raw_group in raw_action.get("stepGroups", []):
            steps = [_strip_urls(s) for s in raw_group.get("steps", []) if _strip_urls(s)]
            if not steps:
                continue
            query_for_match = f"{raw_action.get('actionName', '')} {' '.join(steps)}"
            match, score, margin = deeplink_index.best_match_with_margin(query_for_match)

            actionable = None
            validation_dl = None
            if category == actionCategory.manual:
                # Rule 4.1: Manual interventions cannot carry an actionable deeplink
                actionable = None
                validation_dl = None
            else:
                # Brief Contract: Gate on confidence threshold; fallback to dummy_positive when quality is low
                if match and score >= MIN_MATCH_CONFIDENCE:
                    match_confidences.append(score)
                    match_margins.append(margin)
                    actionable = Deeplink(
                        deeplink=match.deeplink,
                        description=match.description,
                        message=match.message,
                        originalType=match.original_type,
                    )
                    if match.validation:
                        try:
                            validation_dl = ValidationDeepLink(**match.validation)
                        except Exception:
                            validation_dl = None
                elif category == actionCategory.auto:
                    # Fetch real static catalog entry for dummy_positive directly from catalog
                    dummy_entry = getattr(deeplink_index, "get_placeholder_entry", lambda: None)()
                    if dummy_entry:
                        actionable = Deeplink(
                            deeplink=dummy_entry.deeplink,
                            description=dummy_entry.description,
                            message=dummy_entry.message,
                            originalType=dummy_entry.original_type,
                        )
                    else:
                        actionable = Deeplink(
                            deeplink=placeholder,
                            description="Generic placeholder for a Settings screen that has no dedicated entry in this catalog",
                            message="Open the relevant Settings screen",
                            originalType="placeholder",
                        )
                    validation_dl = None
                    match_confidences.append(score if score > 0 else 0.5)

            step_groups.append(StepGroup(steps=steps, actionableDeeplink=actionable, validationDeeplink=validation_dl))

        if step_groups:
            actions.append(
                Action(
                    actionName=raw_action.get("actionName", "").strip().title() or "Device Settings",
                    description=_enforce_description_length(raw_action.get("description", "")),
                    category=category,
                    stepGroups=step_groups,
                )
            )

    if not actions:
        return (None, None) if return_margin else None

    # Programmatic Hard Constraint: One Action = One Screen
    actions, disagreement_count = _enforce_one_action_one_screen(actions)

    order_rank = {actionCategory.auto: 0, actionCategory.manual: 1, actionCategory.critical: 2}
    actions.sort(key=lambda a: order_rank.get(a.category, 1))

    # Ground Goal score in deterministic retrieval evidence: weakest action confidence
    deterministic_score = round(min(match_confidences), 2) if match_confidences else 0.5
    primary_margin = match_margins[0] if match_margins else None
    reported_margin = primary_margin if primary_margin is not None else None

    clean_title = _enforce_title_syntax(raw_goal.get("title", ""), query=query)
    clean_goal = _enforce_goal_syntax(raw_goal.get("goal", ""), title=clean_title, query=query)

    goal = Goal(
        goal=clean_goal,
        title=clean_title,
        actions=actions,
        score=deterministic_score,
    )
    if return_margin:
        return goal, reported_margin
    return goal


def build_response(
    query: str,
    siis_response: Optional[str],
    deeplink_index: DeeplinkIndex,
    return_margin: bool = False,
    return_usage: bool = False,
):
    if return_usage:
        raw_goal, usage = extract_goal(query, siis_response, return_usage=True)
    else:
        raw_goal = extract_goal(query, siis_response)
        usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model": "stub"}

    if return_margin:
        goal, margin = resolve_and_order(raw_goal, deeplink_index, query=query, return_margin=True)
        resp = ContextDeeplinkResponse(contexts=[] if goal is None else [goal])
        if return_usage:
            return resp, margin, usage
        return resp, margin
    else:
        goal = resolve_and_order(raw_goal, deeplink_index, query=query)
        resp = ContextDeeplinkResponse(contexts=[] if goal is None else [goal])
        if return_usage:
            return resp, usage
        return resp

