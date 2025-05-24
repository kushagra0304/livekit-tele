import subprocess
import time
import signal
import sys

def main():
    # Start both server subprocesses
    p2 = subprocess.Popen([
        "uvicorn", "server:app",
        "--host", "0.0.0.0",
        "--port", "8000"
    ])
    p1 = subprocess.Popen(["python3", "agent.py", "start"])

    def shutdown(signum, frame):
        print("\nShutting down servers...")
        p1.terminate()
        p2.terminate()
        p1.wait()
        p2.wait()
        print("Servers stopped.")
        sys.exit(0)

    # Handle Ctrl+C and termination signals gracefully
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Both servers started. Press Ctrl+C to stop.")

    # Keep main thread alive while servers run
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
