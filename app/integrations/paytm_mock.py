"""Mock Paytm payment link. Production: Paytm payment-link API + signed webhook."""
import os


def create_link(entry_id: int) -> str:
    base = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/pay/{entry_id}"