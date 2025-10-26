# seed.py
import asyncio, uuid, json
from rag import PatientRAG, get_redis

DOCTORS = [
  {"user_id":"admin","password":"test123","role":"doctor","name":"Dr. Admin"}
]

PATIENTS = [
    {
        "user_id": "alice",
        "password": "test123",
        "patient_id": "p1",
        "profile": {
            "name": "Alice Lee", "age": 46,
            "surgeon": "Dr. Patel", "procedure": "Laparoscopic cholecystectomy",
            "emergency_contact": {"name": "Surgery Desk", "phone": "+1-555-200-1000"},
            "allergies": ["penicillin"],
            "medications": [
                {"name": "Amoxicillin", "dose": "500mg", "freq": "q8h", "duration_days": 5},
                {"name": "Ibuprofen", "dose": "400mg", "freq": "q6h prn pain"}
            ],
            "red_flags": [
                "fever > 38.5°C after day 2",
                "worsening right upper quadrant pain",
                "persistent vomiting",
                "yellowing of eyes/skin",
                "shortness of breath"
            ]
        },
    },
    {
        "user_id": "bob",
        "password": "test123",
        "patient_id": "p2",
        "profile": {
            "name": "Bob Singh", "age": 62,
            "surgeon": "Dr. Nguyen", "procedure": "Total knee replacement",
            "emergency_contact": {"name": "Ortho Ward", "phone": "+1-555-400-2233"},
            "allergies": ["sulfa drugs"],
            "medications": [
                {"name": "Paracetamol", "dose": "1g", "freq": "q6h"},
                {"name": "Enoxaparin", "dose": "40mg SC", "freq": "daily x 14 days"},
            ],
            "red_flags": [
                "increasing swelling or redness of leg",
                "severe calf pain",
                "shortness of breath",
                "fever > 38°C",
            ]
        },
    },
    {
        "user_id": "carol",
        "password": "test123",
        "patient_id": "p3",
        "profile": {
            "name": "Carol Wu", "age": 29,
            "surgeon": "Dr. Green", "procedure": "Cesarean section",
            "emergency_contact": {"name": "OB On-Call", "phone": "+1-555-700-5050"},
            "allergies": ["none"],
            "medications": [
                {"name": "Ferrous sulfate", "dose": "325mg", "freq": "daily"},
                {"name": "Ibuprofen", "dose": "600mg", "freq": "q6h prn pain"},
            ],
            "red_flags": [
                "heavy vaginal bleeding",
                "foul-smelling discharge",
                "fever > 38°C",
                "severe abdominal pain",
                "leg swelling",
            ]
        },
    },
    {
        "user_id": "daniel",
        "password": "test123",
        "patient_id": "p4",
        "profile": {
            "name": "Daniel Ortiz", "age": 55,
            "surgeon": "Dr. Johnson", "procedure": "Coronary artery bypass graft",
            "emergency_contact": {"name": "Cardiac ICU", "phone": "+1-555-900-1122"},
            "allergies": ["latex"],
            "medications": [
                {"name": "Aspirin", "dose": "81mg", "freq": "daily"},
                {"name": "Metoprolol", "dose": "50mg", "freq": "bid"},
                {"name": "Atorvastatin", "dose": "40mg", "freq": "qhs"},
            ],
            "red_flags": [
                "chest pain",
                "shortness of breath",
                "dizziness or fainting",
                "fever > 38°C",
                "wound drainage",
            ]
        },
    },
]


async def main():
    r = await get_redis()
    pipe = r.pipeline()
    for p in PATIENTS:
        pipe.hset(f"postop:user:{p['user_id']}", mapping={"password": p["password"], "patient_id": p["patient_id"]})
        pipe.hset(f"postop:patient:{p['patient_id']}", mapping={"profile": json.dumps(p["profile"])})
    
    for d in DOCTORS:
        pipe.hset(f"postop:doctor:{d['user_id']}", mapping={"password": d["password"], "role":"doctor", "name": d["name"]})

    await pipe.execute()

    pr = PatientRAG(); await pr.init(r)
    docs = []
    for p in PATIENTS:
        pid = p["patient_id"]
        prof = p["profile"]
        def add(kind, text):
            docs.append({
              "id": f"postop:doc:{uuid.uuid4()}",
              "patient_id": pid, "kind": kind, "text": text
            })
        add("summary", f"{prof['name']} ({prof['age']}y). Procedure: {prof['procedure']} by {prof['surgeon']}.")
        add("contacts", f"Emergency: {prof['emergency_contact']['name']} {prof['emergency_contact']['phone']}")
        add("allergies", "Allergies: " + ", ".join(prof["allergies"]))
        meds_lines = [f"{m['name']} {m['dose']} {m['freq']}" for m in prof["medications"]]
        add("meds", "Medication plan: " + "; ".join(meds_lines))
        add("red_flags", "Critical symptoms: " + "; ".join(prof["red_flags"]))
    await pr.upsert_docs(r, docs)
    print(f"Seeded {len(PATIENTS)} patients and {len(docs)} docs.")

if __name__ == "__main__":
    asyncio.run(main())
