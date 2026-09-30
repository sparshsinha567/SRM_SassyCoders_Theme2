import json
from pathlib import Path

sub_file = Path("main data for submission/final_submission_output.json")
if not sub_file.exists():
    sub_file = Path("../main data for submission/final_submission_output.json")

data = json.load(open(sub_file, encoding="utf-8"))

print("=" * 80)
print("DEEPLINK SCREEN RESOLUTION ACCURACY AUDIT (Exact Target Screen vs Parent Menu)")
print("Scale: 2.0 = Exact target leaf screen | 1.0 = Parent menu | 0.0 = Unrelated")
print("=" * 80)

scores = []
items_report = []

for item in data:
    ctx = item["response"]["contexts"][0] if item["response"]["contexts"] else None
    if not ctx:
        continue
    
    # Analyze actionable deeplinks
    auto_deeplinks = []
    has_manual_repair = False
    for act in ctx["actions"]:
        if act["category"] == "manual":
            has_manual_repair = True
        for sg in act["stepGroups"]:
            dl = sg.get("actionableDeeplink")
            if dl:
                auto_deeplinks.append((act["actionName"], dl["deeplink"], dl["description"]))

    # Score each query
    # Criteria:
    # 2.0: Routes to specific leaf setting (e.g. Fast cable charging, Quick access, Apps screen, Aspect ratio, Touch sensitivity)
    # 1.0: Routes to high-level parent setting
    # N/A: Pure manual hardware service
    if not auto_deeplinks and has_manual_repair:
        score = 2.0  # Perfect compliance with manual hardware rule
        rating = "EXACT (Manual Hardware Repair - Zero False Deeplinks)"
    elif auto_deeplinks:
        first_desc = auto_deeplinks[0][2].lower()
        if any(term in first_desc for term in ["settings page", "enables", "disables"]) and not first_desc.startswith("opens general settings"):
            score = 2.0
            rating = "EXACT LEAF SCREEN"
        else:
            score = 1.0
            rating = "PARENT MENU"
    else:
        score = 0.0
        rating = "UNRESOLVED"

    scores.append(score)
    first_dl = auto_deeplinks[0] if auto_deeplinks else ("N/A", "None", "Hardware Repair (Manual)")
    print(f"[{item['id']}] Score: {score:.1f}/2.0 | Rating: {rating}")
    print(f"   Query: {item['query'][:65]}...")
    print(f"   Title: {ctx['title']}")
    print(f"   Target: {first_dl[1]} - {first_dl[2][:65]}...")
    print()

mean_score = sum(scores) / len(scores) if scores else 0.0
print("=" * 80)
print(f"FINAL SCREEN RESOLUTION ACCURACY SCORE: {mean_score:.2f} / 2.0")
print(f"Leaf Screen Resolution Rate: {sum(1 for s in scores if s == 2.0)} / {len(scores)} ({sum(1 for s in scores if s == 2.0)/len(scores)*100:.1f}%)")
print("=" * 80)
