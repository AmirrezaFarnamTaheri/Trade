"""Assistant evaluation: a fixed prompt set, a no-model baseline, and a verdict with thresholds set in advance."""
import json

from gym.services.assistant_eval import baseline, cases, evaluate, verdict


def test_prompt_set_is_deterministic_and_baseline_is_valid_json():
    first, second = cases(), cases()
    assert [c["prompt"] for c in first] == [c["prompt"] for c in second] and len(first) == 30
    base = baseline(first)
    assert base["json_valid_rate"] == 1.0 and base["cases"] == 30 and 0 < base["valid_proposal_rate"] <= 1


def test_a_model_that_repeats_history_or_breaks_json_does_not_beat_the_baseline():
    prompt_set = cases(10)
    base = baseline(prompt_set)
    garbled = evaluate(lambda prompt: "I suggest [ema-trend", prompt_set)
    assert garbled["json_valid_rate"] == 0 and not verdict(garbled, base)["adopt"]

    def echo_history(prompt):  # proposes exactly what was already tested, from the prompt itself
        history = json.loads(prompt.split("net result (JSON): ")[1].split("\n")[0])
        return json.dumps([{"strategy": h["strategy"], "params": h["params"]} for h in history][:3])
    echo = evaluate(echo_history, prompt_set)
    assert echo["repeat_rate"] == 1.0 and not verdict(echo, base)["adopt"]
