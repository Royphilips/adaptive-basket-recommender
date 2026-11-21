"""Adaptive conversational assistant for the basket recommender.

It extends the starting system's assistant (app_cli.py, unchanged) so that it
learns from what you do and changes its behavior to suit you.

Everything from the starting system still works:
  add <items>   remove <items>   clear   show   avoid <x>   allow <x>
  why <item>    more / less      diversity <0-0.9>          help   quit

New commands for the adaptive system:
  yes <numbers or items>   accept suggestions, e.g. 'yes 1 3' or 'yes salsa'
  no <numbers or items>    turn suggestions down, e.g. 'no 2' or 'no salsa'
  no all                   none of these right now (a weak signal, not a dislike)
  undo                     take back your last yes / no / checkout / reset
  checkout                 finish this trip; I remember what you bought
  profile                  see everything I have learned about you
  reset profile            make me forget everything I have learned
  adapt on | off           switch all personalization on or off
  details on | off | auto  always / never show the evidence, or let me adapt

Run:  python adaptive_cli.py --user yourname
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from adaptive import AdaptiveRecommender, UserProfile
from adaptive.profile import HIDE_AFTER_REJECTS, NOTICE_DOWN, NOTICE_UP, PROFILE_DIR, WHY_THRESHOLD
from app_cli import ShoppingAssistant
from recommender import BasketRecommender, load_catalog, load_transactions

HELP = __doc__.split("\n\n", 2)[2].rsplit("\n\n", 1)[0]


class AdaptiveAssistant(ShoppingAssistant):
    def __init__(self, recommender: BasketRecommender, profile: UserProfile,
                 folder: Path = PROFILE_DIR):
        super().__init__(recommender)
        self.adaptive = AdaptiveRecommender(recommender)
        self.profile = profile
        self.folder = folder
        self.avoid_items = set(profile.avoid_items)            # remembered between sessions
        self.avoid_categories = set(profile.avoid_categories)
        self.last_shown: List = []       # the list currently on screen (for 'yes 2')
        self.shown_this_trip: set = set()
        self.acted: set = set()          # suggestions already answered with yes or no
        self._undo = None

    # ------------------------------------------------------------ suggestions
    def recommendations(self):
        return self.adaptive.recommend(self.basket, self.profile, self.k,
                                       self.avoid_items | self.dismissed,
                                       self.avoid_categories, self.diversity)

    def suggestions(self) -> str:
        recs = self.recommendations()
        self.last_shown = recs
        self.shown_this_trip |= {r.item for r in recs}
        if not recs:
            return "I have nothing left to suggest with those filters."
        details = self.profile.wants_details()
        lines = [f"  {n}. {r.explain(details)}" for n, r in enumerate(recs, 1)]
        return "You might also want (answer 'yes 1' or 'no 2'):\n" + "\n".join(lines)

    # ---------------------------------------------------------------- helpers
    def _snapshot(self) -> None:
        self._undo = (self.profile.to_dict(), set(self.basket), set(self.dismissed),
                      set(self.acted), set(self.shown_this_trip))

    def _targets(self, text: str) -> List[str]:
        """Turn '1 3', 'all' or item names into a list of items."""
        words = text.replace(",", " ").split()
        if any(w.lower() in {"all", "everything", "none"} for w in words):
            return [r.item for r in self.last_shown]
        items = []
        for w in words:
            if w.isdigit() and 1 <= int(w) <= len(self.last_shown):
                items.append(self.last_shown[int(w) - 1].item)
        for item in self.find_items(" ".join(w for w in words if not w.isdigit())):
            if item not in items:
                items.append(item)
        return items

    def _notices(self) -> List[str]:
        """Tell the shopper, once, whenever what I learned changes my behavior."""
        p, out = self.profile, []
        if not p.adaptation:
            return out

        def once(key: str, active: bool, message: str) -> None:
            if active and key not in p.notified:
                p.notified.append(key)
                out.append(message)
            elif not active and key in p.notified:
                p.notified.remove(key)

        for item in list(p.items):
            once(f"hidden:{item}", p.is_hidden(item),
                 f"Note: you've turned down {item} {HIDE_AFTER_REJECTS} times, so I'll stop "
                 f"suggesting it. Type 'allow {item.lower()}' to bring it back.")
        for cat in list(p.categories):
            m = p.category_multiplier(cat)
            once(f"down:{cat}", m <= NOTICE_DOWN,
                 f"Note: you've said no to {cat} items a couple of times lately, so I'll rank "
                 f"{cat} lower for now. Type 'profile' to see what I've learned, or 'undo'.")
            once(f"up:{cat}", m >= NOTICE_UP,
                 f"Note: you've said yes to {cat} items a couple of times lately, so I'll rank "
                 f"{cat} higher for now. Type 'profile' to see what I've learned, or 'undo'.")
        once("details", p.details == "auto" and p.why_requests >= WHY_THRESHOLD,
             "Note: you've asked 'why' a few times, so I'll show the evidence with every "
             "suggestion from now on. Type 'details off' to switch back.")
        return out

    def _save(self) -> None:
        self.profile.avoid_items = sorted(self.avoid_items)
        self.profile.avoid_categories = sorted(self.avoid_categories)
        self.profile.save(self.folder)

    def _with_notices(self, reply: str) -> str:
        notices = self._notices()
        return "\n".join(notices + [reply]) if notices else reply

    # ------------------------------------------------------------- commands
    def handle(self, line: str) -> str:
        reply = self._handle(line.strip())
        self._save()
        return reply

    def _handle(self, line: str) -> str:
        if not line:
            return ""
        command, _, rest = line.partition(" ")
        command, rest = command.lower(), rest.strip()
        cat = self.rec.category_of

        if command in {"help", "?"}:
            return HELP

        if command in {"yes", "y", "take", "accept"}:
            items = [i for i in self._targets(rest) if i not in self.basket]
            if not items:
                return "Which one? Try 'yes 1' or 'yes salsa'."
            self._snapshot()
            for item in items:
                self.basket.add(item)
                self.dismissed.discard(item)
                if item in self.shown_this_trip and item not in self.acted:
                    self.profile.record_accept(item, cat(item))
                    self.acted.add(item)
            return self._with_notices(f"Added {', '.join(items)}.\n" + self.suggestions())

        if command in {"no", "n", "skip", "reject"}:
            items = [i for i in self._targets(rest) if i not in self.basket]
            if not items:
                return "Which one? Try 'no 2', 'no salsa' or 'no all'."
            self._snapshot()
            # "no all" means "none of these right now". That is weaker evidence than
            # turning down one named item, so it is recorded as an ignore, not a dislike.
            bulk = rest.lower() in {"all", "everything", "none"}
            for item in items:
                if item not in self.acted:
                    if bulk:
                        self.profile.record_ignore(item)
                    else:
                        self.profile.record_reject(item, cat(item))
                    self.acted.add(item)
                self.dismissed.add(item)
            return self._with_notices(f"OK, not {', '.join(items)}.\n" + self.suggestions())

        if command == "undo":
            if self._undo is None:
                return "Nothing to undo."
            data, self.basket, self.dismissed, self.acted, self.shown_this_trip = self._undo
            self.profile.__dict__.update(UserProfile.from_dict(data).__dict__)
            self.avoid_items = set(self.profile.avoid_items)
            self.avoid_categories = set(self.profile.avoid_categories)
            self._undo = None
            return "Undone.\n" + self.suggestions()

        if command in {"checkout", "done", "finish"}:
            if not self.basket:
                return "Your basket is empty, so there is nothing to save."
            self._snapshot()
            bought = sorted(self.basket)
            self.profile.record_trip(bought)
            for item in self.shown_this_trip - self.acted - self.basket:
                self.profile.record_ignore(item)      # shown but never answered: a weak "no"
            self.basket, self.dismissed = set(), set()
            self.shown_this_trip, self.acted = set(), set()
            return self._with_notices(
                f"Trip {self.profile.trips} saved: {', '.join(bought)}.\n"
                f"New trip started.\n" + self.suggestions())

        if command == "profile":
            return "\n".join(self.profile.summary())

        if command == "reset":
            self._snapshot()
            self.profile.reset()
            self.avoid_items, self.avoid_categories = set(), set()
            return "I've forgotten everything I learned about you ('undo' brings it back).\n" + self.suggestions()

        if command == "adapt" and rest.lower() in {"on", "off"}:
            self.profile.adaptation = rest.lower() == "on"
            state = "ON: I'll use what I've learned" if self.profile.adaptation else \
                    "OFF: you'll get the same suggestions as everyone else (I keep what I learned for later)"
            return f"Adaptation is {state}.\n" + self.suggestions()

        if command == "details" and rest.lower() in {"on", "off", "auto"}:
            self.profile.details = rest.lower()
            return f"Details set to {self.profile.details}.\n" + self.suggestions()

        if command == "why":
            self.profile.record_why()
            return self._with_notices(super().handle(line))

        if command == "allow":
            for item in self.find_items(rest):
                self.profile.forgive(item)

        # Everything else is handled by the starting system. If the shopper adds an
        # item I had suggested, that also counts as a "yes" (implicit feedback).
        # This applies only to the list on screen for a basket that already had items;
        # a shopper who is just listing what they have is not answering a suggestion.
        before, on_screen = set(self.basket), {r.item for r in self.last_shown}
        reply = super().handle(line)
        for item in self.basket - before:
            if before and item in on_screen and item not in self.acted:
                self.profile.record_accept(item, cat(item))
                self.acted.add(item)
        return self._with_notices(reply)


def build_assistant(user: str = "guest", folder: Path = PROFILE_DIR) -> AdaptiveAssistant:
    recommender = BasketRecommender().fit(load_transactions(), load_catalog())
    return AdaptiveAssistant(recommender, UserProfile.load(user, folder), folder)


def greeting(assistant: AdaptiveAssistant) -> str:
    p = assistant.profile
    if p.trips or p.items:
        return (f"Welcome back, {p.name}. I remember {p.trips} trip(s). "
                f"Type 'profile' to see what I've learned.\n" + assistant.suggestions())
    return (f"Hello {p.name}. I don't know you yet, so I'll start with what most shoppers buy "
            f"and learn as you answer.\n" + assistant.suggestions())


def main() -> None:
    parser = argparse.ArgumentParser(description="Adaptive basket assistant")
    parser.add_argument("--user", default="guest", help="profile name (default: guest)")
    args = parser.parse_args()
    assistant = build_assistant(args.user)
    print(greeting(assistant))
    print("Tell me what's in your basket, answer with yes/no, or type 'help'.")
    interactive = sys.stdin.isatty()
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if not interactive:
            print(line)
        if line.strip().lower() in {"quit", "exit", "bye"}:
            print("Goodbye! Your profile is saved.")
            break
        reply = assistant.handle(line)
        if reply:
            print(reply)


if __name__ == "__main__":
    main()
