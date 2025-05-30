import subprocess
import time
import signal
import sys
import os

def main():
    # Start p1 and wait for it to complete first
    p1 = subprocess.Popen(["python3", "agent.py", "download-files"])
    p1.wait()

    # Start server subprocesses p2 and p3
    p2 = subprocess.Popen(["python3", "agent.py", "start"], preexec_fn=os.setsid)
    p3 = subprocess.Popen([
        "uvicorn", "server:app",
        "--host", "0.0.0.0",
        "--port", "8000"
    ], preexec_fn=os.setsid)

    processes = [p2, p3]  # Store processes for easy handling

    def shutdown(signum, frame):
        print("\nShutting down servers...")
        for p in processes:
            if p and p.poll() is None:  # Check if process exists and is running
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print(f"{p.args} did not terminate, killing...")
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except ProcessLookupError:
                    print(f"Process {p.args} already exited.")
            else:
                print(f"Process {p.args} is not running or already terminated.")
        print("Servers stopped.")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Servers started. Press Ctrl+C to stop.")
    try:
        while True:
            for p in processes:
                if p.poll() is not None:
                    print(f"Server {p.args} exited unexpectedly.")
                    shutdown(None, None)
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)

if __name__ == "__main__":
    main()
