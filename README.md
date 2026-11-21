# Adaptive Basket Recommender

Repository: <https://github.com/Royphilips/adaptive-basket-recommender>

A shopping assistant that **adapts to each shopper**. You tell it what is
in your basket and it suggests what else you may need. As you answer
*yes* or *no*, finish trips and ask questions, it changes what it
suggests, what it stops suggesting, and how much explanation it shows.
It tells you whenever it changes its behavior, and you can see, undo or
erase everything it has learned.

## The system this project started from

The starting point is my earlier project, **Basket Recommender**
(<https://github.com/Royphilips/basket-recommender>). That system mines
association rules from 3,000 shopping baskets and suggests items that go
with the basket. It is *not* adaptive: every shopper with the same basket
gets the same suggestions, and it remembers nothing between sessions.

Basket Recommender was itself built on Example 1, "Generating Association
Rules from Frequent Itemsets," in the mlxtend user guide by Sebastian
Raschka (<https://rasbt.github.io/mlxtend/user_guide/frequent_patterns/association_rules/>,
BSD 3-Clause license), which is kept in `original_example/`.

**Unchanged files from the starting system:** `recommender/`, `app_cli.py`,
`app_gui.py`, `evaluate.py`, `data/`, `original_example/`,
`tests/test_recommender.py`.

**New files for this project:** `adaptive/profile.py`, `adaptive/engine.py`,
`adaptive_cli.py`, `simulate.py`, `tests/test_adaptive.py`,
`colab_demo.ipynb`, `AI_USAGE.md`.

## How it adapts

| What the shopper does | What the system learns | How its behavior changes |
|---|---|---|
| Says **yes** or **no** to a suggestion | A preference score for that item and its category | Items and categories move up or down the list |
| Says **no** to the same item 3 times | The item is unwanted | It is no longer suggested (`allow <item>` brings it back) |
| Leaves a suggestion unanswered, or says `no all` | A weak signal, worth a quarter of a "no" | A small nudge only; it can never hide an item |
| Finishes trips with `checkout` | What this shopper regularly buys | "Your usuals" replace generic popular items |
| Asks **why** twice | This shopper wants evidence | Every suggestion shows its statistics from then on |
| Says `avoid dairy` | An explicit rule | Remembered in every later session |

Design rules that keep the adaptation safe and understandable:

- **Cautious.** One click only nudges a score. It takes about two
  consistent answers before a category moves noticeably.
- **Recent behavior counts most.** Category evidence fades by 10% after
  every trip, so the system can change its mind.
- **Announced.** A line beginning `Note:` appears whenever learning changes
  the system's behavior, and changed suggestions carry a label such as
  `[moved down: you've said no to Produce items lately]`.
- **Controllable.** `profile` shows everything learned; `undo` reverses the
  last answer; `reset profile` erases everything; `adapt off` returns the
  exact suggestions of the starting system.
- **Private.** A profile holds only counts and is saved as a small JSON
  file in `profiles/` on your own machine.

## Running it

Requires Python 3.9 or later.

```bash
pip install -r requirements.txt

python adaptive_cli.py --user yourname    # the adaptive assistant
python -m pytest -q                       # 30 tests
python simulate.py                        # simulation -> results/simulation.md
python app_cli.py                         # the starting system, for comparison
```

### Example

```
> I have tortillas and ground beef
  1. Avocado (Produce): goes with Tortillas
  2. Cheddar Cheese (Dairy & Eggs): goes with Tortillas
  3. Salsa (Pantry): goes with Tortillas
> no avocado
> yes salsa
> checkout
...two trips later...
Note: you've turned down Avocado 3 times, so I'll stop suggesting it.
Type 'allow avocado' to bring it back.
> checkout
  1. Ground Beef (Meat): one of your usuals
  2. Tortillas (Bakery): one of your usuals
```

A full session is in `results/sample_session.txt`.

Commands: `yes`, `no`, `no all`, `undo`, `checkout`, `profile`,
`reset profile`, `adapt on|off`, `details on|off|auto`, plus everything
from the starting system (`add`, `remove`, `clear`, `show`, `avoid`,
`allow`, `why`, `more`, `less`, `diversity`, `help`, `quit`).

### Running it in Google Colab

1. Open <https://colab.research.google.com/github/Royphilips/adaptive-basket-recommender/blob/main/colab_demo.ipynb>
   (works while the repository is public), or upload `colab_demo.ipynb`
   with **File ▸ Upload notebook**.
2. In the first code cell, set `REPO_URL` to this repository's address,
   or leave it empty and upload the project ZIP when asked.
3. Run the cells in order. The tests should report **30 passed**.

## Does adapting help?

`simulate.py` runs 300 simulated shoppers, each with two disliked and two
liked categories, through the starting system and the adaptive system.

| Measure (per trip, 5 suggestions shown) | Starting system | Adaptive system |
|---|---|---|
| Suggestions accepted, trips 7–12 | 1.90 | 2.25 |
| Disliked items shown, trips 7–12 | 1.52 | 1.10 |
| Suggestions accepted after tastes change, trips 9–16 | 2.39 | 2.65 |

![Learning curve](results/learning_curve.png)

Limitations: the shoppers are simulated and answer by category, which is
also how the system learns, so this shows the mechanism works as designed,
not how much real shoppers would benefit. After a simulated shopper's taste
changes, the adaptive system is slow to catch up on the newly liked
category (0.46 items shown per trip against 0.63 for the starting system);
fading old evidence helped only slightly (0.43 without it).

## Use of AI tools

See [`AI_USAGE.md`](AI_USAGE.md) for which parts of this project were
created with an AI assistant.

## License

MIT for this project's code (see `LICENSE`). The baseline example follows
mlxtend's BSD 3-Clause license.
