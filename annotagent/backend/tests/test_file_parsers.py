from app.utils.file_parsers import parse_csv_dataset
from app.api.optimizers import _canonical_gold_labels, _label_for_dimension
from app.api.results import _match_status, _metric_gold_label


def test_parse_theme_level_csv_as_gold_labels():
    content = """Row,Response ID,Logs (Donated vs. T1/T2/T3/T4),Coding theme,Level,Time stamp,Relevant quotes 
1,R_1,Donated,Listening strategy,Question-asking,8/5/2025,"How did you come up with it?"
1,R_1,Donated,AI role,Companion,8/5/2025,"How did you come up with it?"
2,R_2,Donated,Listening strategy,Offers advice,8/5/2025,"You could try taking a short break."
"""

    items = parse_csv_dataset(content)

    assert len(items) == 2
    assert items[0]["content"] == "How did you come up with it?"
    assert items[0]["gold_labels"] == {
        "Listening strategy": "Question-asking",
        "AI role": "Companion",
    }
    assert items[1]["gold_labels"] == {
        "Listening strategy": "Offers advice",
    }


def test_parse_theme_level_csv_preserves_multiple_levels_for_same_theme():
    content = """Coding theme,Level,Relevant quotes 
Listening strategy,Question-asking,"Tell me more."
Listening strategy,Offers advice,"Tell me more."
"""

    items = parse_csv_dataset(content)

    assert len(items) == 1
    assert items[0]["gold_labels"] == {
        "Listening strategy": ["Question-asking", "Offers advice"],
    }


def test_parse_theme_level_csv_does_not_depend_on_column_order():
    content = """Label,Notes,Response,Dimension
Question-asking,reviewed,"Tell me more.",Listening strategy
Companion,reviewed,"Tell me more.",AI role
"""

    items = parse_csv_dataset(content)

    assert len(items) == 1
    assert items[0]["content"] == "Tell me more."
    assert items[0]["gold_labels"] == {
        "Listening strategy": "Question-asking",
        "AI role": "Companion",
    }


def test_parse_csv_embedded_gold_labels_json():
    content = 'sentence,gold_labels\n"hello","{""Theme"": ""Level A""}"\n'

    items = parse_csv_dataset(content)

    assert items[0]["content"] == "hello"
    assert items[0]["gold_labels"] == {"Theme": "Level A"}


def test_label_lookup_ignores_codebook_citation_suffix():
    labels = {
        "Listening strategy": "Question-asking",
        "Support type": "Emotional support",
    }

    assert (
        _label_for_dimension(labels, "Listening Strategy (Bodie et al., 2012)")
        == "Question-asking"
    )


def test_canonical_gold_labels_match_codebook_casing_and_punctuation():
    valid_labels = [
        "Question-Asking",
        "Sympathetic Responsiveness",
        "Offers Advice, Opinions, Perspectives, And Personal Experience",
    ]

    assert _canonical_gold_labels("Question-asking", valid_labels) == ["Question-Asking"]
    assert _canonical_gold_labels(
        ["Question-asking", "Sympathetic responsiveness"],
        valid_labels,
    ) == ["Question-Asking", "Sympathetic Responsiveness"]
    assert _canonical_gold_labels(
        "Offers advice, opinions, perspectives, and personal experience",
        valid_labels,
    ) == ["Offers Advice, Opinions, Perspectives, And Personal Experience"]


def test_feedback_evidence_marks_list_gold_as_partial_match():
    gold = ["Question-asking", "Sympathetic responsiveness", "Paraphrase"]

    assert _match_status("Sympathetic Responsiveness", gold) == "partial"
    assert _match_status("Humor", gold) == "mismatch"


def test_metric_gold_label_counts_matching_list_item_as_correct_target():
    gold = ["Question-asking", "Sympathetic responsiveness", "Paraphrase"]

    assert _metric_gold_label("Sympathetic Responsiveness", gold) == "Sympathetic Responsiveness"
    assert _metric_gold_label("Humor", gold) == "Question-asking"
    assert _metric_gold_label("Back-Channel Response", "Back-channel response") == "Back-Channel Response"
