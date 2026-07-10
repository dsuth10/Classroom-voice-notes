# scripts/watch_inbox_worker.py
import os
import sys

# Add project root to path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.worker.broker_worker import BrokerWorker

def main() -> None:
    print("=== Classroom Voice Notes: Production Broker Worker ===")
    
    config = {
        "poll_interval_seconds": int(os.getenv("CVN_POLL_INTERVAL_SECONDS", "5")),
        "openclaw": {
            "gateway_url": os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789"),
            "responses_path": "/v1/responses",
            "agent_id": os.getenv("OPENCLAW_AGENT_ID", "cvn-broker"),
            "normal_timeout_seconds": int(os.getenv("OPENCLAW_NORMAL_TIMEOUT_SECONDS", "120")),
            "maximum_timeout_seconds": int(os.getenv("OPENCLAW_MAXIMUM_TIMEOUT_SECONDS", "1500")),
            "maximum_output_tokens": int(os.getenv("OPENCLAW_MAXIMUM_OUTPUT_TOKENS", "2000")),
            "maximum_result_characters": int(os.getenv("OPENCLAW_MAXIMUM_RESULT_CHARACTERS", "20000")),
            "connect_timeout_seconds": float(os.getenv("OPENCLAW_CONNECT_TIMEOUT_SECONDS", "10.0"))
        }
    }
    
    try:
        worker = BrokerWorker(config)
        worker.run()
    except KeyboardInterrupt:
        print("\n[+] Worker shutdown initiated by operator.")
    except Exception as e:
        print(f"[-] Fatal worker error during execution: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
