#!/usr/bin/env python3
"""FrameLab local server backed by the installed Codex app-server."""

import cgi
import json
import mimetypes
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("FRAME_LAB_DATA_DIR", ROOT)).expanduser().resolve()
DEFAULT_PRESETS_DIR = ROOT / "presets"
PRESETS_DIR = DATA_ROOT / "presets"
OUTPUTS_DIR = DATA_ROOT / "outputs"
UPLOADS_DIR = DATA_ROOT / ".uploads"
IMAGEGEN_SKILL = Path.home() / ".codex" / "skills" / ".system" / "imagegen" / "SKILL.md"
CODEX_CANDIDATES = [
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path("/Applications/Codex.app/Contents/Resources/codex"),
]
MAX_BODY_BYTES = 80 * 1024 * 1024
MAX_FILES = 8
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
STYLE_FILES = {
    "felt": "03-felt-mini.txt",
    "watercolor": "04-watercolor.txt",
    "doodle": "06-pinterest-doodle.txt",
    "vintage": "07-vintage-poster.txt",
}
STYLE_META = {
    "felt": {
        "name": "펠트 미니미",
        "description": "폭닥한 수공예 디오라마",
        "thumbnail": "/photo-edit-assets/03-felt-mini.jpg",
    },
    "watercolor": {
        "name": "감성 수채화",
        "description": "투명한 물감과 종이결",
        "thumbnail": "/photo-edit-assets/04-watercolor.jpg",
    },
    "doodle": {
        "name": "핀터 손그림",
        "description": "검은 선과 포인트 컬러",
        "thumbnail": "/photo-edit-assets/06-pinterest-doodle.jpg",
    },
    "vintage": {
        "name": "빈티지 포스터",
        "description": "구아슈 여행 포스터",
        "thumbnail": "/photo-edit-assets/07-vintage-poster.jpg",
    },
}
JOBS = {}
JOBS_LOCK = threading.Lock()
GENERATION_LOCK = threading.Lock()

DATA_ROOT.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
PRESETS_DIR.mkdir(exist_ok=True)
for preset_name in STYLE_FILES.values():
    destination = PRESETS_DIR / preset_name
    source = DEFAULT_PRESETS_DIR / preset_name
    if not destination.exists() and source.is_file():
        shutil.copyfile(source, destination)


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def find_codex():
    configured = os.environ.get("FRAME_LAB_CODEX")
    if configured and Path(configured).is_file():
        return Path(configured)
    command = shutil.which("codex")
    if command:
        return Path(command)
    candidates = list(CODEX_CANDIDATES)
    if platform.system() == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        codex_bin_root = local_app_data / "OpenAI" / "Codex" / "bin"
        candidates.extend(codex_bin_root.glob("*/codex.exe"))
        candidates.append(codex_bin_root / "codex.exe")
    existing = [path for path in candidates if path.is_file()]
    return max(existing, key=lambda path: path.stat().st_mtime, default=None)


def codex_command(codex_path, *arguments):
    if platform.system() == "Windows" and codex_path.suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", str(codex_path), *arguments]
    return [str(codex_path), *arguments]


def set_job(job_id, **changes):
    with JOBS_LOCK:
        JOBS[job_id].update(changes)


def preset_payload():
    presets = []
    for style, filename in STYLE_FILES.items():
        path = PRESETS_DIR / filename
        presets.append({
            "id": style,
            "fileName": filename,
            "prompt": path.read_text(encoding="utf-8") if path.is_file() else "",
            **STYLE_META[style],
        })
    return presets


def history_payload():
    records = []
    for metadata_path in OUTPUTS_DIR.glob("*/metadata.json"):
        try:
            record = json.loads(metadata_path.read_text(encoding="utf-8"))
            records.append(record)
        except (OSError, json.JSONDecodeError):
            continue
    records.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    return records[:100]


def open_local_folder(target):
    folders = {"outputs": OUTPUTS_DIR, "presets": PRESETS_DIR}
    folder = folders.get(target)
    if not folder:
        raise ValueError("열 수 없는 폴더입니다.")
    folder.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(folder)])
    elif system == "Windows":
        subprocess.Popen(["explorer", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return folder


class CodexAppServer:
    """Small JSON-RPC client for the locally installed Codex app-server."""

    def __init__(self, codex_path):
        self.process = subprocess.Popen(
            codex_command(codex_path, "app-server", "--listen", "stdio://"),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.responses = {}
        self.condition = threading.Condition()
        self.notifications = queue.Queue()
        self.stderr_lines = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request(1, "initialize", {
            "clientInfo": {"name": "frame-lab", "version": "0.2.0"},
            "capabilities": {"experimentalApi": True},
        })
        self.send({"method": "initialized", "params": {}})

    def _read_stdout(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in message and "method" in message:
                self.send({"id": message["id"], "result": {"decision": "decline"}})
            elif "id" in message:
                with self.condition:
                    self.responses[str(message["id"])] = message
                    self.condition.notify_all()
            else:
                self.notifications.put(message)

    def _read_stderr(self):
        for line in self.process.stderr:
            text = line.strip()
            if text:
                self.stderr_lines.append(text)
                self.stderr_lines = self.stderr_lines[-20:]

    def send(self, message):
        if self.process.poll() is not None:
            raise RuntimeError("Codex 로컬 서버가 예기치 않게 종료됐습니다.")
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def request(self, request_id, method, params, timeout=30):
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.time() + timeout
        with self.condition:
            while str(request_id) not in self.responses:
                remaining = deadline - time.time()
                if remaining <= 0:
                    details = self.stderr_lines[-1] if self.stderr_lines else method
                    raise TimeoutError(f"Codex 응답 시간 초과: {details}")
                self.condition.wait(remaining)
            response = self.responses.pop(str(request_id))
        if "error" in response:
            error = response["error"]
            raise RuntimeError(error.get("message", str(error)))
        return response.get("result", {})

    def transform(self, image_path, prompt, request_id):
        thread = self.request(request_id, "thread/start", {
            "cwd": str(DATA_ROOT),
            "ephemeral": True,
            "approvalPolicy": "never",
            "sandbox": "workspace-write",
            "runtimeWorkspaceRoots": [str(DATA_ROOT), str(ROOT)],
        })
        thread_id = thread["thread"]["id"]
        instruction = (
            "Use $imagegen in built-in edit mode on the attached local image. "
            "Generate exactly one final edited image. Preserve the source composition and identity. "
            "Do not use shell commands, do not copy files, and do not merely describe the result; "
            "the host application will save the generated asset.\n\nSTYLE PROMPT:\n" + prompt
        )
        self.request(request_id + 1, "turn/start", {
            "threadId": thread_id,
            "cwd": str(DATA_ROOT),
            "input": [
                {"type": "text", "text": instruction},
                {"type": "localImage", "path": str(image_path)},
                {"type": "skill", "name": "imagegen", "path": str(IMAGEGEN_SKILL)},
            ],
        })

        generated_path = None
        deadline = time.time() + 600
        while time.time() < deadline:
            try:
                message = self.notifications.get(timeout=min(5, deadline - time.time()))
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError("Codex 로컬 서버가 이미지 생성 중 종료됐습니다.")
                continue
            params = message.get("params", {})
            if params.get("threadId") != thread_id:
                continue
            if message.get("method") == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "imageGeneration" and item.get("status") == "completed":
                    generated_path = item.get("savedPath")
                if item.get("type") == "imageGeneration" and item.get("failure"):
                    raise RuntimeError(f"이미지 생성 실패: {item['failure']}")
            if message.get("method") == "turn/completed":
                turn = params.get("turn", {})
                if turn.get("status") != "completed":
                    error = turn.get("error") or "Codex 작업이 완료되지 않았습니다."
                    raise RuntimeError(str(error))
                if not generated_path or not Path(generated_path).is_file():
                    raise RuntimeError("Codex가 결과 이미지 경로를 반환하지 않았습니다.")
                return Path(generated_path)
        raise TimeoutError("이미지 생성 제한 시간(10분)을 초과했습니다.")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


def strength_text(value):
    return {
        "1": "Apply the style gently while preserving most photographic detail.",
        "2": "Apply the style clearly and evenly while preserving identity and composition.",
        "3": "Apply the style strongly and unmistakably while preserving identity and composition.",
    }.get(value, "Apply the style clearly while preserving identity and composition.")


def run_job(job_id, style, strength, uploads):
    codex_path = find_codex()
    if not codex_path:
        set_job(job_id, status="failed", error="설치된 Codex 실행 파일을 찾지 못했습니다.")
        return
    if not IMAGEGEN_SKILL.is_file():
        set_job(job_id, status="failed", error="Codex imagegen 스킬을 찾지 못했습니다.")
        return

    with GENERATION_LOCK:
        set_job(job_id, status="running", message="설치된 Codex에 연결 중")
        client = None
        try:
            client = CodexAppServer(codex_path)
            prompt = strength_text(strength) + "\n\n" + (
                PRESETS_DIR / STYLE_FILES[style]
            ).read_text(encoding="utf-8").strip()
            results = []
            total = len(uploads)
            output_dir = OUTPUTS_DIR / job_id
            output_dir.mkdir(parents=True, exist_ok=True)
            for index, upload in enumerate(uploads, start=1):
                set_job(
                    job_id,
                    completed=index - 1,
                    message=f"{index}/{total} · {upload['sourceName']} 변환 중",
                )
                source_suffix = Path(upload["sourceName"]).suffix.lower() or upload["path"].suffix or ".jpg"
                source_name = f"{index:02d}-source{source_suffix}"
                shutil.copyfile(upload["path"], output_dir / source_name)
                generated = client.transform(upload["path"], prompt, 1000 + index * 10)
                output_name = f"{index:02d}-{style}.png"
                output_path = output_dir / output_name
                shutil.copyfile(generated, output_path)
                results.append({
                    "sourceName": upload["sourceName"],
                    "sourceUrl": f"/outputs/{job_id}/{source_name}",
                    "style": style,
                    "url": f"/outputs/{job_id}/{output_name}",
                    "downloadName": f"{Path(upload['sourceName']).stem}-{style}.png",
                })
                set_job(job_id, completed=index, results=list(results))
            with JOBS_LOCK:
                created_at = JOBS[job_id].get("createdAt")
            record = {
                "jobId": job_id,
                "createdAt": created_at,
                "style": style,
                "styleName": STYLE_META[style]["name"],
                "strength": strength,
                "total": total,
                "results": results,
            }
            (output_dir / "metadata.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            set_job(
                job_id,
                status="completed",
                completed=total,
                message=f"{total}장 변환 완료",
                results=results,
            )
        except Exception as error:
            set_job(job_id, status="failed", error=str(error), message="변환 실패")
        finally:
            if client:
                client.close()
            shutil.rmtree(UPLOADS_DIR / job_id, ignore_errors=True)


class AppHandler(SimpleHTTPRequestHandler):
    server_version = "FrameLab/0.3"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, max_bytes=256 * 1024):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0 or content_length > max_bytes:
            raise ValueError("요청 데이터 크기가 올바르지 않습니다.")
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def serve_output(self):
        raw_path = unquote(urlsplit(self.path).path)
        relative = raw_path[len("/outputs/"):]
        candidate = (OUTPUTS_DIR / relative).resolve()
        output_root = OUTPUTS_DIR.resolve()
        if candidate != output_root and output_root not in candidate.parents:
            self.send_error(403, "Forbidden")
            return
        if not candidate.is_file():
            self.send_error(404, "File not found")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.end_headers()
        with candidate.open("rb") as source:
            shutil.copyfileobj(source, self.wfile)

    def do_GET(self):
        if self.path.startswith("/outputs/"):
            self.serve_output()
            return
        if self.path == "/api/status":
            codex = find_codex()
            self.send_json(200, {
                "ready": bool(codex and IMAGEGEN_SKILL.is_file()),
                "backend": "installed-codex",
                "codex": str(codex) if codex else None,
                "imagegen": IMAGEGEN_SKILL.is_file(),
                "maxFiles": MAX_FILES,
                "dataDir": str(DATA_ROOT),
            })
            return
        if self.path == "/api/history":
            self.send_json(200, {"history": history_payload()})
            return
        if self.path == "/api/presets":
            self.send_json(200, {"presets": preset_payload()})
            return
        if self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                payload = dict(job) if job else None
            if not payload:
                self.send_json(404, {"error": "작업을 찾을 수 없습니다."})
            else:
                payload.pop("uploadDir", None)
                self.send_json(200, payload)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/open-folder":
            try:
                payload = self.read_json()
                folder = open_local_folder(payload.get("target"))
                self.send_json(200, {"opened": True, "path": str(folder)})
            except (ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
            return
        if self.path != "/api/transform":
            self.send_json(404, {"error": "지원하지 않는 경로입니다."})
            return
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self.send_json(413, {"error": "업로드 용량이 너무 큽니다."})
            return
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(content_length),
            },
        )
        style = form.getfirst("style", "")
        strength = form.getfirst("strength", "2")
        if style not in STYLE_FILES:
            self.send_json(400, {"error": "알 수 없는 편집 스타일입니다."})
            return
        image_fields = form["image"] if "image" in form else []
        if not isinstance(image_fields, list):
            image_fields = [image_fields]
        if not image_fields or len(image_fields) > MAX_FILES:
            self.send_json(400, {"error": f"사진은 1~{MAX_FILES}장까지 선택할 수 있습니다."})
            return

        job_id = uuid.uuid4().hex[:12]
        upload_dir = UPLOADS_DIR / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploads = []
        for index, item in enumerate(image_fields, start=1):
            source_name = Path(item.filename or f"image-{index}.png").name
            content_type = item.type or mimetypes.guess_type(source_name)[0] or ""
            if content_type not in ALLOWED_TYPES:
                shutil.rmtree(upload_dir, ignore_errors=True)
                self.send_json(400, {"error": f"지원하지 않는 형식입니다: {content_type or source_name}"})
                return
            data = item.file.read()
            if not data:
                shutil.rmtree(upload_dir, ignore_errors=True)
                self.send_json(400, {"error": "비어 있는 이미지가 포함되어 있습니다."})
                return
            suffix = Path(source_name).suffix.lower() or mimetypes.guess_extension(content_type) or ".png"
            upload_path = upload_dir / f"{index:02d}{suffix}"
            upload_path.write_bytes(data)
            uploads.append({"sourceName": source_name, "path": upload_path})

        job = {
            "jobId": job_id,
            "status": "queued",
            "message": "작업 대기 중",
            "style": style,
            "total": len(uploads),
            "completed": 0,
            "results": [],
            "error": None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "uploadDir": str(upload_dir),
        }
        with JOBS_LOCK:
            JOBS[job_id] = job
        threading.Thread(
            target=run_job,
            args=(job_id, style, strength, uploads),
            daemon=True,
        ).start()
        self.send_json(202, {"jobId": job_id, "status": "queued"})

    def do_PUT(self):
        if not self.path.startswith("/api/presets/"):
            self.send_json(404, {"error": "지원하지 않는 경로입니다."})
            return
        style = self.path.rsplit("/", 1)[-1]
        if style not in STYLE_FILES:
            self.send_json(404, {"error": "프리셋을 찾을 수 없습니다."})
            return
        try:
            payload = self.read_json()
            prompt = payload.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("프롬프트 내용을 입력해주세요.")
            if len(prompt) > 50000:
                raise ValueError("프롬프트가 너무 깁니다.")
            path = PRESETS_DIR / STYLE_FILES[style]
            path.write_text(prompt.strip() + "\n", encoding="utf-8")
            self.send_json(200, {
                "saved": True,
                "preset": next(item for item in preset_payload() if item["id"] == style),
            })
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})

    def log_message(self, format_string, *args):
        sys.stdout.write(f"[{self.log_date_time_string()}] {format_string % args}\n")


def main():
    host = os.environ.get("PHOTO_EDIT_HOST", "127.0.0.1")
    port = int(os.environ.get("PHOTO_EDIT_PORT", "4173"))
    codex = find_codex()
    print(f"FrameLab: http://{host}:{port}")
    print(f"Backend: installed Codex ({codex or 'not found'})")
    server = ThreadingHTTPServer((host, port), AppHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
