from fastapi import FastAPI, Request, HTTPException
import random
import json
import os
from dotenv import load_dotenv
from livekit import api
import uuid
import boto3
from io import BytesIO
from fastapi.responses import StreamingResponse
import ffmpeg
import asyncio
from livekit.api import ListParticipantsRequest
import datetime

load_dotenv(".env.local")

rand_id = ""

def generate_id():
    return str(uuid.uuid4())

app = FastAPI()

@app.get("/")
def root():
    return {"status": "OK", "message": "Voice AI agent is running"}

async def get_sip_call_status(lkapi, room_name):
    res = await lkapi.room.list_participants(ListParticipantsRequest(
        room=room_name
    ))

    sip_participant = None

    for participant in res.participants:
        # Check if participant kind is SIP (assuming 3 is the SIP kind)
        if participant.kind == 3:
            sip_participant = participant
            break
    
    if sip_participant is None:
        return None  # or raise an exception if no SIP participant found

    return sip_participant.attributes['sip.callStatus']

async def dispatch_call(phone_number: str, prompt: str, name: str):
    rand_id = generate_id()

    # Validate inputs
    if not phone_number:
        return {"error": "Missing phone_number"}
    if not prompt:
        return {"error": "Missing prompt"}
    if not name:
        return {"error": "Missing name"}

    room_name = f"outbound-{''.join(str(random.randint(0, 9)) for _ in range(10))}"

    # Initialize the LiveKit API client
    lkapi = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL"),
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET"),
    )

    # Prepare and send the dispatch request
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

    # await asyncio.sleep(5)

    # last_status = "dialing"

    # while (await get_sip_call_status(lkapi, room_name)) != None:
    #     last_status = await get_sip_call_status(lkapi, room_name)
    #     print(last_status)
    #     await asyncio.sleep(5)  

    await lkapi.aclose()

    return ({
        "room": room_name,
        "phone_number": phone_number,
        "data_id": rand_id,
        # "last_status": last_status
    })

async def batch_dispatch_calls(people: list, prompt: str):
    results = []
    
    for person in people:
        phone_number = person.get("phone_number")
        name = person.get("name")

        try:            
            data = await dispatch_call(phone_number, prompt, name)
            results.append(data)
            await asyncio.sleep(5)
        except Exception as e:
            # If there's an error, add it to the results
            results.append({
                'phone_number': phone_number,
                'error': str(e)
            })
    
    # Create a consolidated result object
    consolidated_data = {
        'batch_id': generate_id(),  # or use uuid.uuid4().hex
        'timestamp': str(datetime.datetime.now()),
        'total_calls': len(people),
        'results': results
    }
    
    # Save the consolidated data to a JSON file
    os.makedirs('batch_data', exist_ok=True)
    file_path = f'batch_data/batch_{consolidated_data["batch_id"]}.json'
    
    with open(file_path, 'w') as f:
        json.dump(consolidated_data, f, indent=2)
    
    return consolidated_data

@app.post("/batch-dispatch")
async def trigger_batch_dispatch(request: Request):
    data = await request.json()
    
    people = data.get("people", [])
    prompt = data.get("prompt")
    
    if not people:
        return {"error": "No people provided"}
    if not prompt:
        return {"error": "Missing prompt"}
    
    # Extract phone numbers and names from people
    phone_numbers = [person.get("phone_number") for person in people]
    names = [person.get("name") for person in people]
    
    if not all(phone_numbers):
        return {"error": "Some people entries are missing phone_number"}
    if not all(names):
        return {"error": "Some people entries are missing name"}
    
    # Start the batch processing
    asyncio.create_task(batch_dispatch_calls(people, prompt))
    
    return {
        "status": "batch dispatch on the way"
    }

@app.post("/dispatch")
async def trigger_dispatch(request: Request):
    data = await request.json()

    phone_number = data.get("phone_number")
    prompt = data.get("prompt")
    name = data.get("name")

    return await (dispatch_call(phone_number, prompt, name))

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

