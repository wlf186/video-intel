import pytest

from video_intel.prompts import (
    BASE_FIELDS,
    FIRST_FRAME,
    HEADINGS,
    REFERENCE_FIELDS,
    compile_prompt,
)


@pytest.mark.parametrize("mode,count", [("t2v", 0), ("i2v", 1), ("r2v", 1), ("r2v", 3)])
def test_official_structure_and_audio_defaults(mode, count):
    prompt = "A woman (S1) says: <d>[Chinese] 你好！</d> The cup lands with a clink."
    result = compile_prompt(prompt, mode=mode, count=count)
    effective = result["effective_prompt"]
    assert tuple(HEADINGS.findall(effective)) == (
        REFERENCE_FIELDS if mode == "r2v" else BASE_FIELDS
    )
    assert effective.count(prompt) == 1
    assert effective.count(FIRST_FRAME) == (1 if mode == "i2v" else 0)
    assert "No dialogue" not in effective
    assert effective.endswith("non_diegetic_music:\nN/A")
    assert not result["prompt_warnings"]


def test_reference_order_and_custom_score():
    result = compile_prompt(
        "[Shot 1] <Subject 1> holds <Subject 3>; <Subject 2> lies nearby.",
        "Light wind.",
        "r2v",
        3,
        music="Sparse piano notes.",
        reference_descriptions=[
            "The person in blue.",
            "The orange basketball.",
            "The white coffee cup.",
        ],
    )
    prompt = result["effective_prompt"]
    assert (
        "<Subject 2> is the main visible subject in <Picture 2>. The orange basketball."
        in prompt
    )
    assert prompt.count("[Shot 1]") == 1
    assert "overall_soundscape:\nLight wind." in prompt
    assert prompt.endswith("non_diegetic_music:\nSparse piano notes.")
    assert "fully_preserved" in prompt


def test_raw_text_is_exact_and_separate_settings_warn():
    prompt = " \n" + compile_prompt("A bird")["effective_prompt"] + "\n  "
    result = compile_prompt(prompt, "ignored ambience", music="ignored score")
    assert result["prompt_format"] == "raw"
    assert result["effective_prompt"] == prompt
    assert len(result["prompt_warnings"]) == 1
    assert "not merged" in result["prompt_warnings"][0]


def test_ordinary_text_does_not_trigger_raw_detection():
    result = compile_prompt('A sign reads "detailed_description:" beside a window.')
    assert result["prompt_format"] == "guided"


def test_raw_diagnostics_do_not_rewrite_or_assume_one_subject_per_picture():
    prompt = """subject_definitions:
<Subject 1> and <Subject 4> are the two people in <Picture 1>.
summary:
[reference generation] The two people talk.
retention_analysis:
Preserve their appearances.
detailed_description:
[Shot 1] <Subject 4> waves.
overall_soundscape:
Wind.
non_diegetic_music:
N/A"""
    result = compile_prompt(prompt, mode="r2v", count=1, prompt_format="raw")
    assert not result["prompt_warnings"]
    assert result["effective_prompt"] == prompt
    invalid = compile_prompt(
        prompt + "\n<Picture 2>", mode="r2v", count=1, prompt_format="raw"
    )
    assert any(
        "unavailable pictures" in warning for warning in invalid["prompt_warnings"]
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prompt_format": "unknown"},
        {"count": 1},
        {"mode": "i2v", "count": 0},
        {"mode": "r2v", "count": 4},
        {"music": "x" * 4001},
        {"reference_descriptions": "person"},
        {"reference_descriptions": [None]},
        {"mode": "r2v", "count": 2, "reference_descriptions": ["one"]},
        {"reference_descriptions": ["x" * 1001]},
    ],
)
def test_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        compile_prompt("A scene", **kwargs)


def test_raw_limit_allows_legacy_assembled_prompts_without_truncation():
    prompt = "integrated_multimodal_description:\n" + "x" * 20000
    assert compile_prompt(prompt)["effective_prompt"] == prompt
    with pytest.raises(ValueError):
        compile_prompt("x" * 16001, prompt_format="guided")
    with pytest.raises(ValueError):
        compile_prompt("x" * 40001, prompt_format="raw")


def test_missing_sections_and_first_frame_are_advisory():
    result = compile_prompt("A scene", mode="i2v", count=1, prompt_format="raw")
    assert result["effective_prompt"] == "A scene"
    assert any(
        "Missing recommended sections" in warning
        for warning in result["prompt_warnings"]
    )
    assert any("0 seconds" in warning for warning in result["prompt_warnings"])
