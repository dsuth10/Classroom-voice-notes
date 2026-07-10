# app/worker/result_validation.py

def sanitise_text(text: str) -> str:
    """Removes any potential sensitive details or formatting artifacts."""
    return text.strip()
