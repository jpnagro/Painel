import numpy as np
import pandas as pd

LISTA_QUEBRA = [
    0,
    0.5270772063192397,
    0.5392865399099575,
    0.5487455803291189,
    0.5717575996274532,
    0.5931789001656713,
    0.6098758374210749,
    0.6247240724928961,
    0.6396911057987202,
    1.01,
]

RATING_ORDER = ["AA", "A", "B", "C", "D", "E", "F", "G", "H"]


def _calc_score_step(num: int, prob: float, val1: float, val2: float) -> int:
    lista = list(np.linspace(val1, val2, num + 1))
    for i in range(num):
        if lista[i] <= prob < lista[i + 1]:
            return num - i
    return 0


def prob_to_score(prob: float) -> int:
    lb = LISTA_QUEBRA
    bands = [
        (lb[0], lb[1], 900, 100),
        (lb[1], lb[2], 800, 100),
        (lb[2], lb[3], 700, 100),
        (lb[3], lb[4], 600, 100),
        (lb[4], lb[5], 500, 100),
        (lb[5], lb[6], 400, 100),
        (lb[6], lb[7], 300, 100),
        (lb[7], lb[8], 200, 100),
        (lb[8], lb[9], 0, 200),
    ]
    for lo, hi, base, num in bands:
        if lo <= prob < hi:
            return base + _calc_score_step(num, prob, lo, hi)
    return 0


def score_to_prob(score: int):
    faixas = {
        (900, 1000): (100, 0, 1),
        (800, 900): (100, 1, 2),
        (700, 800): (100, 2, 3),
        (600, 700): (100, 3, 4),
        (500, 600): (100, 4, 5),
        (400, 500): (100, 5, 6),
        (300, 400): (100, 6, 7),
        (200, 300): (100, 7, 8),
        (0, 200): (200, 8, 9),
    }
    for (lo, hi), (num, i1, i2) in faixas.items():
        if lo <= score < hi:
            adc = score - lo
            v1, v2 = LISTA_QUEBRA[i1], LISTA_QUEBRA[i2]
            arr = np.linspace(v1, v2, num + 1)
            idx = max(0, min(num - adc - 1, num - 1))
            return float((arr[idx] + arr[idx + 1]) / 2)
    return None


def calculate_psi(expected: pd.Series, actual: pd.Series, buckets: int = 10):
    breaks = np.quantile(expected, np.linspace(0, 1, buckets + 1))
    breaks = np.unique(breaks)
    exp_perc = np.histogram(expected, bins=breaks)[0] / len(expected)
    act_perc = np.histogram(actual, bins=breaks)[0] / len(actual)
    parts = (act_perc - exp_perc) * np.log((act_perc + 1e-6) / (exp_perc + 1e-6))
    return float(np.sum(parts)), parts, breaks


def sort_ratings(series: pd.Series) -> pd.Categorical:
    present = [r for r in RATING_ORDER if r in series.values]
    return pd.Categorical(series, categories=present, ordered=True)


def psi_status(value: float) -> str:
    if value < 0.10:
        return "🟢 Estável"
    if value < 0.25:
        return "🟡 Moderado"
    return "🔴 Crítico"


def delta_color(current: float, reference: float, higher_is_better: bool = True) -> str:
    if higher_is_better:
        return "normal" if current >= reference else "inverse"
    return "normal" if current <= reference else "inverse"
