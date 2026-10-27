"""MLflow UI Launcher with filesystem backend support."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    mlruns_dir = Path("artifacts/mlruns")
    mlruns_dir.mkdir(parents=True, exist_ok=True)

    # Enable filesystem backend for MLflow 3.x
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"

    port = sys.argv[1] if len(sys.argv) > 1 else "5000"

    print("=" * 60)
    print("  Starting MLflow UI Server")
    print("=" * 60)
    print(f"[*] Backend Store:  {mlruns_dir.resolve()}")
    print(f"[*] Access URL:     http://localhost:{port}")
    print("=" * 60)

    cmd = [
        sys.executable,
        "-m",
        "mlflow",
        "ui",
        "--backend-store-uri",
        str(mlruns_dir.as_posix()),
        "--port",
        str(port),
    ]

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n[!] MLflow UI server stopped by user.")


if __name__ == "__main__":
    main()
