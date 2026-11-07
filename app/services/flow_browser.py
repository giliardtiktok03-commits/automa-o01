"""Local Flow browser profile and automatic generation handoff. No Google passwords."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse
import uuid

from filelock import FileLock, Timeout
from PIL import Image

from app.utils import utils
from app.services import task_artifacts


class FlowError(ValueError):
    def __init__(self, message, *, key=None):
        super().__init__(message)
        self.key = key


class FlowRefusal(FlowError):
    pass


def normalized(profile, project):
    # Trim pasted boundary whitespace/format markers; never change internal IDs.
    def trim(value):
        return str(value or "").strip().strip("\u200b\ufeff").strip()
    return trim(profile), trim(project)


def validate(profile, project):
    profile, project = normalized(profile, project)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", profile):
        raise FlowError("Use a profile name with 1-48 letters, numbers, underscores or hyphens", key="flow.invalid_profile")
    u = urlparse(project)
    if (u.scheme != "https" or u.netloc != "flow.google.com" or u.query or u.fragment
            or not re.fullmatch(r"/project/[0-9a-fA-F-]{36}/?", u.path)):
        raise FlowError("Use the HTTPS Flow project URL, without extra query parameters", key="flow.invalid_project")
    uuid.UUID(u.path.strip('/').split('/')[-1])
    if importlib.util.find_spec("playwright") is None:
        raise FlowError("Run PREPARAR_FLOW_WINDOWS.bat first to install the optional browser integration", key="flow.setup_required")


def _root():
    return Path(utils.storage_dir("flow_browser", create=True))


def _launch(request):
    return subprocess.Popen([sys.executable, "-m", "app.services.flow_browser", "--request", str(request)],
                            cwd=utils.root_dir(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def connect(profile, project):
    profile, project = normalized(profile, project)
    validate(profile, project)
    folder = _root() / "requests"
    folder.mkdir(exist_ok=True)
    request = folder / (uuid.uuid4().hex + ".json")
    task_artifacts._write_json_atomic(request, {"profile": profile, "project": project, "action": "connect"})
    _launch(request)
    return request.with_suffix(".result.json")



def start_test(profile, project, require_zero=True):
    from app.services.ai33.policy import reject_legacy_generation
    reject_legacy_generation()

def generate(prompt, directory, profile, project, timeout=900, require_zero=True):
    from app.services.ai33.policy import reject_legacy_generation
    reject_legacy_generation()


def _save_image(download, target):
    temporary = target.with_suffix('.download')
    try:
        download.save_as(str(temporary))
        if temporary.stat().st_size > 25 * 1024 * 1024:
            raise FlowError("Downloaded file exceeds 25 MB")
        with Image.open(temporary) as image:
            if image.width * image.height > 50_000_000:
                raise FlowError("Image exceeds 50 million pixels")
            image.load()
            image.convert("RGB").save(target, format="PNG")
    finally:
        temporary.unlink(missing_ok=True)


def _browser(request_file):
    data = json.loads(request_file.read_text(encoding="utf-8"))
    validate(data["profile"], data["project"])
    result_file = request_file.with_suffix(".result.json")
    profile_root = _root() / "profiles"
    profile_root.mkdir(exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
        with FileLock(str(profile_root / (data["profile"] + '.lock')), timeout=0), sync_playwright() as p:
            # Visible installed Chrome; no stealth flags, password collection or
            # CAPTCHA/quota bypass. Google may disallow login in automation.
            context = p.chromium.launch_persistent_context(str(profile_root / data["profile"]),
                        channel="chrome", headless=False, accept_downloads=True, chromium_sandbox=True)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                if data["action"] == "connect":
                    page.goto(data["project"], wait_until="domcontentloaded", timeout=60000)
                    while context.pages:
                        try:
                            page.wait_for_timeout(500)
                        except Exception:
                            if not context.pages:
                                break
                            raise
                    task_artifacts._write_json_atomic(result_file, {"status": "closed"})
                    return
                from app.services import flow_automation
                page.goto(data["project"], wait_until="domcontentloaded", timeout=60000)
                target = request_file.with_suffix('.png')
                try:
                    flow_automation.generate(page, data['prompt'], target, timeout=data.get('timeout',900),
                                             require_zero=data.get('require_zero',True))
                    result = {"status": "ready"}
                except FlowRefusal:
                    result = {"status": "refused"}
                except FlowError as exc:
                    result = {"status": "failed", "error": str(exc)}
                task_artifacts._write_json_atomic(result_file, result)
            finally:
                context.close()
    except Timeout:
        task_artifacts._write_json_atomic(result_file, {"status": "failed", "error": "Close the existing Flow connection window before generating"})
    except Exception:
        task_artifacts._write_json_atomic(result_file, {"status": "failed", "error": "Browser closed or unavailable. Check installed Chrome and the optional Playwright dependency. No automatic retry."})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    _browser(Path(parser.parse_args().request).resolve())
