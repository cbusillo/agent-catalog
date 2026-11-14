from pathlib import Path


def canary() -> None:
    Path().no_such_method()
