import os
import google.generativeai as genai 

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_client = None
def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY") 
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        genai.configure(api_key=api_key) 
        _client = genai

    return _client

def chat_llm(system_prompt: str, user: str) -> str:
    """
    Simple text-in/text-out.
    """
    client = get_client()
    model = client.GenerativeModel(GEMINI_MODEL) 
    
    resp = model.generate_content(
        contents=[
            {"role": "user", "parts": [{"text": f"{system_prompt}\n\nUSER: {user}"}]}
        ],
    )
    try:
        return resp.text.strip()
    except (AttributeError, ValueError):
        print(f"Warning: Could not extract text from Gemini response: {resp}")
        return "(Could not generate a response)"