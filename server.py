from fastapi import FastAPI, Request, HTTPException
import random
import json
import os
from dotenv import load_dotenv
from livekit import api
import uuid
from datetime import datetime
import boto3
from io import BytesIO
from fastapi.responses import StreamingResponse
import ffmpeg

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
    
@app.get("/get-all-call-data")
async def get_all_call_data():
    try:
        # Check if call_data directory exists
        if not os.path.exists("call_data"):
            return {"error": "No call data directory found"}
        
        # Get all JSON files in the call_data directory
        call_data_files = [f for f in os.listdir("call_data") if f.endswith('.json')]
        
        # Read and combine all call data
        all_calls = []
        for file_name in call_data_files:
            file_path = os.path.join("call_data", file_name)
            with open(file_path, "r") as f:
                data = json.load(f)
                # Add the call_id (filename without .json extension) to the data
                data["call_id"] = file_name.replace(".json", "")
                all_calls.append(data)
        
        return {"calls": all_calls}
    
    except Exception as e:
        return {"error": str(e)}
    

# Initialize boto3 S3 client
s3_client = boto3.client(
    's3',                     
    aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("S3_SECERET"),
    region_name='ap-south-1'
)

BUCKET_NAME = 'livekit-tele'

@app.get("/get-recording/{filename}")
async def convert_ogg_to_mp3(filename: str):
    # Step 1: Download OGG file from S3 into memory
    ogg_data = BytesIO()
    try:
        s3_client.download_fileobj(BUCKET_NAME, "recordings/"+filename+".ogg", ogg_data)
        ogg_data.seek(0)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found or S3 error: {e}")

    # Step 2: Use ffmpeg-python to convert ogg -> mp3 in memory
    try:
        # Input stream from ogg_data bytes
        process = (
            ffmpeg
            .input('pipe:0')
            .output('pipe:1', format='mp3', audio_bitrate='192k')
            .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
        )

        out, err = process.communicate(input=ogg_data.read())

        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg error: {err.decode()}")

        mp3_data = BytesIO(out)
        mp3_data.seek(0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio conversion error: {e}")

    # Step 3: Return the MP3 file
    return StreamingResponse(mp3_data, media_type="audio/mpeg",
                             headers={"Content-Disposition": f"attachment; filename={filename.rsplit('.', 1)[0]}.mp3"})
