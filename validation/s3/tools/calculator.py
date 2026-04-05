def divide(a: float, b: float) -> float:
    """Divide two numbers."""
    if b == 0:
        return float("inf")
    return a / b
