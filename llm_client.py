import os
from google import genai

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_client = None
def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        _client = genai.Client(api_key=api_key)
    return _client

def chat_llm(system_prompt: str, user: str) -> str:
    """
    Simple text-in/text-out.
    """
    client = get_client()
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            {"role": "user", "parts": [{"text": f"{system_prompt}\n\nUSER: {user}"}]}
        ],
    )
    return getattr(resp, "text", "").strip()
