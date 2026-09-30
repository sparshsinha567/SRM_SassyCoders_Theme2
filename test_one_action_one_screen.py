"""Unit test covering the One Action = One Screen constraint:
1. Intra-action split path: verifies divergent step groups are split into distinct Action cards.
2. Inter-action merge path: verifies duplicate target screen actions have their step groups merged.
"""
from structure_extraction import _enforce_one_action_one_screen
from schema import Action, StepGroup, Deeplink, actionCategory


def test_intra_action_split():
    dl_display = Deeplink(
        deeplink="voiceassist://masked/act/screen_display",
        description="Display Settings",
        message="Configure Display",
        originalType="onClickURL",
    )
    dl_battery = Deeplink(
        deeplink="voiceassist://masked/act/screen_battery",
        description="Battery Settings",
        message="Configure Battery",
        originalType="onClickURL",
    )

    sg_display = StepGroup(steps=["Turn off adaptive brightness"], actionableDeeplink=dl_display)
    sg_battery = StepGroup(steps=["Put unused apps to sleep"], actionableDeeplink=dl_battery)

    action_divergent = Action(
        actionName="Power & Display Options",
        description="It will configure display and battery options",
        category=actionCategory.auto,
        stepGroups=[sg_display, sg_battery],
    )

    split_actions, disagreement_count = _enforce_one_action_one_screen([action_divergent])

    assert disagreement_count == 1, f"Expected 1 disagreement, got {disagreement_count}"
    assert len(split_actions) == 2, f"Expected 2 split actions, got {len(split_actions)}"
    assert split_actions[0].stepGroups[0].actionableDeeplink.deeplink == "voiceassist://masked/act/screen_display"
    assert split_actions[1].stepGroups[0].actionableDeeplink.deeplink == "voiceassist://masked/act/screen_battery"
    assert "Secondary" in split_actions[1].actionName
    print("[PASS] test_intra_action_split: Successfully split divergent step groups into separate Action cards.")


def test_inter_action_merge():
    dl_adaptive = Deeplink(
        deeplink="voiceassist://masked/act/screen_adaptive",
        description="Adaptive Brightness",
        message="Configure Brightness",
        originalType="onClickURL",
    )

    action1 = Action(
        actionName="Adaptive Brightness Toggle",
        description="It will enable adaptive display brightness automatically",
        category=actionCategory.auto,
        stepGroups=[StepGroup(steps=["Navigate to Settings > Display", "Toggle Adaptive Brightness to ON"], actionableDeeplink=dl_adaptive)],
    )

    action2 = Action(
        actionName="Display Sensor Calibration",
        description="It will verify light sensor responsiveness",
        category=actionCategory.auto,
        stepGroups=[StepGroup(steps=["Ensure ambient light sensor is unobstructed", "Check screen brightness shifts"], actionableDeeplink=dl_adaptive)],
    )

    merged_actions, disagreement_count = _enforce_one_action_one_screen([action1, action2])

    assert disagreement_count == 0, f"Expected 0 intra-action disagreements, got {disagreement_count}"
    assert len(merged_actions) == 1, f"Expected 1 merged action, got {len(merged_actions)}"
    assert len(merged_actions[0].stepGroups) == 2, f"Expected 2 step groups, got {len(merged_actions[0].stepGroups)}"

    all_steps = [s for sg in merged_actions[0].stepGroups for s in sg.steps]
    assert len(all_steps) == 4, f"Expected 4 preserved steps, got {len(all_steps)}"
    print("[PASS] test_inter_action_merge: Successfully merged step groups into primary card without step loss.")


def test_split_then_merge_compound():
    """Compound pipeline test: an action splits due to intra-action disagreement,
    and the resulting split fragment then merges with a 3rd action targeting the same screen."""
    dl_screen_a = Deeplink(
        deeplink="voiceassist://masked/act/screen_A",
        description="Screen A (Display)",
        message="Configure Display",
        originalType="onClickURL",
    )
    dl_screen_b = Deeplink(
        deeplink="voiceassist://masked/act/screen_B",
        description="Screen B (Battery)",
        message="Configure Battery",
        originalType="onClickURL",
    )

    # Action 1 has divergent step groups (Screen A and Screen B)
    sg_a1 = StepGroup(steps=["Turn off adaptive brightness"], actionableDeeplink=dl_screen_a)
    sg_b1 = StepGroup(steps=["Enable battery saver mode"], actionableDeeplink=dl_screen_b)
    action1_divergent = Action(
        actionName="Display & Power Management",
        description="It will configure display and battery settings",
        category=actionCategory.auto,
        stepGroups=[sg_a1, sg_b1],
    )

    # Action 2 also targets Screen B
    sg_b2 = StepGroup(
        steps=["Put background apps to sleep", "Inspect battery discharge curve"],
        actionableDeeplink=dl_screen_b,
    )
    action2_battery = Action(
        actionName="Battery Optimization",
        description="It will optimize battery discharge behavior",
        category=actionCategory.auto,
        stepGroups=[sg_b2],
    )

    # Execute compound pipeline
    final_actions, disagreement_count = _enforce_one_action_one_screen([action1_divergent, action2_battery])

    print("\n--- TEST 3: COMPOUND SPLIT-THEN-MERGE ---")
    print("Disagreement count:", disagreement_count)
    print("Resulting actions count:", len(final_actions))
    for i, a in enumerate(final_actions):
        steps = [s for sg in a.stepGroups for s in sg.steps]
        dl = a.stepGroups[0].actionableDeeplink.deeplink
        print(f"Action {i+1}: {a.actionName} | Target: {dl} | Step Groups: {len(a.stepGroups)} | Steps ({len(steps)}): {steps}")

    assert disagreement_count == 1, f"Expected 1 intra-action split disagreement, got {disagreement_count}"
    assert len(final_actions) == 2, f"Expected exactly 2 final distinct screen cards, got {len(final_actions)}"

    # First action targets Screen A
    assert final_actions[0].stepGroups[0].actionableDeeplink.deeplink == "voiceassist://masked/act/screen_A"
    assert len(final_actions[0].stepGroups[0].steps) == 1

    # Second action targets Screen B and holds merged steps from both Action 1 fragment and Action 2
    assert final_actions[1].stepGroups[0].actionableDeeplink.deeplink == "voiceassist://masked/act/screen_B"
    assert len(final_actions[1].stepGroups) == 2, f"Expected 2 merged step groups, got {len(final_actions[1].stepGroups)}"

    all_b_steps = [s for sg in final_actions[1].stepGroups for s in sg.steps]
    assert "Enable battery saver mode" in all_b_steps
    assert "Put background apps to sleep" in all_b_steps
    assert len(all_b_steps) == 3, f"Expected 3 steps in merged battery action, got {len(all_b_steps)}"

    print("[PASS] test_split_then_merge_compound: Successfully split divergent group and merged fragment with duplicate screen action.")


if __name__ == "__main__":
    test_intra_action_split()
    test_inter_action_merge()
    test_split_then_merge_compound()
    print("\nALL ONE ACTION = ONE SCREEN UNIT TESTS PASSED!")
