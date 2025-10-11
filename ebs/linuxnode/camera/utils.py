

from fractions import Fraction
from types import SimpleNamespace


def dict_to_ns(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: dict_to_ns(v) for k, v in d.items()})
    elif isinstance(d, list):
        return [dict_to_ns(x) for x in d]
    return d


def decode_flags(value, enum_cls):
    """Turn an IntFlag value into a list of strings."""
    try:
        return [flag.name for flag in enum_cls if flag & value]
    except Exception:
        return [str(value)]


def merge_dicts(source, updates):
    """
    Recursively merge two dictionaries. If a key exists in both, and its value is a dictionary,
    merge them recursively. Otherwise, take the value from `updates`.
    https://blog.mqhamdam.pro/pythonrecursive-merge-dict/
    """
    for key, value in updates.items():
        # If the value is a dictionary and the key exists in the source as a dictionary, recurse
        if isinstance(value, dict) and key in source and isinstance(source[key], dict):
            merge_dicts(source[key], value)
        else:
            # Otherwise, set or update the key in the source
            source[key] = value
    return source


def parse_fraction(frac: Fraction):
    if frac.denominator == 1:
        return f"{frac.numerator}"
    else:
        return f"{frac.numerator}/{frac.denominator}"
