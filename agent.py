from livekit import rtc, api
from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    RunContext,
    get_job_context,
    cli,
    WorkerOptions,
    RoomInputOptions,
)

from livekit.plugins import (
    deepgram,
    groq,
    cartesia,
    silero,
    google,
    openai,
    noise_cancellation,  # noqa: F401
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel
import asyncio
import logging
import os
from dotenv import load_dotenv
import json

load_dotenv(".env.local")
logger = logging.getLogger("voice-ai-agent")
logger.setLevel(logging.INFO)
outbound_trunk_id = os.getenv("OUTBOUND_TRUNK_ID") 

class OutboundCaller(Agent):
    def __init__(self, name: str, prompt: str, dial_info: dict):
        super().__init__(instructions=f"{prompt} Customer's name is: {name}")
        self.participant = None
        self.dial_info = dial_info

    def set_participant(self, participant):
        self.participant = participant

    async def hangup(self):
        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))

    async def transfer_call(self, ctx: RunContext):
        transfer_to = self.dial_info.get("transfer_to")
        if not transfer_to:
            return "cannot transfer call"
        await ctx.session.generate_reply(instructions="Transferring you now...")
        job_ctx = get_job_context()
        try:
            await job_ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job_ctx.room.name,
                    participant_identity=self.participant.identity,
                    transfer_to=f"tel:{transfer_to}",
                )
            )
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            await self.hangup()

    async def end_call(self, ctx: RunContext):
        logger.info(f"Ending call for {self.participant.identity}")
        current_speech = ctx.session.current_speech
        if current_speech:
            await current_speech.wait_for_playout()
        await self.hangup()

    async def detected_answering_machine(self, ctx: RunContext):
        logger.info(f"Voicemail detected for {self.participant.identity}")
        await self.hangup()
    
from datetime import datetime
import json

async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")

    session = AgentSession(
        turn_detection=MultilingualModel(),
        vad=silero.VAD.load(),
        # stt=deepgram.STT(model="nova-3", language="multi"),
        # you can also use OpenAI's TTS with openai.TTS()
        # tts=cartesia.TTS(),
        stt=openai.STT(
            model="gpt-4o-transcribe",
        ),   
        tts=openai.TTS(
            model="gpt-4o-mini-tts"
        ),
        llm=groq.LLM(),
        # you can also use a speech-to-speech model like OpenAI's Realtime API
        # llm=openai.realtime.RealtimeModel()
    )

    async def write_transcript():
        current_date = datetime.now().strftime("%Y%m%d_%H%M%S")

        # This example writes to the temporary directory, but you can save to any location
        filename = f"/tmp/transcript_{ctx.room.name}_{current_date}.json"
        
        with open(filename, 'w') as f:
            json.dump(session.history.to_dict(), f, indent=2)
            
        print(f"Transcript for {ctx.room.name} saved to {filename}")

    ctx.add_shutdown_callback(write_transcript)

    await ctx.connect()

    # when dispatching the agent, we'll pass it the approriate info to dial the user
    # dial_info is a dict with the following keys:
    # - phone_number: the phone number to dial
    # - transfer_to: the phone number to transfer the call to when requested
    info = json.loads(ctx.job.metadata)
    participant_identity = phone_number = info["phone_number"]
    prompt = info["prompt"]

    # look up the user's phone number and appointment details
    agent = OutboundCaller(
        name=info["name"],
        prompt=prompt,
        dial_info=info,
    )

    # start the session first before dialing, to ensure that when the user picks up
    # the agent does not miss anything the user says
    session_started = asyncio.create_task(
        session.start(
            agent=agent,
            room=ctx.room,
            room_input_options=RoomInputOptions(
                # enable Krisp background voice and noise removal
                noise_cancellation=noise_cancellation.BVCTelephony(),
            ),
        )
    )

    # `create_sip_participant` starts dialing the user
    try:
        # print(ctx.room.name, outbound_trunk_id, phone_number, participant_identity)

        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=outbound_trunk_id,
                sip_call_to=phone_number,
                participant_identity=participant_identity,
                # function blocks until user answers the call, or if the call fails
                wait_until_answered=True,
            )
        )

        # wait for the agent session start and participant join
        await session_started
        participant = await ctx.wait_for_participant(identity=participant_identity)
        logger.info(f"participant joined: {participant.identity}")

        agent.set_participant(participant)

    except api.TwirpError as e:
        logger.error(
            f"error creating SIP participant: {e.message}, "
            f"SIP status: {e.metadata.get('sip_status_code')} "
            f"{e.metadata.get('sip_status')}"
        )
        ctx.shutdown()

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )