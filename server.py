from fastapi import FastAPI, Request, HTTPException
import random
import json
import os
from dotenv import load_dotenv
from livekit import api
import uuid
import boto3
from io import BytesIO
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import ffmpeg
from fastapi.middleware.cors import CORSMiddleware
import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import json
import os
import pytz

# CORS configuration
origins = [
    "*"
]

load_dotenv(".env.local")

# Create templates directory if it doesn't exist
os.makedirs("templates", exist_ok=True)

# Mount templates directory
templates = Jinja2Templates(directory="templates")

rand_id = ""

import json
import os

def prepend_to_json_file(obj, filename='data.json'):
    # Check if file exists
    if os.path.exists(filename):
        with open(filename, 'r+', encoding='utf-8') as file:
            try:
                data = json.load(file)
                if not isinstance(data, list):
                    raise ValueError("JSON content must be a list.")
            except json.JSONDecodeError:
                data = []

            data.insert(0, obj)  # Prepend the object
            file.seek(0)
            json.dump(data, file, indent=4)
            file.truncate()
    else:
        with open(filename, 'w', encoding='utf-8') as file:
            json.dump([obj], file, indent=4)


def generate_id(phone_number, name):
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.datetime.now(ist).strftime("%B-%d-%Y_%I-%M-%S_%p_IST")
    random_hex = f"{random.randint(0, 0xFFF):03X}"                   # 3-digit uppercase hex
    clean_name = ''.join(e for e in name if e.isalnum()).lower()    # Sanitize name
    return f"{phone_number}_{clean_name}_{now}_{random_hex}"


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],              # allowed origins
    allow_credentials=True,             # allow cookies or auth headers
    allow_methods=["*"],                # allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],                # allow all headers
)

from fastapi import FastAPI, Request, Header, HTTPException
from livekit.api.webhook import WebhookReceiver
from livekit.api.access_token import TokenVerifier
import logging

# Replace with your actual LiveKit API Key and Secret
API_KEY=os.getenv("LIVEKIT_API_KEY")
API_SECRET=os.getenv("LIVEKIT_API_SECRET")

# Initialize TokenVerifier and WebhookReceiver
token_verifier = TokenVerifier(API_KEY, API_SECRET)
webhook_receiver = WebhookReceiver(token_verifier)

# Optional: Set up logging
# logging.basicConfig(level=logging.INFO)

call_status = False

@app.post("/")
async def receive_webhook(request: Request, authorization: str = Header(None)):
    global call_status
    try:
        if authorization is None:
            raise HTTPException(status_code=401, detail="Authorization header missing")

        # Get raw body of the request
        body = await request.body()
        body_str = body.decode("utf-8")

        # Verify and parse the webhook
        event = webhook_receiver.receive(body_str, authorization)

        if event.event == "room_finished":
            call_status = False

        print(event.event)
        # logging.info(f"Received Webhook Event: {event}")
        return {"status": "ok", "event": event.DESCRIPTOR.name}
    except Exception as e:
        logging.error(f"Webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# @app.middleware("http")
# async def log_request(request: Request, call_next):
#     try:
#         body = await request.body()
#         print(f"Received request: {request.method} {request.url} with body: {body}")
#     except Exception as e:
#         print(f"Error reading request body: {e}")
#     return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

async def dispatch_call(phone_number: str, prompt: str, name: str):
    global call_status

    if call_status:
        return { "message": "call in place" }

    rand_id = generate_id(phone_number, name)

    # Validate inputs
    if not phone_number:
        return {"error": "Missing phone_number"}
    if not prompt:
        return {"error": "Missing prompt"}
    if not name:
        return {"error": "Missing name"}

    room_name = "tele_room"

    # Initialize the LiveKit API client
    lkapi = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL"),
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET"),
    )

    # Prepare and send the dispatch request
    dispatch = await lkapi.agent_dispatch.create_dispatch(
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

    call_status = True

    await lkapi.aclose()

    prepend_to_json_file({
        "data_id": rand_id
    })

    # token = "eyJhbGciOiJIUzI1NiJ9.eyJtZXRhZGF0YSI6IntcInJvbGVcIjpcImhvc3RcIn0iLCJuYW1lIjoic2Rhc2RhIiwidmlkZW8iOnsicm9vbSI6InRlc3Rfcm9vbSIsInJvb21Kb2luIjp0cnVlLCJjYW5QdWJsaXNoIjp0cnVlLCJjYW5QdWJsaXNoRGF0YSI6dHJ1ZSwiY2FuU3Vic2NyaWJlIjp0cnVlfSwiaXNzIjoiQVBJTmNDU0FMaTZuOXNhIiwiZXhwIjoxNzQ5MDg2ODM2LCJuYmYiOjAsInN1YiI6InNkYXNkYV9fIn0.0wQ0xSnXOAJXGjpkDp67yLyyz-sP67eD_4aCXsh8KHc"
    # token = createParticipantToken("urmi_fe", room_name)

    return ({
        "room": room_name,
        "phone_number": phone_number,
        "data_id": rand_id,
        # "token": token
    })

def createParticipantToken(userInfo, roomName):
    token = api.AccessToken(
        os.getenv('LIVEKIT_API_KEY'),
        os.getenv('LIVEKIT_API_SECRET')
    ).with_identity(userInfo) \
     .with_name(userInfo) \
     .with_grants(api.VideoGrants(
        room_join=True,
        room=roomName,
        can_publish=False,
        can_publish_data=False,
        can_subscribe=False
    ))
    
    return token.to_jwt()

@app.get("/get_curr_call_stat")
async def get_call_stat(request: Request):
    global call_status
    if not call_status:
        return { "message": "no call in place" }
    
    lkapi = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL"),
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET"),
    )
    
    dispatches = await lkapi.agent_dispatch.list_dispatch(room_name="tele_room")

    print(dispatches)

    return {}

@app.get("/get_call_logs")
def get_data():
    if not os.path.exists("data.json"):
        return JSONResponse(content=[], status_code=200)
    
    try:
        with open("data.json", 'r', encoding='utf-8') as file:
            data = json.load(file)
            if not isinstance(data, list):
                raise ValueError("Data is not a list")
            return JSONResponse(content=data)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"Error reading JSON file: {e}")

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
        ogg_bytes = ogg_data.getvalue()  # Get all bytes at once
        
        # Validate that we actually got data
        if len(ogg_bytes) == 0:
            raise HTTPException(status_code=404, detail="File is empty")
            
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found or S3 error: {e}")
    
    # Step 2: Use ffmpeg-python to convert ogg -> mp3 in memory
    try:
        # Input stream from ogg_data bytes
        process = (
            ffmpeg
            .input('pipe:0', format='ogg')  # Explicitly specify input format
            .output('pipe:1', format='mp3', acodec='libmp3lame', audio_bitrate='192k')
            .overwrite_output()  # Handle any potential conflicts
            .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
        )
        
        # Use the raw bytes instead of reading from BytesIO again
        stdout, stderr = process.communicate(input=ogg_bytes)
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown ffmpeg error"
            raise RuntimeError(f"ffmpeg error: {error_msg}")
            
        # Validate output
        if not stdout or len(stdout) == 0:
            raise RuntimeError("ffmpeg produced empty output")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio conversion error: {e}")
    
    # Step 3: Return the MP3 file with proper headers for auto-download
    clean_filename = filename.rsplit('.', 1)[0] if '.' in filename else filename
    
    return StreamingResponse(
        BytesIO(stdout), 
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f"attachment; filename=\"{clean_filename}.mp3\"",
            "Content-Length": str(len(stdout)),
            "Cache-Control": "no-cache"
        }
    )