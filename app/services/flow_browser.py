"""Local, user-assisted Flow browser profile. Never stores Google passwords."""
import argparse
import html
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlparse
import uuid

from filelock import FileLock, Timeout
from PIL import Image

from app.utils import utils
from app.services import task_artifacts


class FlowError(ValueError):
    pass


class FlowRefusal(FlowError):
    pass


def validate(profile, project):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", profile):
        raise FlowError("Use a profile name with 1-48 letters, numbers, underscores or hyphens")
    u = urlparse(project)
    if (u.scheme != "https" or u.netloc != "flow.google.com" or u.query or u.fragment
            or not re.fullmatch(r"/project/[0-9a-fA-F-]{36}/?", u.path)):
        raise FlowError("Use the HTTPS Flow project URL, without extra query parameters")
    uuid.UUID(u.path.strip('/').split('/')[-1])
    if importlib.util.find_spec("playwright") is None:
        raise FlowError("Run PREPARAR_FLOW_WINDOWS.bat first to install the optional browser integration")


def _root():
    return Path(utils.storage_dir("flow_browser", create=True))


def _launch(request):
    return subprocess.Popen([sys.executable, "-m", "app.services.flow_browser", "--request", str(request)],
                            cwd=utils.root_dir(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def connect(profile, project):
    validate(profile, project)
    folder = _root() / "requests"
    folder.mkdir(exist_ok=True)
    request = folder / (uuid.uuid4().hex + ".json")
    task_artifacts._write_json_atomic(request, {"profile": profile, "project": project, "action": "connect"})
    _launch(request)
    return request.with_suffix(".result.json")


def generate(prompt, directory, profile, project, timeout=900):
    validate(profile, project)
    folder = Path(directory)
    request = folder / ("flow-" + uuid.uuid4().hex + ".json")
    task_artifacts._write_json_atomic(request, {"profile": profile, "project": project, "action": "generate",
                                              "prompt": prompt, "timeout": timeout})
    result_file = request.with_suffix(".result.json")
    process = _launch(request)
    try:
        process.wait(timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)
        raise FlowError("Flow browser timed out; review the project before any new generation") from None
    if not result_file.exists():
        raise FlowError("Flow browser closed without a result; review the project before retrying")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if result.get("status") == "refused":
        raise FlowRefusal("User reported an explicit Flow refusal; no resubmission")
    if result.get("status") != "ready":
        raise FlowError(result.get("error", "Flow did not provide an image"))
    image = request.with_suffix(".png")
    if not image.is_file():
        raise FlowError("Flow image file is missing")
    return image


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
                        channel="chrome", headless=False, accept_downloads=True)
            try:
                page = context.new_page()
                if data["action"] == "connect":
                    page.goto(data["project"], wait_until="domcontentloaded", timeout=60000)
                    while context.pages:
                        page.wait_for_timeout(500)
                    task_artifacts._write_json_atomic(result_file, {"status": "closed"})
                    return
                outcome = {}
                target = request_file.with_suffix('.png')
                def receive(download):
                    if urlparse(download.page.url).hostname != "flow.google.com":
                        return
                    try:
                        _save_image(download, target)
                        outcome["status"] = "ready"
                    except Exception:
                        outcome.update(status="failed", error="Download is not a usable image")
                page.on("download", receive)
                control = context.new_page()
                control.set_content('<meta charset="utf-8"><h2>MPT — Google Flow</h2>'
                    '<p>Copie o prompt abaixo. No Flow, selecione Imagem, confira proporção, modelo e créditos. '
                    'Escolha quantidade x1. Gere uma imagem e clique em Download no próprio Flow. O MPT recebe o arquivo e continua.</p>'
                    '<p>Não baixe outra imagem durante este pedido. Não há garantia de gratuidade. '
                    'Se aparecer CAPTCHA ou limite, cancele e resolva diretamente no serviço.</p>'
                    '<textarea style="width:95%;height:240px">' + html.escape(data['prompt']) + '</textarea>'
                    '<p><button onclick="document.title=\'MPT_REFUSED\'">Flow recusou por segurança</button> '
                    '<button onclick="document.title=\'MPT_CANCEL\'">Cancelar / limite / CAPTCHA</button></p>')
                page.goto(data["project"], wait_until="domcontentloaded", timeout=60000)
                # Best-effort prefill only. The user confirms generation/model/
                # credits and download; never invokes undocumented Google APIs.
                editors = page.locator('textarea, [contenteditable="true"][role="textbox"]')
                if editors.count() == 1 and editors.first.is_visible():
                    try:
                        editors.first.fill(data["prompt"], timeout=2000)
                    except Exception:
                        pass
                control.bring_to_front()
                deadline = time.monotonic() + data.get("timeout", 900)
                while not outcome and time.monotonic() < deadline:
                    title = control.title()
                    if title == 'MPT_REFUSED':
                        outcome['status'] = 'refused'
                    elif title == 'MPT_CANCEL':
                        outcome.update(status='cancelled', error='Flow cancelled by user; no automatic retry')
                    page.wait_for_timeout(250)
                if not outcome:
                    outcome.update(status='timeout', error='Flow timed out; review the project before retrying')
                task_artifacts._write_json_atomic(result_file, outcome)
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
