from app.engine.codebook_parser import DimensionDef, LabelDef
from app.engine.label_parser import parse_answer
from app.engine.prompt_generator import generate_dimension_prompt


def test_no_label_variants_normalize_to_canonical_label():
    labels = ["Emotional Support", "Functional Support", "No label"]

    assert parse_answer("Answer: N/A", labels) == "No label"
    assert parse_answer("Answer: none", labels) == "No label"
    assert parse_answer("Answer: not applicable", labels) == "No label"


def test_prompt_explains_no_label_when_available():
    dim = DimensionDef(
        name="AI Behavior Theme",
        dim_type="multi_label",
        labels=[
            LabelDef(name="Emotional Support", definition="Offers emotional support."),
            LabelDef(name="Functional Support", definition="Offers practical help."),
            LabelDef(name="No label", definition="Use when none of the themes apply."),
        ],
    )

    prompt = generate_dimension_prompt(dim)

    assert '"No label"' in prompt
    assert "none of the substantive labels apply" in prompt
    assert "Do not force a substantive label" in prompt
