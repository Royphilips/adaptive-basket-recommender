"""Simulation: does adapting to the shopper actually help?

Real shoppers were not available, so this script simulates them. Each
simulated shopper has hidden tastes: two categories they dislike and two
they like. On every trip the shopper starts with two items, is shown five
suggestions, and answers each one (yes, no, or no answer) according to
those hidden tastes. The same shoppers, trips and random choices are run
twice: once with the starting system (adaptation off) and once with the
adaptive system, which learns from the answers.

Two experiments:
  steady  - tastes stay the same for all 12 trips
  drift   - after trip 8 of 16, one disliked category becomes a liked one
            (tests whether the system can change its mind; it is also run
            with fading of old evidence switched off, for comparison)

The simulated shoppers answer by category, which is also how the system
learns, so these results show that the mechanism works as designed. They
do not show how much real shoppers would benefit.

Run:  python simulate.py      (prints tables, writes results/simulation.*)
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

import adaptive.profile as profile_settings
from adaptive import AdaptiveRecommender, UserProfile
from recommender import BasketRecommender, load_catalog, load_transactions

N_USERS = 300
K = 5
BASE_YES = {"rule": 0.50, "usual": 0.50, "popular": 0.20}   # chance of "yes" by kind of suggestion
TASTE = {"dislike": 0.05, "neutral": 1.0, "like": 1.5}      # multiplied into that chance
SAYS_NO = 0.5      # when the answer isn't yes, how often the shopper says "no" rather than nothing
RESULTS = Path(__file__).resolve().parent / "results"


def make_shopper(user: int, categories: list) -> dict:
    rng = random.Random(f"shopper-{user}")
    picks = rng.sample(categories, 4)
    return {"dislike": set(picks[:2]), "like": set(picks[2:])}


def taste_of(shopper: dict, category: str) -> str:
    return "dislike" if category in shopper["dislike"] else "like" if category in shopper["like"] else "neutral"


def run(model, transactions, catalog, n_trips: int, adaptation: bool, drift_after: int | None = None):
    """Per trip, averaged over shoppers: yes answers, disliked items shown, and items
    shown from the category whose taste changes (only meaningful in the drift experiment)."""
    adaptive = AdaptiveRecommender(model)
    categories = sorted(set(catalog.values()))
    accepted = [0.0] * n_trips
    disliked_shown = [0.0] * n_trips
    changed_shown = [0.0] * n_trips
    for user in range(N_USERS):
        shopper = make_shopper(user, categories)
        changed = sorted(shopper["dislike"])[0]                  # the category that flips in 'drift'
        profile = UserProfile(name=f"sim{user}", adaptation=adaptation)
        for trip in range(n_trips):
            if drift_after is not None and trip == drift_after:   # a disliked category becomes liked
                shopper = {"dislike": shopper["dislike"] - {changed}, "like": shopper["like"] | {changed}}
            rng = random.Random(f"trip-{user}-{trip}")           # same starting basket in both runs
            while True:
                start = [i for i in rng.choice(transactions) if catalog[i] not in shopper["dislike"]]
                if len(start) >= 2:
                    break
            basket = set(rng.sample(start, 2))
            recs = adaptive.recommend(basket, profile, K)
            answered = set()
            for rec in recs:
                taste = taste_of(shopper, rec.category)
                if taste == "dislike":
                    disliked_shown[trip] += 1
                if rec.category == changed:
                    changed_shown[trip] += 1
                answer = random.Random(f"answer-{user}-{trip}-{rec.item}")   # same answer in both runs
                if answer.random() < min(0.95, BASE_YES[rec.source] * TASTE[taste]):
                    profile.record_accept(rec.item, rec.category)
                    basket.add(rec.item)
                    answered.add(rec.item)
                    accepted[trip] += 1
                elif answer.random() < SAYS_NO:
                    profile.record_reject(rec.item, rec.category)
                    answered.add(rec.item)
            for rec in recs:
                if rec.item not in answered:
                    profile.record_ignore(rec.item)
            profile.record_trip(basket)
    per_shopper = lambda totals: [t / N_USERS for t in totals]
    return per_shopper(accepted), per_shopper(disliked_shown), per_shopper(changed_shown)


def experiment(model, transactions, catalog, name: str, n_trips: int, drift_after=None) -> pd.DataFrame:
    static_yes, static_bad, static_changed = run(model, transactions, catalog, n_trips, False, drift_after)
    adapt_yes, adapt_bad, adapt_changed = run(model, transactions, catalog, n_trips, True, drift_after)
    table = pd.DataFrame({
        "experiment": name, "trip": range(1, n_trips + 1),
        "static_yes": static_yes, "adaptive_yes": adapt_yes,
        "static_disliked_shown": static_bad, "adaptive_disliked_shown": adapt_bad,
    })
    if drift_after is not None:
        # Also run the adaptive system with fading switched off, to measure what fading adds.
        normal = profile_settings.CATEGORY_MEMORY
        profile_settings.CATEGORY_MEMORY = 1.0
        nofade_yes, _, nofade_changed = run(model, transactions, catalog, n_trips, True, drift_after)
        profile_settings.CATEGORY_MEMORY = normal
        table["static_changed_shown"] = static_changed
        table["adaptive_changed_shown"] = adapt_changed
        table["nofade_changed_shown"] = nofade_changed
        table["nofade_yes"] = nofade_yes
    return table


def draw_chart(steady: pd.DataFrame, drift: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), sharey=True)
    for ax, data, title in ((axes[0], steady, "Tastes stay the same"),
                            (axes[1], drift, "Tastes change after trip 8")):
        ax.plot(data.trip, data.static_yes, color="#8a8984", linewidth=2, marker="o", markersize=4,
                label="Starting system (no adaptation)")
        ax.plot(data.trip, data.adaptive_yes, color="#2a78d6", linewidth=2, marker="o", markersize=4,
                label="Adaptive system")
        if title.startswith("Tastes change"):
            ax.axvline(8.5, color="#52514e", linewidth=1, linestyle=":")
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Trip number")
        ax.set_ylim(0, 3.2)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.yaxis.grid(True, color="#ecebe7")
        ax.set_axisbelow(True)
    axes[0].set_ylabel("Suggestions accepted (of 5)")
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    plt.tight_layout()
    plt.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


def main() -> None:
    transactions, catalog = load_transactions(), load_catalog()
    model = BasketRecommender().fit(transactions, catalog)
    steady = experiment(model, transactions, catalog, "steady", 12)
    drift = experiment(model, transactions, catalog, "drift", 16, drift_after=8)

    RESULTS.mkdir(exist_ok=True)
    both = pd.concat([steady, drift])
    both.to_csv(RESULTS / "simulation.csv", index=False)
    show = lambda df: df.drop(columns="experiment").round(2).to_string(index=False)
    text = (f"# Simulation results\n\n{N_USERS} simulated shoppers, {K} suggestions per trip. "
            f"Values are averages per shopper per trip.\n\n## Tastes stay the same\n\n```\n{show(steady)}\n```\n\n"
            f"## Tastes change after trip 8\n\n```\n{show(drift)}\n```\n")
    (RESULTS / "simulation.md").write_text(text, encoding="utf-8")
    print("Tastes stay the same\n" + show(steady))
    print("\nTastes change after trip 8\n" + show(drift))
    late_s, late_d, after = steady[steady.trip > 6], drift[drift.trip > 8], drift[(drift.trip > 8) & (drift.trip <= 12)]
    summary = (
        f"Steady, trips 7-12: yes per trip {late_s.static_yes.mean():.2f} (starting) vs "
        f"{late_s.adaptive_yes.mean():.2f} (adaptive); disliked items shown "
        f"{late_s.static_disliked_shown.mean():.2f} vs {late_s.adaptive_disliked_shown.mean():.2f}.\n"
        f"Drift, trips 9-16: yes per trip {late_d.static_yes.mean():.2f} (starting) vs "
        f"{late_d.adaptive_yes.mean():.2f} (adaptive) vs {late_d.nofade_yes.mean():.2f} (adaptive, no fading).\n"
        f"Drift, trips 9-12, items shown from the newly liked category: "
        f"{after.static_changed_shown.mean():.2f} (starting) vs {after.adaptive_changed_shown.mean():.2f} "
        f"(adaptive) vs {after.nofade_changed_shown.mean():.2f} (adaptive, no fading).")
    print("\n" + summary)
    with open(RESULTS / "simulation.md", "a", encoding="utf-8") as f:
        f.write("\n## Summary\n\n" + summary.replace("\n", "\n\n") + "\n")
    try:
        draw_chart(steady, drift, RESULTS / "learning_curve.png")
        print("\nChart saved to results/learning_curve.png")
    except ImportError:
        print("\n(matplotlib not installed, so no chart was drawn)")


if __name__ == "__main__":
    main()
