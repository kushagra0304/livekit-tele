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
    function_tool
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
from livekit.plugins.turn_detector.english import EnglishModel
import asyncio
import logging
import os
from dotenv import load_dotenv
import json
from livekit.agents import metrics, MetricsCollectedEvent

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

    @function_tool()
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

    @function_tool()
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
        turn_detection=EnglishModel(),
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3"),
        # you can also use OpenAI's TTS with openai.TTS()
        tts=cartesia.TTS(),
        # stt=openai.STT(
        #     model="gpt-4o-transcribe",
        # ),   
        # tts=openai.TTS(
        #     model="gpt-4o-mini-tts"
        # ),
        # stt=google.STT(
        #     model="telephony",
        #     spoken_punctuation=False,
        # ),        
        # tts=google.TTS(
        #     voice_name="hi-IN-Chirp3-HD-Achernar",
        #     gender="female",
        #     language="hi-IN"
        # ),        
        llm=groq.LLM(),
        # you can also use a speech-to-speech model like OpenAI's Realtime API
        # llm=openai.realtime.RealtimeModel()
    )

    # ------------------------------------------------------------
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        return summary
    # ------------------------------------------------------------

    info = json.loads(ctx.job.metadata)
    participant_identity = phone_number = info["phone_number"]
    prompt = info["prompt"]
    data_id = info["data_id"]

    async def write_transcript():
        # Create directory for storing transcripts, if it doesn't exist
        output_dir = "call_data"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, (data_id + ".json"))

        try:
            summary = await log_usage()
            logger.info(f"Usage: {summary}")

            # Prepare the data to save
            data_to_save = {
                "name": info["name"],
                "number": phone_number,
                "transcript": session.history.to_dict(),
                "metrics": {
                    "tts_characters_count": summary.tts_characters_count,
                    "stt_audio_duration": summary.stt_audio_duration,
                    "llm_prompt_tokens": summary.llm_prompt_tokens,
                    "llm_prompt_cached_tokens": summary.llm_prompt_cached_tokens,
                    "llm_completion_tokens": summary.llm_completion_tokens
                }
            }

            # Save the data as a JSON file
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=4)

            logger.info(f"Call data saved successfully to {filepath}")

        except Exception as e:
            logger.error(f"Failed to save call data: {e}")

    req = api.RoomCompositeEgressRequest(
        room_name=ctx.room.name,
        audio_only=True,
        file_outputs=[api.EncodedFileOutput(
            file_type=api.EncodedFileType.OGG,
            filepath=f"""recordings/{data_id}.ogg""",
            s3=api.S3Upload(
                bucket="livekit-tele",
                region="ap-south-1",
                access_key=os.getenv("S3_ACCESS_KEY"),
                secret=os.getenv("S3_SECERET"),
            ),
        )],
    )

    lkapi = api.LiveKitAPI()
    res = await lkapi.egress.start_room_composite_egress(req)
    print(res)
    await lkapi.aclose()


    ctx.add_shutdown_callback(write_transcript)
    await ctx.connect()

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