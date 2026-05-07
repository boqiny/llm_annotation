"""Canonical enums, label maps, and helpers for self-disclosure annotation."""
from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


class Topic(str, Enum):
    CAUSAL_CONVERSATION = "Causal conversation"
    CURRENT_LIFE_CHALLENGES = "Current life challenges"
    DESIRE_FOR_FRIENDSHIP = "Desire for friendship"
    EMOTIONAL_DISTRESS = "Emotional distress"
    EMOTIONAL_RESPONSE = "Emotional response"
    FINANCIAL_STRUGGLES = "Financial struggles"
    FUTURE_PLANS = "Future plans"
    INFORMATION_AND_ADVICE = "Information and advice"
    INTERPERSONAL_ISSUE = "Interpersonal issue"
    INTIMATE_EXCHANGE = "Intimate exchange"
    PHILOSOPHICAL_PERSPECTIVE = "Philosophical perspective"
    WORK_STRESS = "Work stress"


class TopicCategory(str, Enum):
    CAUSAL_EXCHANGE = "Causal exchange"
    EMOTIONAL_AND_SOCIAL_SUPPORT = "Emotional and social support"
    EMOTIONAL_DISCLOSURE = "Emotional disclosure"
    KNOWLEDGE_SEEKING = "Knowledge seeking"
    PHILOSOPHICAL_AND_MORAL_INQUIRY = "Philosophical and moral inquiry"
    ROMANTIC_AND_SEXUAL_INTERACTIONS = "Romantic and sexual interactions"


class LevelOfDisclosureLabel(str, Enum):
    HIGH = "High"
    LOW = "Low"
    NO = "No"


class DepthOfDisclosureLabel(str, Enum):
    PERIPHERAL = "Peripheral"
    INTERMEDIATE = "Intermediate"
    CENTRAL = "Central"


class IntimacyOfDisclosureLabel(str, Enum):
    PERIPHERAL = "Peripheral"
    INTERMEDIATE = "Intermediate"
    CORE = "Core"


class ConfessionLabel(str, Enum):
    YES = "Yes, it's a confession"
    NO = "No, it's not a confession"


class TemporalityLabel(str, Enum):
    PAST = "Past"
    NOW = "Now"
    FUTURE = "Future"


CANONICAL_TOPICS = tuple(topic.value for topic in Topic)
CANONICAL_TOPIC_CATEGORIES = tuple(cat.value for cat in TopicCategory)

LABEL_SCHEMES = (
    "Level of disclosure",
    "Depth of disclosure",
    "Intimacy of self-disclosure",
    "Disclosure as confession",
    "Temporality",
)

TOPIC_TO_CATEGORY: Dict[str, str] = {
    Topic.CAUSAL_CONVERSATION.value: TopicCategory.CAUSAL_EXCHANGE.value,
    Topic.CURRENT_LIFE_CHALLENGES.value: TopicCategory.EMOTIONAL_AND_SOCIAL_SUPPORT.value,
    Topic.DESIRE_FOR_FRIENDSHIP.value: TopicCategory.EMOTIONAL_AND_SOCIAL_SUPPORT.value,
    Topic.EMOTIONAL_DISTRESS.value: TopicCategory.EMOTIONAL_AND_SOCIAL_SUPPORT.value,
    Topic.EMOTIONAL_RESPONSE.value: TopicCategory.EMOTIONAL_AND_SOCIAL_SUPPORT.value,
    Topic.FINANCIAL_STRUGGLES.value: TopicCategory.KNOWLEDGE_SEEKING.value,
    Topic.FUTURE_PLANS.value: TopicCategory.KNOWLEDGE_SEEKING.value,
    Topic.INFORMATION_AND_ADVICE.value: TopicCategory.KNOWLEDGE_SEEKING.value,
    Topic.INTERPERSONAL_ISSUE.value: TopicCategory.EMOTIONAL_DISCLOSURE.value,
    Topic.INTIMATE_EXCHANGE.value: TopicCategory.ROMANTIC_AND_SEXUAL_INTERACTIONS.value,
    Topic.PHILOSOPHICAL_PERSPECTIVE.value: TopicCategory.PHILOSOPHICAL_AND_MORAL_INQUIRY.value,
    Topic.WORK_STRESS.value: TopicCategory.EMOTIONAL_AND_SOCIAL_SUPPORT.value,
}

SCHEME_NAME_MAP: Dict[str, str] = {
    "Level of disclosure": "Level of disclosure",
    "Depth of disclosure": "Depth of disclosure",
    "Depth of dislcosure": "Depth of disclosure",
    "Depth of dislcosure ": "Depth of disclosure",
    "depth of dislcosure": "Depth of disclosure",
    "Disclosure as confession": "Disclosure as confession",
    "Intimacy of self-disclosure": "Intimacy of self-disclosure",
    "Initmacy of self-disclosure": "Intimacy of self-disclosure",
    "intimacy of self-disclosure": "Intimacy of self-disclosure",
    "Temporality": "Temporality",
    "temporality": "Temporality",
}

LEVEL_MAP_BY_SCHEME: Dict[str, Dict[str, str]] = {
    "Level of disclosure": {
        "High": "High", "High ": "High", "high": "High",
        "Low": "Low", "Low ": "Low", "low": "Low",
        "No": "No", "No ": "No", "no": "No",
    },
    "Depth of disclosure": {
        "Peripheral": "Peripheral", "Peripheral layer": "Peripheral",
        "Intermediate": "Intermediate", "Intermediate layer": "Intermediate",
        "Intermediate level": "Intermediate",
        "Central": "Central", "Central layer": "Central", "central layer": "Central",
    },
    "Intimacy of self-disclosure": {
        "Peripheral": "Peripheral", "Peripheral layer": "Peripheral",
        "Peripheral level": "Peripheral", "Peripheral level ": "Peripheral",
        "Intermediate": "Intermediate", "Intermediate layer": "Intermediate",
        "Intermediate level": "Intermediate",
        "Core": "Core", "Core layer": "Core", "core layer": "Core",
    },
    "Disclosure as confession": {
        "Yes, it's a confession": "Yes, it's a confession",
        "No": "No, it's not a confession",
        "No, it's not a confession": "No, it's not a confession",
        "No, it is not a confession": "No, it's not a confession",
    },
    "Temporality": {
        "Past": "Past", "past": "Past",
        "Now": "Now", "now": "Now",
        "Present": "Now", "present": "Now",
        "Future": "Future", "future": "Future",
    },
}

TOPIC_ALIASES: Dict[str, str] = {t.value.lower(): t.value for t in Topic}
TOPIC_CATEGORY_ALIASES: Dict[str, str] = {
    "causal exchange": TopicCategory.CAUSAL_EXCHANGE.value,
    "emotional and social support": TopicCategory.EMOTIONAL_AND_SOCIAL_SUPPORT.value,
    "emotional disclosure": TopicCategory.EMOTIONAL_DISCLOSURE.value,
    "knowledge seeking": TopicCategory.KNOWLEDGE_SEEKING.value,
    "philosophical and moral inquiry": TopicCategory.PHILOSOPHICAL_AND_MORAL_INQUIRY.value,
    "romantic and sexual interactions": TopicCategory.ROMANTIC_AND_SEXUAL_INTERACTIONS.value,
}


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def canonicalize_scheme(raw: object) -> str:
    return SCHEME_NAME_MAP.get(normalize_text(raw), "")


def canonicalize_level(raw_scheme: object, raw_level: object) -> str:
    scheme = canonicalize_scheme(raw_scheme)
    if not scheme:
        return ""
    return LEVEL_MAP_BY_SCHEME.get(scheme, {}).get(normalize_text(raw_level), "")


def canonicalize_topic(raw: object) -> str:
    val = normalize_text(raw)
    if not val:
        return ""
    return TOPIC_ALIASES.get(val.lower(), val)


def canonicalize_topic_category(raw: object) -> str:
    val = normalize_text(raw)
    if not val:
        return ""
    return TOPIC_CATEGORY_ALIASES.get(val.lower(), val)


def canonical_topic_category_for_topic(topic: object) -> str:
    return TOPIC_TO_CATEGORY.get(canonicalize_topic(topic), "")
