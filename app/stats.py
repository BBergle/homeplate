from datetime import date, timedelta


def week_totals(days: list[date], today: date) -> list[int]:
    if not days:
        return [0]
    monday = lambda d: d - timedelta(days=d.weekday())
    last = monday(today)
    first = min(monday(min(days)), last)
    totals = [0] * ((last - first).days // 7 + 1)
    for d in days:
        i = (monday(d) - first).days // 7
        if i < len(totals):
            totals[i] += 1
    return totals


def streak(totals: list[int], goal: int) -> int:
    n, last = 0, len(totals) - 1
    for i in range(last, -1, -1):
        if totals[i] >= goal:
            n += 1
        elif i == last:                       # current week still in progress
            continue
        elif i + 1 == last or totals[i + 1] >= goal + 1:   # repairable or repaired
            continue
        else:
            break
    return n


def longest_run(totals: list[int], goal: int) -> int:
    best = run = 0
    for t in totals:
        run = run + 1 if t >= goal else 0
        best = max(best, run)
    return best


def achievements(home_meals: int, distinct_recipes: int, longest: int) -> list[tuple[str, bool]]:
    return [
        ("First cook", home_meals >= 1),
        ("10 meals", home_meals >= 10),
        ("50 meals", home_meals >= 50),
        ("4-week streak", longest >= 4),
        ("5 different recipes", distinct_recipes >= 5),
    ]


def savings(home_meals: int, delivery_cost: float, home_meal_cost: float) -> float:
    return home_meals * (delivery_cost - home_meal_cost)
