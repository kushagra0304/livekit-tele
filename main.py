import subprocess
import time
import signal
import sys

def main():
    # Start p1 and wait for it to complete first
    p1 = subprocess.Popen(["python3", "agent.py", "download-files"])
    p1.wait()  # Wait until p1 completes before starting servers

    # Start server subprocesses p2 and p3
    p2 = subprocess.Popen(["python3", "agent.py", "start"])
    p3 = subprocess.Popen([
        "nohup", "uvicorn", "server:app",
        "--host", "0.0.0.0",
        "--port", "8000"
    ])

    def shutdown(signum, frame):
        print("\nShutting down servers...")
        for p in (p2, p3):
            p.terminate()
        # Wait briefly, then kill if not exited
        for p in (p2, p3):
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"{p.args} did not terminate, killing...")
                p.kill()
        print("Servers stopped.")
        sys.exit(0)

    # Handle Ctrl+C and termination signals gracefully
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Servers started. Press Ctrl+C to stop.")

    # Keep main thread alive while servers run
    try:
        while True:
            # Check if any server exited unexpectedly
            if p2.poll() is not None:
                print("Server p2 exited unexpectedly.")
                shutdown(None, None)
            if p3.poll() is not None:
                print("Server p3 exited unexpectedly.")
                shutdown(None, None)
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
