import os, time, asyncio, json, re, jwt
import numpy as np
from typing import Optional, List
from pydantic import BaseModel

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from rag import PatientRAG, get_redis
from llm_client import chat_llm

VECTOR_FIELD = "embedding"   
TEXT_FIELD = "text"       

def extract_json(text: str) -> Optional[dict]:
    """Extracts JSON from a string, handling markdown fences."""
    # Look for ```json ... ```
    match = re.search(r'```json\s*([\s\S]*?)\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        # Look for ``` ... ```
        match = re.search(r'```\s*([\s\S]*?)\s*```', text, re.DOTALL)
        if match:
            text = match.group(1)

    # Naive find first/last braces
    try:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
    except json.JSONDecodeError:
        pass 
    return None

def normalize_patient_doc(doc: dict) -> dict:
    out = dict(doc)

    if isinstance(out.get("allergies"), list):
        out["allergies"] = ",".join(map(str, out["allergies"]))

    if isinstance(out.get("red_flags"), list):
        out["red_flags"] = ",".join(map(str, out["red_flags"]))

    meds = out.get("medications")
    if isinstance(meds, (list, dict)):
        out["medications"] = json.dumps(meds, ensure_ascii=False)

    for k in list(out.keys()):
        if isinstance(out[k], (list, dict)):
            out[k] = json.dumps(out[k], ensure_ascii=False)

    return out

JWT_SECRET = os.getenv("JWT_SECRET", "supersecret-dev-key")
JWT_ALG = os.getenv("JWT_ALG", "HS256")

app = FastAPI(title="Post-Op Chatbot (Gemini + Redis)")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/")
def root():
    return FileResponse("index.html")

class Login(BaseModel):
    user_id: str
    password: str

class ChatMsg(BaseModel):
    message: str


async def verify_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        raise HTTPException(401, "Invalid token")
    return payload["patient_id"]

@app.post("/auth/login")
async def login(body: Login):
    r = await get_redis()
    patient_name = "" 
    
    # patient
    ukey = f"postop:user:{body.user_id}"
    data = await r.hgetall(ukey)
    if data and data.get(b"password", b"").decode() == body.password:
        patient_id = data[b"patient_id"].decode()
        token = jwt.encode({"role":"patient","patient_id": patient_id, "iat": int(time.time())}, JWT_SECRET, algorithm=JWT_ALG)
        
        try:
            patient_profile_raw = await r.hget(f"postop:patient:{patient_id}", "profile")
            if patient_profile_raw:
                profile_data = json.loads(patient_profile_raw.decode())
                patient_name = profile_data.get("name", "")
        except Exception:
            patient_name = "" 
            
        return {
            "access_token": token, 
            "token_type": "bearer", 
            "patient_id": patient_id, 
            "role":"patient",
            "name": patient_name
        }

    # doctor
    dkey = f"postop:doctor:{body.user_id}"
    data = await r.hgetall(dkey)
    if data and data.get(b"password", b"").decode() == body.password:
        doctor_name = data.get(b"name", b"Doctor").decode() # <-- NEW
        token = jwt.encode({"role":"doctor","user_id": body.user_id, "iat": int(time.time())}, JWT_SECRET, algorithm=JWT_ALG)
        return {
            "access_token": token, 
            "token_type": "bearer", 
            "role":"doctor",
            "name": doctor_name
        }

    raise HTTPException(401, "Invalid credentials")

@app.post("/seed")  # for dev and sampling
async def seed():
    import seed as seeder
    await seeder.main()
    return {"status":"ok"}


from fastapi import Depends

async def require_doctor(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization.split(" ", 1)[1]
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    if payload.get("role") != "doctor":
        raise HTTPException(403, "Doctor role required")
    return payload.get("user_id") or "doctor"

class NewPatient(BaseModel):
    user_id: str
    password: str = "test123"
    patient_id: str
    name: str
    age: int
    surgeon: str
    procedure: str
    emergency_name: str
    emergency_phone: str
    allergies: list[str] = []
    medications: list[dict]  
    red_flags: list[str] = []

@app.post("/admin/add_patient")
async def add_patient(p: NewPatient, doctor: str = Depends(require_doctor)):
    r = await get_redis()

    # Check if the user_id or patient_id already exists
    user_key = f"postop:user:{p.user_id}"
    patient_key = f"postop:patient:{p.patient_id}"
    
    if await r.exists(user_key):
        raise HTTPException(
            status_code=409,
            detail=f"Login user_id '{p.user_id}' already exists."
        )
    
    if await r.exists(patient_key):
        raise HTTPException(
            status_code=409,
            detail=f"Patient ID '{p.patient_id}' already exists."
        )

    await r.hset(user_key, mapping={"password": p.password, "patient_id": p.patient_id})
    profile = {
        "name": p.name, "age": p.age, "surgeon": p.surgeon, "procedure": p.procedure,
        "emergency_contact": {"name": p.emergency_name, "phone": p.emergency_phone},
        "allergies": p.allergies,
        "medications": p.medications,
        "red_flags": p.red_flags,
    }
    await r.hset(patient_key, mapping={"profile": json.dumps(profile)})

    pr = PatientRAG(); await pr.init(r)
    docs = []
    def add(kind, text):
        docs.append({"id": f"postop:doc:{p.patient_id}:{kind}:{int(time.time())}",
                     "patient_id": p.patient_id, "kind": kind, "text": text})
    add("summary", f"{p.name} ({p.age}y). Procedure: {p.procedure} by {p.surgeon}.")
    add("contacts", f"Emergency: {p.emergency_name} {p.emergency_phone}")
    if p.allergies:
        add("allergies", "Allergies: " + ", ".join(p.allergies))
    if p.medications:
        meds_lines = [f"{m['name']} {m['dose']} {m['freq']}" for m in p.medications]
        add("meds", "Medication plan: " + "; ".join(meds_lines))
    if p.red_flags:
        add("red_flags", "Critical symptoms: " + "; ".join(p.red_flags))

    from rag import embed
    vecs = embed([d["text"] for d in docs])

    for d, v in zip(docs, vecs):
        d[TEXT_FIELD] = d.pop("text")
        d[VECTOR_FIELD] = np.asarray(v, dtype="float32").tobytes()

    await pr.index.load(docs)

    return {"status":"ok","patient_id": p.patient_id}


@app.post("/chat")
async def chat(body: ChatMsg, patient_id: str = Depends(verify_token)):
    r = await get_redis()
    rag = PatientRAG(); await rag.init(r)

    hits = await rag.search(r, patient_id, body.message, k=6)
    ctx_lines = []
    for h in hits:
        text = h.get("text")
        if isinstance(text, (bytes, bytearray)): text = text.decode()
        ctx_lines.append(f"- {text}")
    context = "\n".join(ctx_lines) if ctx_lines else "(no context)"

    # Build contact_hint
    contact = ""
    for line in ctx_lines:
        if "Emergency:" in line:
            contact = line.replace("- ","")
            break

    system = f"""
        You are a post-operative patient assistant. Use ONLY the provided patient context.
        You MUST return a JSON object with keys: "triage_level", "assistant", and "alert".

        --- Triage Rules ---
        - Level 1: Routine/self-care guidance based on meds/instructions in context.
        - Level 2: Give Level 1 advice AND ask the patient to schedule an appointment with their clinician.
        - Level 3: Inform the patient they will be contacted *shortly* by their emergency contact (listed in the context). Set "alert": true.

        --- Special Conversational Rules ---
        - If the user says "hi", "hello", or "hey":
        - Set "triage_level": 1.
        - Set "assistant": "Hello! I'm here to help with your post-operative questions. We are here for you if you need anything."
        - Set "alert": false.
        - If the user says "thanks" or "thank you":
        - Set "triage_level": 1.
        - Set "assistant": "You're very welcome! We are here for you if you have any other questions."
        - Set "alert": false.
        - If the user says "bye" or "goodbye":
        - Set "triage_level": 1.
        - Set "assistant": "Goodbye! Take care and please remember to stay on track with your prescribed medications. We are here for you."
        - Set "alert": false.

        --- General Rules ---
        - For all other medical or recovery questions, use the Triage Rules.
        - **NEVER** mention medications, dosage, or frequency unless the patient explicitly asks about their medication OR the response is a sign-off (Bye/Goodbye).
        - Never invent medications; quote names/dose/frequency only from context.
        - If info is missing, say so and include clinician contact.
        - Always sound caring and reassuring.

        PATIENT CONTEXT:
        {context}
    """

    raw = chat_llm(system, body.message)

    data = extract_json(raw) 

    triage_level = None
    alert_sent = False
    answer_text = raw # Default to raw text if parsing fails

    if data:
        # Parsing succeeded
        triage_level = int(data.get("triage_level")) if "triage_level" in data else None
        answer_text = data.get("assistant") or "I found some information but could not formulate a reply."

        if data.get("alert") and triage_level == 3:
            # simulate alert: push to Redis list
            await r.lpush(f"postop:alerts:{patient_id}", json.dumps({
                "ts": int(time.time()),
                "patient_id": patient_id,
                "message": body.message
            }))
            alert_sent = True
    else:
        # Parsing failed, use the original fallback logic
        low = body.message.lower()
        if any(k in low for k in ["chest pain","shortness of breath","severe pain","fever 39","fever 40","yellowing"]):
            triage_level = 3
            alert_sent = True
            await r.lpush(f"postop:alerts:{patient_id}", json.dumps({"ts": int(time.time()), "patient_id": patient_id, "message": body.message}))

    return {
        "patient_id": patient_id,
        "context_used": ctx_lines,
        "answer": answer_text, 
        "contact_hint": contact,
        "triage_level": triage_level,
        "alert_sent": alert_sent
    }
