from fastapi import FastAPI, Request
import random
import json
import os
from dotenv import load_dotenv
from livekit import api

load_dotenv(".env.local")

app = FastAPI()

@app.get("/")
def root():
    return {"status": "OK", "message": "Voice AI agent is running"}

@app.post("/dispatch")
async def trigger_dispatch(request: Request):
    data = await request.json()
    phone_number = data.get("phone_number")
    prompt = data.get("prompt")
    name = data.get("name")

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

    await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name="outbound-caller",
            room=room_name,
            metadata=json.dumps({
                "phone_number": phone_number,
                "prompt": prompt,
                "name": name
            })
        )
    )
    return {"status": "dispatch started", "room": room_name, "phone_number": phone_number}
