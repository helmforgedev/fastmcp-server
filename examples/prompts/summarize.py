def summarize(text: str) -> str:
    """Summarize the provided text."""
    return f"Please provide a concise summary of the following text:\n\n{text}"


def explain(topic: str, audience: str = "beginner") -> str:
    """Explain a topic for a specific audience."""
    return f"Please explain {topic} in terms suitable for a {audience} audience."
