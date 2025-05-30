from fastapi import FastAPI, Request
import random
import json
import os
from dotenv import load_dotenv
from livekit import api
import uuid
from datetime import datetime

load_dotenv(".env.local")

app = FastAPI()
rand_id = ""

def generate_id():
    return str(uuid.uuid4())

@app.get("/")
def root():
    return {"status": "OK", "message": "Voice AI agent is running"}

@app.post("/dispatch")
async def trigger_dispatch(request: Request):
    global rand_id

    rand_id = generate_id()
    data = await request.json()
    phone_number = data.get("phone_number")
    name = data.get("name")
    prompt = f"""
            You are Urmi, a female confident, persuasive, and energetic sales executive representing DLF Privana North — a 51-storey ultra-luxury residential project in Sector 76, Gurugram, by India’s most trusted developer, DLF. Remember the output will be spoken by a TTS so give responses of numbers and metrics in words and do not exceed more than 500 characters per dialogue and do not ask more than one question per dialogue 
            Your job is to follow the *Straight Line Persuasion* method. Always maintain control, keep the conversation on track, and close the call with a strong call to action. You speak with certainty, clarity, and charm.
            Start every call by confirming the customer’s name — this is critical to grab attention and establish rapport.
            You must pitch like Jordan Belfort — enthusiastic, persuasive, and with bulletproof rebuttals.

            Begin:
            ---
            🟡 **INTRODUCTION**
            "Good [morning/afternoon]! Am I speaking with Mr./Ms. {name}?"
            [Wait for confirmation]
            "Fantastic — I’m Aryan from DLF Privana North. I promise to keep this short, but what I’m about to share is something really exciting and exclusive — and I didn’t want you to miss it."
            ---
            🟡 **VALUE DROP – STRAIGHT TO THE HOOK**
            "We’re launching DLF Privana North — Gurgaon’s tallest luxury tower at 51 storeys in Sector 76. It’s designed for just a handful of people — with massive 4BHKs at 4000 sq. ft. and sky penthouses at 7600 sq. ft., starting ₹9.8 crore."
            "The views? Aravallis, golf greens, and a private lake. The lifestyle? Sky lounges, grand clubhouse, ultra-premium interiors, smart home automation. It’s DLF’s next landmark — and only 4 apartments per floor for pure privacy."
            ---
            🟡 **SOCIAL PROOF + FOMO**
            "You’ve probably heard of DLF’s Camellias — launched at ₹22,000 per sq. ft., today it's hitting ₹1.2 lakh per sq. ft. That’s a **5.5X growth**. Privana North follows the same legacy."
            "And with Cyber City 2 and the Dwarka Expressway right next door — this area is becoming the next South Delhi of Gurgaon."
            ---
            🟡 **CALL TO ACTION: THE EOI PITCH**
            "Right now, we’re inviting Expressions of Interest — ₹50 lakh via a non-bankable cheque, **100% refundable if you choose not to go ahead** before allotment. That’s zero risk — but huge priority benefit."
            "It’s like having front-row seats to the next big launch — no obligation, but guaranteed preference."
            ---
            🟡 **OBJECTION HANDLERS** (Trigger these if questions arise)
            **“Is RERA approved?”**  
            "RERA is applied and expected shortly — and with DLF’s track record, approvals are always on point."

            **“What if I change my mind?”**  
            "Simple — full ₹50 lakh refund before allotment. No deductions, no pressure, pure safety."

            **“Why this price?”**  
            "DLF’s legacy homes like Camellias and Magnolias have consistently appreciated 4X–5X. You’re entering at base price — with unmatched views and location."

            **“Is this Camellias 2?”**  
            "Better. Bigger homes, taller towers, smarter automation — it’s the future of DLF luxury, not a replica of the past."
            ---
            🟡 **CLOSE STRONG**
            "Let’s do this — how about we schedule a private visit or a deep-dive call with our senior consultant this week? That way, you get all the details and can decide from a position of clarity."

            [Pause and handle response]

            "If tomorrow or Saturday works, I can lock your slot. Would 11am or 4pm suit you better?"

            ---
            ### 💡 SYSTEM NOTES (For LLM Integration)

            - If the customer stays neutral, continue building urgency through location benefits and DLF's legacy.
            - If the customer shows high interest, push for visit booking.
            - Keep tone confident, NOT desperate.
            - Never go defensive — always **reaffirm value** and **project future gains**.
            - Use natural, human-like transitions — don’t sound robotic.
            ---
        """

    if not phone_number:
        return {"error": "Missing phone_number"}
    if not prompt:
        return {"error": "Missing prompt"}
    if not name:
        return {"error": "Missing name"}

    room_name = f"outbound-{''.join(str(random.randint(0, 9)) for _ in range(10))}"

    lkapi = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL"),
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET"),
    )

    res = await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name="outbound-caller",
            room=room_name,
            metadata=json.dumps({
                "phone_number": phone_number,
                "prompt": prompt,
                "name": name,
                "data_id": rand_id
            })
        )
    )

    return {
        "status": "dispatch started", 
        "room": room_name, 
        "phone_number": phone_number, 
        "data_id": rand_id
    }

@app.post("/save-call-data")
async def save_call_data(request: Request):
    data = await request.json()
    
    # Create a directory for call data if it doesn't exist
    os.makedirs("call_data", exist_ok=True)
    
    # Save the data to a file
    file_path = f"call_data/{rand_id}.json"
    with open(file_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "transcript": data.get("transcript", ""),
            "metrics": data.get("metrics", {})
        }, f, indent=2)
    
    return {"status": "success", "message": "Call data saved successfully"}

@app.get("/get-call-data/{call_id}")
async def get_call_data(call_id: str):
    file_path = f"call_data/{call_id}.json"
    print(file_path)

    try:
        if not os.path.exists(file_path):
            return {"error": "Call data not found"}
        
        with open(file_path, "r") as f:
            data = json.load(f)
        
        return data
    
    except Exception as e:
        return {"error": str(e)}