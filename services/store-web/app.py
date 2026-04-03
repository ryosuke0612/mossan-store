from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.service_host import build_store_web_app


def create_app():
    return build_store_web_app()


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
