"""
FreeCut Video Editor - Python Backend Server
Handles FFmpeg operations, file dialogs, shell operations, and file system access.
Serves the React frontend as a static web application.
"""

import asyncio
import base64
import json
import os
import platform
import subprocess
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import psutil
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


# ============= Configuration =============

@dataclass
class HWAccelInfo:
    encoder: str = "libx264"
    hwaccel: str = ""
    available: bool = False


@dataclass
class ProbeResult:
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    audio_codec: Optional[str]
    bitrate: int


@dataclass
class FFmpegCheckResult:
    available: bool
    version: str
    path: str
    hw_accel: HWAccelInfo


# Get the base directory (project root)
BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIST = BASE_DIR / "dist"


# ============= FFmpeg Path Resolution =============

def get_ffmpeg_path() -> str:
    """Get the FFmpeg binary path.
    
    Priority:
    1. imageio-ffmpeg bundled binary (Python package)
    2. Local bin directory (for development)
    3. System PATH fallback
    """
    # 1. Use imageio-ffmpeg (bundled, no system install needed)
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            return path
    except ImportError:
        pass
    
    # 2. Check local bin directory
    system = platform.system()
    binary_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
    local_bin = BASE_DIR / "bin" / f"{platform.system().lower()}-{platform.machine()}" / binary_name
    
    if local_bin.exists():
        return str(local_bin)
    
    # 3. Fall back to system PATH
    return binary_name


def get_ffprobe_path() -> str:
    """Get the FFprobe binary path.
    
    Uses imageio-ffmpeg's bundled binary directory to find ffprobe,
    or falls back to local bin / system PATH.
    """
    # 1. Try to find ffprobe next to imageio-ffmpeg's bundled ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path:
            ffmpeg_dir = os.path.dirname(ffmpeg_path)
            system = platform.system()
            probe_name = "ffprobe.exe" if system == "Windows" else "ffprobe"
            probe_path = os.path.join(ffmpeg_dir, probe_name)
            if os.path.exists(probe_path):
                return probe_path
    except ImportError:
        pass
    
    # 2. Check local bin directory
    system = platform.system()
    binary_name = "ffprobe.exe" if system == "Windows" else "ffprobe"
    local_bin = BASE_DIR / "bin" / f"{platform.system().lower()}-{platform.machine()}" / binary_name
    
    if local_bin.exists():
        return str(local_bin)
    
    return binary_name


# ============= Hardware Acceleration Detection =============

async def detect_hardware_acceleration() -> HWAccelInfo:
    """Detect available hardware acceleration options."""
    system = platform.system()
    ffmpeg_path = get_ffmpeg_path()
    
    # Platform-specific encoder candidates
    candidates = []
    if system == "Windows":
        candidates = [
            {"encoder": "h264_nvenc", "hwaccel": "cuda"},
            {"encoder": "h264_amf", "hwaccel": "d3d11va"},
            {"encoder": "h264_qsv", "hwaccel": "qsv"},
        ]
    elif system == "Darwin":
        candidates = [
            {"encoder": "h264_videotoolbox", "hwaccel": "videotoolbox"},
        ]
    else:  # Linux
        candidates = [
            {"encoder": "h264_nvenc", "hwaccel": "cuda"},
            {"encoder": "h264_vaapi", "hwaccel": "vaapi"},
        ]
    
    for candidate in candidates:
        if await test_encoder(ffmpeg_path, candidate["encoder"]):
            return HWAccelInfo(
                encoder=candidate["encoder"],
                hwaccel=candidate["hwaccel"],
                available=True
            )
    
    return HWAccelInfo(encoder="libx264", hwaccel="", available=False)


async def test_encoder(ffmpeg_path: str, encoder: str) -> bool:
    """Test if an encoder is available."""
    try:
        result = await asyncio.create_subprocess_exec(
            ffmpeg_path, "-hide_banner", "-encoders",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(result.communicate(), timeout=5)
        return encoder.encode() in stdout
    except Exception:
        # Fallback to synchronous subprocess (Windows uvicorn compatibility)
        try:
            result = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-encoders"],
                capture_output=True, timeout=5
            )
            return encoder.encode() in result.stdout
        except Exception:
            return False


# ============= FFmpeg Operations =============

async def check_ffmpeg() -> FFmpegCheckResult:
    """Check FFmpeg availability and capabilities."""
    ffmpeg_path = get_ffmpeg_path()
    
    try:
        result = await asyncio.create_subprocess_exec(
            ffmpeg_path, "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(result.communicate(), timeout=5)
        
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg returned code {result.returncode}")
        
        output = stdout.decode()
    except Exception as e:
        # Fallback to synchronous subprocess (Windows uvicorn event loop issue)
        print(f"[FFmpegCheck] Async subprocess failed ({e}), falling back to sync subprocess")
        try:
            sync_result = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True, timeout=5
            )
            if sync_result.returncode != 0:
                return FFmpegCheckResult(
                    available=False, version="", path=ffmpeg_path,
                    hw_accel=HWAccelInfo(encoder="libx264", hwaccel="", available=False)
                )
            output = sync_result.stdout.decode()
        except Exception as e2:
            print(f"[FFmpegCheck] Sync subprocess also failed: {e2}")
            return FFmpegCheckResult(
                available=False, version="", path=ffmpeg_path,
                hw_accel=HWAccelInfo(encoder="libx264", hwaccel="", available=False)
            )
    
    version_match = output.split("ffmpeg version ")[1].split()[0] if "ffmpeg version" in output else "unknown"
    
    hw_accel = await detect_hardware_acceleration()
    
    return FFmpegCheckResult(
        available=True,
        version=version_match,
        path=ffmpeg_path,
        hw_accel=hw_accel
    )


async def probe_file(file_path: str) -> ProbeResult:
    """Probe a media file for its properties."""
    ffprobe_path = get_ffprobe_path()
    
    def run_probe():
        return subprocess.run(
            [ffprobe_path, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", file_path],
            capture_output=True, timeout=15
        )
    
    result = await asyncio.to_thread(run_probe)
    
    if result.returncode != 0:
        raise Exception(f"FFprobe failed: {result.stderr.decode()}")
    
    data = json.loads(result.stdout.decode())
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    
    if not video_stream:
        raise Exception("No video stream found")
    
    # Parse FPS
    fps = 30
    r_frame_rate = video_stream.get("r_frame_rate", "30/1")
    if r_frame_rate:
        parts = r_frame_rate.split("/")
        if len(parts) == 2 and int(parts[1]) > 0:
            fps = int(parts[0]) / int(parts[1])
    
    return ProbeResult(
        duration=float(data.get("format", {}).get("duration", video_stream.get("duration", "0"))),
        width=video_stream.get("width", 0),
        height=video_stream.get("height", 0),
        fps=fps,
        codec=video_stream.get("codec_name", ""),
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        bitrate=int(data.get("format", {}).get("bit_rate", "0"))
    )


async def generate_thumbnail(file_path: str, time_seconds: float) -> str:
    """Generate a thumbnail image from a video."""
    ffmpeg_path = get_ffmpeg_path()
    
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        output_path = tmp.name
    
    try:
        def run_thumbnail():
            return subprocess.run(
                [ffmpeg_path, "-y", "-hide_banner",
                 "-ss", str(time_seconds),
                 "-i", file_path,
                 "-vframes", "1",
                 "-vf", "scale=320:-1",
                 "-q:v", "5",
                 output_path],
                capture_output=True, timeout=10
            )
        
        result = await asyncio.to_thread(run_thumbnail)
        
        if result.returncode != 0:
            raise Exception(f"Thumbnail generation failed: {result.stderr.decode()}")
        
        # Read and encode as base64
        with open(output_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()
        
        return f"data:image/jpeg;base64,{image_data}"
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


# ============= Export Progress Tracker =============

class ExportProgressTracker:
    """Track export progress by parsing FFmpeg output."""
    
    def __init__(self, total_duration: float):
        self.total_duration = total_duration
        self.progress = 0.0
        self._callbacks: list[callable] = []
    
    def add_callback(self, callback: callable):
        self._callbacks.append(callback)
    
    def update(self, time_ms: int):
        if self.total_duration > 0:
            self.progress = min(time_ms / (self.total_duration * 1_000_000), 1.0)
            for cb in self._callbacks:
                cb(self.progress)


# Global state for active export
active_export_process: Optional[asyncio.subprocess.Process] = None
active_progress_tracker: Optional[ExportProgressTracker] = None


CRF_MAP = {
    "low": {"libx264": "28", "libx265": "32", "libvpx": "35", "hw": "30"},
    "medium": {"libx264": "23", "libx265": "28", "libvpx": "30", "hw": "25"},
    "high": {"libx264": "18", "libx265": "24", "libvpx": "23", "hw": "20"},
    "very_high": {"libx264": "15", "libx265": "20", "libvpx": "18", "hw": "15"},
}


# ============= FastAPI Application =============

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    # Startup
    print("FreeCut Backend starting...")
    yield
    # Shutdown
    global active_export_process
    if active_export_process:
        active_export_process.terminate()


app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use a router for API endpoints so they're registered before the catch-all
from fastapi import APIRouter
api_router = APIRouter(prefix="/api")


# ============= API Endpoints =============

@api_router.get("/")
async def api_root():
    """API health check."""
    return {"status": "ok", "service": "freecut-backend"}



@api_router.get("/ffmpeg/check")
async def ffmpeg_check():
    """Check FFmpeg availability and hardware acceleration."""
    result = await check_ffmpeg()
    return {
        "available": result.available,
        "version": result.version,
        "path": result.path,
        "hwAccel": {
            "encoder": result.hw_accel.encoder,
            "hwaccel": result.hw_accel.hwaccel,
            "available": result.hw_accel.available
        }
    }


@api_router.post("/ffmpeg/probe")
async def ffmpeg_probe(request: Request):
    """Probe a media file for its properties."""
    body = await request.json()
    file_path = body.get("filePath")
    
    if not file_path:
        return JSONResponse({"error": "filePath required"}, status_code=400)
    
    result = await probe_file(file_path)
    return {
        "duration": result.duration,
        "width": result.width,
        "height": result.height,
        "fps": result.fps,
        "codec": result.codec,
        "audioCodec": result.audio_codec,
        "bitrate": result.bitrate
    }


@api_router.post("/ffmpeg/thumbnail")
async def ffmpeg_thumbnail(request: Request):
    """Generate a thumbnail from a video."""
    body = await request.json()
    file_path = body.get("filePath")
    time_seconds = body.get("timeSeconds", 0)
    
    if not file_path:
        return JSONResponse({"error": "filePath required"}, status_code=400)
    
    result = await generate_thumbnail(file_path, time_seconds)
    return {"thumbnail": result}


@api_router.post("/ffmpeg/export")
async def ffmpeg_export(request: Request):
    """Export a video with the given options."""
    global active_export_process, active_progress_tracker
    
    body = await request.json()
    
    input_path = body.get("inputPath")
    output_path = body.get("outputPath")
    start_time = body.get("startTimeSeconds")
    duration = body.get("durationSeconds")
    width = body.get("width")
    height = body.get("height")
    fps = body.get("fps")
    video_format = body.get("format", "mp4")
    quality = body.get("quality", "medium")
    use_hw = body.get("useHardwareAccel", True)
    
    if not input_path or not output_path:
        return JSONResponse({"error": "inputPath and outputPath required"}, status_code=400)
    
    ffmpeg_path = get_ffmpeg_path()
    
    # Get hardware acceleration info
    hw_info = await detect_hardware_acceleration()
    use_hw_accel = use_hw and hw_info.available
    
    encoder = use_hw_accel and hw_info.encoder or "libx264"
    crf = CRF_MAP.get(quality, CRF_MAP["medium"])
    
    # Build FFmpeg arguments
    args = ["-y", "-hide_banner"]
    
    # Hardware decode if available
    if use_hw_accel and hw_info.hwaccel:
        args.extend(["-hwaccel", hw_info.hwaccel])
    
    # Pre-input trimming
    if start_time is not None:
        args.extend(["-ss", str(start_time)])
    if duration is not None:
        args.extend(["-t", str(duration)])
    
    args.extend(["-i", input_path])
    
    # Video filters
    filters = []
    if width and height:
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    if fps:
        filters.append(f"fps={fps}")
    
    if filters:
        args.extend(["-vf", ",".join(filters)])
    
    # Encoder settings
    args.extend(["-c:v", encoder])
    
    if encoder == "libx264":
        args.extend(["-crf", crf["libx264"], "-preset", "fast", "-pix_fmt", "yuv420p"])
    elif "nvenc" in encoder:
        args.extend(["-cq", crf["hw"], "-preset", "p4", "-pix_fmt", "yuv420p"])
    elif "videotoolbox" in encoder:
        args.extend(["-q:v", crf["hw"], "-pix_fmt", "yuv420p"])
    elif "amf" in encoder:
        args.extend(["-quality", "balanced", "-pix_fmt", "yuv420p"])
    elif "qsv" in encoder:
        args.extend(["-global_quality", crf["hw"], "-preset", "faster", "-pix_fmt", "yuv420p"])
    
    # Audio
    if video_format == "webm":
        args.extend(["-c:a", "libopus", "-b:a", "128k"])
    else:
        args.extend(["-c:a", "aac", "-b:a", "192k"])
    
    # Format-specific
    if video_format == "mp4":
        args.extend(["-movflags", "+faststart"])
    
    args.extend(["-progress", "pipe:1", output_path])
    
    # Get duration for progress calculation
    total_duration = 0.0
    try:
        probe_result = await probe_file(input_path)
        total_duration = probe_result.duration
    except Exception:
        pass
    
    # Create progress tracker
    progress_tracker = ExportProgressTracker(total_duration)
    active_progress_tracker = progress_tracker
    
    try:
        # Run FFmpeg via subprocess.Popen in a thread
        # (asyncio subprocess fails under uvicorn on Windows)
        def run_export_sync():
            proc = subprocess.Popen(
                [ffmpeg_path] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL
            )
            stdout, stderr = proc.communicate(timeout=600)
            return proc.returncode, stdout, stderr
        
        returncode, stdout, stderr = await asyncio.to_thread(run_export_sync)
        
        if returncode != 0:
            error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
            raise Exception(f"FFmpeg exited with code {returncode}: {error_msg}")
        
        progress_tracker.progress = 1.0
        return {"success": True, "progress": 1.0}
        
    except asyncio.CancelledError:
        if active_export_process:
            active_export_process.terminate()
        raise
    finally:
        active_export_process = None
        active_progress_tracker = None


async def _read_ffmpeg_progress(stdout: asyncio.StreamReader, tracker: ExportProgressTracker):
    """Read FFmpeg progress output and update progress."""
    try:
        while True:
            line = await stdout.readline()
            if not line:
                break
            
            text = line.decode()
            if "out_time_ms=" in text:
                try:
                    time_ms = int(text.split("out_time_ms=")[1].strip())
                    tracker.update(time_ms)
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass


@api_router.post("/ffmpeg/cancel-export")
async def ffmpeg_cancel_export():
    """Cancel an active export."""
    global active_export_process
    
    if active_export_process:
        active_export_process.terminate()
        active_export_process = None
        return {"success": True}
    
    return {"success": False}


@api_router.get("/ffmpeg/progress")
async def ffmpeg_progress():
    """Get current export progress."""
    global active_progress_tracker
    
    if active_progress_tracker:
        return {"progress": active_progress_tracker.progress}
    
    return {"progress": 0.0}


# ============= Compose Export (Frame-by-Frame GPU Pipeline) =============

import uuid
import time
import threading
from collections import OrderedDict


# ============= Media Upload for Backend Processing =============

# Temp storage for uploaded media files
uploaded_media: dict[str, str] = {}  # mediaId -> temp file path
uploaded_media_dir = tempfile.mkdtemp(prefix="freecut_media_")


@api_router.post("/media/upload")
async def upload_media(request: Request):
    """Upload a media file for backend FFmpeg processing.
    
    Receives binary file data with mediaId in header.
    Stores in temp directory and returns the file path for FFmpeg.
    """
    media_id = request.headers.get("X-Media-Id", "")
    filename = request.headers.get("X-Filename", "media.mp4")
    
    if not media_id:
        return JSONResponse({"error": "X-Media-Id header required"}, status_code=400)
    
    # Check if already uploaded
    if media_id in uploaded_media and os.path.exists(uploaded_media[media_id]):
        return {"mediaId": media_id, "path": uploaded_media[media_id], "cached": True}
    
    # Save file
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    file_path = os.path.join(uploaded_media_dir, f"{media_id}_{safe_filename}")
    
    body = await request.body()
    with open(file_path, "wb") as f:
        f.write(body)
    
    uploaded_media[media_id] = file_path
    file_size = os.path.getsize(file_path)
    print(f"[MediaUpload] Saved {media_id}: {file_size} bytes -> {file_path}")
    
    return {"mediaId": media_id, "path": file_path, "size": file_size, "cached": False}


@api_router.post("/ffmpeg/export-composition")
async def ffmpeg_export_composition(request: Request):
    """Export a full composition using FFmpeg with GPU acceleration.
    
    This is the FAST PATH — the frontend sends the composition description
    with file path mappings. FFmpeg handles decode→filter→encode entirely
    on the GPU in a single pass. No frame-by-frame canvas rendering needed.
    
    Expected body:
    {
        "composition": { tracks, fps, durationInFrames, width, height, ... },
        "mediaMap": { "mediaId1": "/path/to/file1.mp4", ... },
        "settings": { codec, quality, container, width, height, videoBitrate, audioBitrate },
        "useHardwareAccel": true
    }
    """
    _cleanup_old_jobs()
    
    body = await request.json()
    composition = body.get("composition", {})
    media_map = body.get("mediaMap", {})
    settings = body.get("settings", {})
    use_hw = body.get("useHardwareAccel", True)
    
    tracks = composition.get("tracks", [])
    comp_fps = composition.get("fps", 30)
    comp_duration_frames = composition.get("durationInFrames", 0)
    comp_width = settings.get("width", composition.get("width", 1920))
    comp_height = settings.get("height", composition.get("height", 1080))
    codec = settings.get("codec", "avc")
    quality = settings.get("quality", "high")
    container = settings.get("container", "mp4")
    video_bitrate = settings.get("videoBitrate")
    audio_bitrate = settings.get("audioBitrate")
    
    if not tracks:
        return JSONResponse({"error": "No tracks in composition"}, status_code=400)
    
    # Collect all video/audio items with their source paths
    media_items = []
    for track in tracks:
        if track.get("visible") is False:
            continue
        for item in track.get("items", []):
            item_type = item.get("type", "")
            if item_type not in ("video", "audio", "image"):
                continue
            
            media_id = item.get("mediaId", "")
            src = item.get("src", "")
            
            # Resolve file path: check mediaMap first, then src, then uploaded_media
            file_path = media_map.get(media_id, "")
            if not file_path and os.path.exists(src):
                file_path = src
            if not file_path and media_id in uploaded_media:
                file_path = uploaded_media[media_id]
            
            if not file_path or not os.path.exists(file_path):
                print(f"[CompositionExport] Skipping item {item.get('id', '?')}: no file path for mediaId={media_id}")
                continue
            
            media_items.append({
                "file_path": file_path,
                "type": item_type,
                "from": item.get("from", 0),
                "duration_frames": item.get("durationInFrames", 0),
                "source_start": item.get("sourceStart", item.get("trimStart", item.get("offset", 0))),
                "speed": item.get("speed", 1),
                "volume": item.get("volume", 0),
                "muted": track.get("muted", False),
                "effects": item.get("effects", []),
                "fadeIn": item.get("fadeIn", 0),
                "fadeOut": item.get("fadeOut", 0),
            })
    
    if not media_items:
        return JSONResponse({"error": "No media files found in composition"}, status_code=400)
    
    # Check FFmpeg
    ffmpeg_result = await check_ffmpeg()
    if not ffmpeg_result.available:
        return JSONResponse({"error": "FFmpeg not available"}, status_code=500)
    
    ffmpeg_path = get_ffmpeg_path()
    hw_info = ffmpeg_result.hw_accel
    
    # Create output
    ext = {"mp4": ".mp4", "webm": ".webm", "mov": ".mov"}.get(container, ".mp4")
    job_id = str(uuid.uuid4())
    output_dir = tempfile.mkdtemp(prefix="freecut_export_")
    output_path = os.path.join(output_dir, f"export_{job_id}{ext}")
    
    comp_duration_seconds = comp_duration_frames / max(comp_fps, 1)
    
    # Build FFmpeg command
    args = [ffmpeg_path, "-y", "-hide_banner"]
    
    # Hardware decode
    if use_hw and hw_info.available and hw_info.hwaccel:
        args.extend(["-hwaccel", hw_info.hwaccel])
    
    # === Simple case: single video item → direct re-encode ===
    if len(media_items) == 1 and media_items[0]["type"] == "video":
        item = media_items[0]
        source_start_s = item["source_start"] / max(comp_fps, 1) if item["source_start"] else 0
        duration_s = item["duration_frames"] / max(comp_fps, 1)
        speed = item.get("speed", 1) or 1
        
        if source_start_s > 0.01:
            args.extend(["-ss", str(source_start_s)])
        if duration_s > 0:
            args.extend(["-t", str(duration_s / speed)])
        
        args.extend(["-i", item["file_path"]])
        
        # Video filters
        vf = []
        if abs(speed - 1) > 0.01:
            vf.append(f"setpts={1/speed}*PTS")
        vf.append(f"scale={comp_width}:{comp_height}:force_original_aspect_ratio=decrease")
        vf.append(f"pad={comp_width}:{comp_height}:(ow-iw)/2:(oh-ih)/2")
        vf.append(f"fps={comp_fps}")
        
        # Fade effects
        if item.get("fadeIn", 0) > 0.001:
            vf.append(f"fade=t=in:st=0:d={item['fadeIn']}")
        if item.get("fadeOut", 0) > 0.001:
            fade_start = max(0, duration_s - item["fadeOut"])
            vf.append(f"fade=t=out:st={fade_start}:d={item['fadeOut']}")
        
        args.extend(["-vf", ",".join(vf)])
        
        # Audio
        af = []
        if abs(speed - 1) > 0.01:
            af.append(f"atempo={speed}")
        volume = item.get("volume", 0)
        if abs(volume) > 0.01:
            # volume is in dB
            af.append(f"volume={volume}dB")
        
        if item.get("muted"):
            args.extend(["-an"])
        elif af:
            args.extend(["-af", ",".join(af)])
            if container == "webm":
                args.extend(["-c:a", "libopus", "-b:a", str(audio_bitrate or 128000)])
            else:
                args.extend(["-c:a", "aac", "-b:a", str(audio_bitrate or 192000)])
        else:
            if container == "webm":
                args.extend(["-c:a", "libopus", "-b:a", str(audio_bitrate or 128000)])
            else:
                args.extend(["-c:a", "aac", "-b:a", str(audio_bitrate or 192000)])
    
    # === Multi-item: use concat or filter_complex ===
    else:
        # Sort items by timeline position
        sorted_items = sorted(media_items, key=lambda x: x.get("from", 0))
        
        # Add all inputs
        for item in sorted_items:
            source_start_s = item["source_start"] / max(comp_fps, 1) if item["source_start"] else 0
            duration_s = item["duration_frames"] / max(comp_fps, 1)
            
            if source_start_s > 0.01:
                args.extend(["-ss", str(source_start_s)])
            if duration_s > 0:
                args.extend(["-t", str(duration_s)])
            args.extend(["-i", item["file_path"]])
        
        # Build filter_complex
        # First, probe each input to check if it has an audio stream
        input_has_audio = []
        for item in sorted_items:
            has_audio = False
            if item["type"] != "image":
                try:
                    probe_result = subprocess.run(
                        [get_ffprobe_path(), "-v", "quiet", "-print_format", "json",
                         "-show_streams", "-select_streams", "a", item["file_path"]],
                        capture_output=True, timeout=5
                    )
                    if probe_result.returncode == 0:
                        probe_data = json.loads(probe_result.stdout.decode())
                        has_audio = len(probe_data.get("streams", [])) > 0
                except Exception:
                    pass
            input_has_audio.append(has_audio)
        
        # Check if any input lacks audio — if so, add a silent audio source as an extra input
        silent_clip_indices = [
            i for i in range(len(sorted_items))
            if not input_has_audio[i] or sorted_items[i].get("muted")
        ]
        silent_input_idx = None
        if silent_clip_indices:
            silent_input_idx = len(sorted_items)  # Index of the silent audio input
            args.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
        
        n = len(sorted_items)
        filter_parts = []
        concat_inputs = []
        
        # If multiple clips need silent audio, split the silent source into N copies
        if len(silent_clip_indices) > 1:
            split_labels = "".join(f"[sil{i}]" for i in range(len(silent_clip_indices)))
            filter_parts.append(f"[{silent_input_idx}:a]asplit={len(silent_clip_indices)}{split_labels}")
            # Map clip index to split label index
            silent_label_map = {clip_i: f"sil{j}" for j, clip_i in enumerate(silent_clip_indices)}
        elif len(silent_clip_indices) == 1:
            silent_label_map = {silent_clip_indices[0]: f"{silent_input_idx}:a"}
        else:
            silent_label_map = {}
        
        for i, item in enumerate(sorted_items):
            speed = item.get("speed", 1) or 1
            vf_chain = []
            
            vf_chain.append(f"scale={comp_width}:{comp_height}:force_original_aspect_ratio=decrease")
            vf_chain.append(f"pad={comp_width}:{comp_height}:(ow-iw)/2:(oh-ih)/2")
            vf_chain.append(f"fps={comp_fps}")
            
            if abs(speed - 1) > 0.01:
                vf_chain.append(f"setpts={1/speed}*PTS")
            
            filter_parts.append(f"[{i}:v]{','.join(vf_chain)}[v{i}]")
            
            # Determine duration for this item (needed for silent audio trim)
            duration_s = item["duration_frames"] / max(comp_fps, 1)
            
            if not item.get("muted") and input_has_audio[i]:
                # Input has real audio — use it
                af_chain = []
                if abs(speed - 1) > 0.01:
                    af_chain.append(f"atempo={speed}")
                if af_chain:
                    filter_parts.append(f"[{i}:a]{','.join(af_chain)}[a{i}]")
                else:
                    filter_parts.append(f"[{i}:a]acopy[a{i}]")
                concat_inputs.append(f"[v{i}][a{i}]")
            else:
                # No audio stream or muted — use silent audio, trimmed to clip duration
                sil_label = silent_label_map[i]
                filter_parts.append(f"[{sil_label}]atrim=duration={duration_s},asetpts=PTS-STARTPTS[a{i}]")
                concat_inputs.append(f"[v{i}][a{i}]")
        
        concat_str = "".join(concat_inputs)
        filter_parts.append(f"{concat_str}concat=n={n}:v=1:a=1[vout][aout]")
        
        full_filter = ";".join(filter_parts)
        print(f"[CompositionExport] input_has_audio: {input_has_audio}")
        print(f"[CompositionExport] silent_clip_indices: {silent_clip_indices}")
        print(f"[CompositionExport] filter_complex: {full_filter}")
        
        args.extend(["-filter_complex", full_filter])
        args.extend(["-map", "[vout]", "-map", "[aout]"])
        
        if container == "webm":
            args.extend(["-c:a", "libopus", "-b:a", str(audio_bitrate or 128000)])
        else:
            args.extend(["-c:a", "aac", "-b:a", str(audio_bitrate or 192000)])
    
    # Encoder settings
    encoder_args = _get_encoder_args(codec, quality, container, video_bitrate, hw_info if use_hw else HWAccelInfo())
    args.extend(encoder_args)
    
    args.extend(["-progress", "pipe:1", output_path])
    
    print(f"[CompositionExport] Starting FFmpeg: {' '.join(args[:20])}...")
    
    # Create tracking job
    job = ComposeExportJob(
        job_id=job_id,
        width=comp_width,
        height=comp_height,
        fps=comp_fps,
        total_frames=comp_duration_frames,
        codec=codec,
        quality=quality,
        container=container,
        video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate,
        output_path=output_path,
        audio_path=None,
        process=None,
        frames_received=0,
        status="encoding",
        error=None,
        created_at=time.time(),
        frame_buffer={},
        next_frame_to_write=0,
        lock=threading.Lock(),
        encoder_fps=0.0,
    )
    compose_jobs[job_id] = job
    
    # Start FFmpeg using subprocess.Popen in a thread (asyncio subprocess
    # fails silently under uvicorn on Windows)
    print(f"[CompositionExport] Full command: {' '.join(args)}")
    
    def run_ffmpeg_sync():
        """Run FFmpeg in a thread to avoid blocking the event loop."""
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            stdout_data, stderr_data = proc.communicate(timeout=600)
            return proc.returncode, stdout_data, stderr_data
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return -1, b"", b"FFmpeg timeout (600s)"
        except Exception as e:
            return -1, b"", str(e).encode()
    
    try:
        start_time = time.time()
        returncode, stdout_data, stderr_data = await asyncio.to_thread(run_ffmpeg_sync)
        elapsed = time.time() - start_time
        
        if returncode != 0:
            error_msg = stderr_data.decode()[-500:] if stderr_data else "Unknown error"
            job.status = "error"
            job.error = f"FFmpeg exited with code {returncode}: {error_msg}"
            print(f"[CompositionExport] FAILED: {job.error}")
            return JSONResponse({"error": f"FFmpeg failed: {error_msg}"}, status_code=500)
        
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        job.status = "done"
        job.frames_received = job.total_frames
        
        print(f"[CompositionExport] Complete in {elapsed:.1f}s: {file_size} bytes")
        
        return {
            "success": True,
            "jobId": job_id,
            "fileSize": file_size,
            "elapsed": round(elapsed, 2),
            "encoder": encoder_args[1] if len(encoder_args) > 1 else "unknown",
            "hwAccel": hw_info.available if use_hw else False,
        }
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        print(f"[CompositionExport] Exception: {e}")
        return JSONResponse({"error": f"FFmpeg failed: {e}"}, status_code=500)

@dataclass
class ComposeExportJob:
    """Represents an active compose export job."""
    job_id: str
    width: int
    height: int
    fps: int
    total_frames: int
    codec: str
    quality: str
    container: str
    video_bitrate: Optional[int]
    audio_bitrate: Optional[int]
    output_path: str
    audio_path: Optional[str]
    process: Optional[asyncio.subprocess.Process]
    frames_received: int
    status: str  # "ready", "encoding", "finalizing", "done", "error", "cancelled"
    error: Optional[str]
    created_at: float
    # Ordered frame buffer - holds frames until they can be written in sequence
    frame_buffer: dict  # frameIndex -> bytes
    next_frame_to_write: int
    lock: threading.Lock
    encoder_fps: float


# Active compose export jobs
compose_jobs: dict[str, ComposeExportJob] = {}
COMPOSE_JOB_MAX_AGE = 3600  # 1 hour


def _cleanup_old_jobs():
    """Remove stale jobs older than max age."""
    now = time.time()
    stale = [jid for jid, job in compose_jobs.items()
             if now - job.created_at > COMPOSE_JOB_MAX_AGE and job.status in ("done", "error", "cancelled")]
    for jid in stale:
        job = compose_jobs.pop(jid, None)
        if job:
            _cleanup_job_files(job)


def _cleanup_job_files(job: ComposeExportJob):
    """Remove temporary files for a job."""
    for path in [job.output_path, job.audio_path]:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except Exception:
                pass


def _get_encoder_args(codec: str, quality: str, container: str,
                      video_bitrate: Optional[int], hw_info: HWAccelInfo) -> list[str]:
    """Build encoder-specific FFmpeg arguments."""
    use_hw = hw_info.available
    encoder = hw_info.encoder if use_hw else "libx264"

    # Map client codec names to FFmpeg encoders
    if not use_hw:
        codec_map = {
            "avc": "libx264",
            "hevc": "libx265",
            "vp8": "libvpx",
            "vp9": "libvpx-vp9",
            "av1": "libaom-av1",
        }
        encoder = codec_map.get(codec, "libx264")

    crf = CRF_MAP.get(quality, CRF_MAP["medium"])
    args = ["-c:v", encoder]

    if video_bitrate:
        args.extend(["-b:v", str(video_bitrate)])

    if encoder == "libx264":
        args.extend(["-crf", crf["libx264"], "-preset", "fast", "-pix_fmt", "yuv420p"])
    elif encoder == "libx265":
        args.extend(["-crf", crf["libx265"], "-preset", "fast", "-pix_fmt", "yuv420p"])
    elif "nvenc" in encoder:
        if video_bitrate:
            args.extend(["-preset", "p4", "-tune", "hq", "-pix_fmt", "yuv420p"])
        else:
            args.extend(["-cq", crf["hw"], "-preset", "p4", "-tune", "hq", "-pix_fmt", "yuv420p"])
    elif "videotoolbox" in encoder:
        args.extend(["-q:v", crf["hw"], "-pix_fmt", "yuv420p"])
    elif "amf" in encoder:
        args.extend(["-quality", "balanced", "-pix_fmt", "yuv420p"])
    elif "qsv" in encoder:
        args.extend(["-global_quality", crf["hw"], "-preset", "faster", "-pix_fmt", "yuv420p"])
    elif "libvpx" in encoder:
        args.extend(["-crf", crf["libvpx"], "-b:v", "0", "-pix_fmt", "yuv420p"])
    else:
        args.extend(["-pix_fmt", "yuv420p"])

    # Format-specific flags
    if container == "mp4":
        args.extend(["-movflags", "+faststart"])

    return args


@api_router.post("/ffmpeg/export-direct")
async def ffmpeg_export_direct(request: Request):
    """Direct file-to-file export using FFmpeg with GPU acceleration.
    
    This is the FAST PATH — takes a source file path and re-encodes it
    directly with FFmpeg. No frame-by-frame transfer overhead.
    Used when the composition is a simple video re-encode (single clip, no overlays).
    """
    _cleanup_old_jobs()

    body = await request.json()
    input_path = body.get("inputPath")
    codec = body.get("codec", "avc")
    quality = body.get("quality", "high")
    container = body.get("container", "mp4")
    width = body.get("width")
    height = body.get("height")
    fps_val = body.get("fps")
    start_time = body.get("startTime")  # seconds
    duration_time = body.get("duration")  # seconds
    video_bitrate = body.get("videoBitrate")
    audio_bitrate = body.get("audioBitrate")
    use_hw = body.get("useHardwareAccel", True)

    if not input_path:
        return JSONResponse({"error": "inputPath required"}, status_code=400)

    if not os.path.exists(input_path):
        return JSONResponse({"error": f"Input file not found: {input_path}"}, status_code=400)

    # Check FFmpeg
    ffmpeg_result = await check_ffmpeg()
    if not ffmpeg_result.available:
        return JSONResponse({"error": "FFmpeg not available"}, status_code=500)

    ffmpeg_path = get_ffmpeg_path()
    hw_info = ffmpeg_result.hw_accel

    # Create temp output file
    ext = {"mp4": ".mp4", "webm": ".webm", "mov": ".mov", "mkv": ".mkv"}.get(container, ".mp4")
    job_id = str(uuid.uuid4())
    output_dir = tempfile.mkdtemp(prefix="freecut_export_")
    output_path = os.path.join(output_dir, f"export_{job_id}{ext}")

    # Build FFmpeg command
    args = [ffmpeg_path, "-y", "-hide_banner"]

    # Hardware decode if available
    if use_hw and hw_info.available and hw_info.hwaccel:
        args.extend(["-hwaccel", hw_info.hwaccel])

    # Input trimming
    if start_time is not None:
        args.extend(["-ss", str(start_time)])
    if duration_time is not None:
        args.extend(["-t", str(duration_time)])

    args.extend(["-i", input_path])

    # Video filters
    filters = []
    if width and height:
        filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
        filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    if fps_val:
        filters.append(f"fps={fps_val}")

    if filters:
        args.extend(["-vf", ",".join(filters)])

    # Encoder settings
    encoder_args = _get_encoder_args(codec, quality, container, video_bitrate, hw_info if use_hw else HWAccelInfo())
    args.extend(encoder_args)

    # Audio
    if container == "webm":
        args.extend(["-c:a", "libopus", "-b:a", str(audio_bitrate or 128000)])
    else:
        args.extend(["-c:a", "aac", "-b:a", str(audio_bitrate or 192000)])

    args.extend(["-progress", "pipe:1", output_path])

    print(f"[DirectExport] Starting FFmpeg: {' '.join(args)}")

    # Get total duration for progress
    total_duration = 0.0
    try:
        probe_result = await probe_file(input_path)
        total_duration = duration_time or probe_result.duration
    except Exception:
        total_duration = duration_time or 0.0

    # Create job for tracking
    job = ComposeExportJob(
        job_id=job_id,
        width=width or 1920,
        height=height or 1080,
        fps=fps_val or 30,
        total_frames=int(total_duration * (fps_val or 30)),
        codec=codec,
        quality=quality,
        container=container,
        video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate,
        output_path=output_path,
        audio_path=None,
        process=None,
        frames_received=0,
        status="encoding",
        error=None,
        created_at=time.time(),
        frame_buffer={},
        next_frame_to_write=0,
        lock=threading.Lock(),
        encoder_fps=0.0,
    )
    compose_jobs[job_id] = job

    # Start FFmpeg process
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        job.process = process
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        return JSONResponse({"error": f"Failed to start FFmpeg: {e}"}, status_code=500)

    # Progress tracking from stdout
    progress_tracker = ExportProgressTracker(total_duration)

    async def track_progress():
        if not process.stdout:
            return
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode()
                if "out_time_ms=" in text:
                    try:
                        time_ms = int(text.split("out_time_ms=")[1].strip())
                        progress_tracker.update(time_ms)
                        job.frames_received = int(progress_tracker.progress * job.total_frames)
                    except (ValueError, IndexError):
                        pass
                if "fps=" in text:
                    try:
                        fps_str = text.split("fps=")[1].strip().split()[0]
                        job.encoder_fps = float(fps_str)
                    except (ValueError, IndexError):
                        pass
        except Exception:
            pass

    # Read progress from stdout, then wait for process exit
    try:
        await asyncio.wait_for(track_progress(), timeout=300)
        await process.wait()

        # Read stderr for error info
        stderr_data = b""
        if process.stderr:
            stderr_data = await process.stderr.read()

        if process.returncode != 0:
            error_msg = stderr_data.decode()[-500:] if stderr_data else "Unknown error"
            job.status = "error"
            job.error = f"FFmpeg exited with code {process.returncode}: {error_msg}"
            return JSONResponse({"error": job.error}, status_code=500)

        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        job.status = "done"
        job.frames_received = job.total_frames

        elapsed = time.time() - job.created_at
        print(f"[DirectExport] Complete in {elapsed:.1f}s: {file_size} bytes -> {output_path}")

        return {
            "success": True,
            "jobId": job_id,
            "fileSize": file_size,
            "outputPath": output_path,
            "elapsed": round(elapsed, 2),
            "encoder": encoder_args[1] if len(encoder_args) > 1 else "unknown",
            "hwAccel": hw_info.available if use_hw else False,
        }
    except asyncio.TimeoutError:
        process.terminate()
        job.status = "error"
        job.error = "FFmpeg timeout (300s)"
        return JSONResponse({"error": job.error}, status_code=500)
@api_router.post("/ffmpeg/export-compose")
async def ffmpeg_export_compose(request: Request):
    """Create a new compose export job. Starts FFmpeg process waiting for raw frame input."""
    _cleanup_old_jobs()

    body = await request.json()
    width = body.get("width", 1920)
    height = body.get("height", 1080)
    fps_val = body.get("fps", 30)
    total_frames = body.get("totalFrames", 0)
    codec = body.get("codec", "avc")
    quality = body.get("quality", "high")
    container = body.get("container", "mp4")
    video_bitrate = body.get("videoBitrate")
    audio_bitrate = body.get("audioBitrate")

    if total_frames <= 0:
        return JSONResponse({"error": "totalFrames must be > 0"}, status_code=400)

    # Check FFmpeg
    ffmpeg_result = await check_ffmpeg()
    if not ffmpeg_result.available:
        return JSONResponse({"error": "FFmpeg not available"}, status_code=500)

    # Create temp output file
    ext = {"mp4": ".mp4", "webm": ".webm", "mov": ".mov", "mkv": ".mkv"}.get(container, ".mp4")
    job_id = str(uuid.uuid4())
    output_dir = tempfile.mkdtemp(prefix="freecut_export_")
    output_path = os.path.join(output_dir, f"export_{job_id}{ext}")
    video_only_path = os.path.join(output_dir, f"video_{job_id}{ext}")

    # Build FFmpeg command for rawvideo input via stdin
    ffmpeg_path = get_ffmpeg_path()
    hw_info = ffmpeg_result.hw_accel

    args = [
        ffmpeg_path,
        "-y", "-hide_banner",
        # Raw RGBA input from stdin
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{width}x{height}",
        "-r", str(fps_val),
        "-i", "pipe:0",
    ]

    # Add encoder args
    encoder_args = _get_encoder_args(codec, quality, container, video_bitrate, hw_info)
    args.extend(encoder_args)

    # No audio in this pass (will mux later if audio is provided)
    args.extend(["-an"])

    # Output to video-only temp file
    args.extend(["-progress", "pipe:1", video_only_path])

    print(f"[ComposeExport] Starting FFmpeg: {' '.join(args)}")

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        return JSONResponse({"error": f"Failed to start FFmpeg: {e}"}, status_code=500)

    job = ComposeExportJob(
        job_id=job_id,
        width=width,
        height=height,
        fps=fps_val,
        total_frames=total_frames,
        codec=codec,
        quality=quality,
        container=container,
        video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate,
        output_path=output_path,
        audio_path=None,
        process=process,
        frames_received=0,
        status="encoding",
        error=None,
        created_at=time.time(),
        frame_buffer={},
        next_frame_to_write=0,
        lock=threading.Lock(),
        encoder_fps=0.0,
    )

    compose_jobs[job_id] = job

    # Read FFmpeg progress in background
    asyncio.create_task(_read_compose_progress(job))

    return {
        "jobId": job_id,
        "status": "encoding",
        "outputPath": output_path,
        "encoder": encoder_args[1] if len(encoder_args) > 1 else "unknown",
        "hwAccel": hw_info.available,
    }


async def _read_compose_progress(job: ComposeExportJob):
    """Read FFmpeg progress output for a compose job."""
    if not job.process or not job.process.stdout:
        return
    try:
        while True:
            line = await job.process.stdout.readline()
            if not line:
                break
            text = line.decode()
            if "fps=" in text:
                try:
                    fps_str = text.split("fps=")[1].strip().split()[0]
                    job.encoder_fps = float(fps_str)
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass


@api_router.post("/ffmpeg/export-frame")
async def ffmpeg_export_frame(request: Request):
    """Receive a raw RGBA frame and write it to FFmpeg stdin."""
    body = await request.json()
    job_id = body.get("jobId")
    frame_index = body.get("frameIndex", 0)
    data_b64 = body.get("data")

    if not job_id or job_id not in compose_jobs:
        return JSONResponse({"error": "Invalid jobId"}, status_code=400)

    job = compose_jobs[job_id]

    if job.status not in ("encoding",):
        return JSONResponse({"error": f"Job not accepting frames (status: {job.status})"}, status_code=400)

    if not data_b64:
        return JSONResponse({"error": "Missing frame data"}, status_code=400)

    if not job.process or not job.process.stdin:
        return JSONResponse({"error": "FFmpeg process not available"}, status_code=500)

    try:
        frame_data = base64.b64decode(data_b64)
    except Exception as e:
        return JSONResponse({"error": f"Invalid base64 data: {e}"}, status_code=400)

    expected_size = job.width * job.height * 4  # RGBA = 4 bytes per pixel
    if len(frame_data) != expected_size:
        return JSONResponse({
            "error": f"Frame data size mismatch: got {len(frame_data)}, expected {expected_size}"
        }, status_code=400)

    # Buffer the frame and write in order
    with job.lock:
        job.frame_buffer[frame_index] = frame_data
        job.frames_received += 1

        # Write as many sequential frames as possible
        while job.next_frame_to_write in job.frame_buffer:
            data = job.frame_buffer.pop(job.next_frame_to_write)
            try:
                job.process.stdin.write(data)
                await job.process.stdin.drain()
            except Exception as e:
                job.status = "error"
                job.error = f"Failed to write frame {job.next_frame_to_write}: {e}"
                return JSONResponse({"error": job.error}, status_code=500)
            job.next_frame_to_write += 1

    return {"received": True, "framesReceived": job.frames_received}


@api_router.post("/ffmpeg/export-audio")
async def ffmpeg_export_audio(request: Request):
    """Receive WAV audio data to mux into the final output."""
    job_id = request.headers.get("X-Job-Id")

    if not job_id or job_id not in compose_jobs:
        return JSONResponse({"error": "Invalid jobId"}, status_code=400)

    job = compose_jobs[job_id]

    # Save audio to temp file
    audio_data = await request.body()
    audio_dir = os.path.dirname(job.output_path)
    audio_path = os.path.join(audio_dir, f"audio_{job_id}.wav")

    with open(audio_path, "wb") as f:
        f.write(audio_data)

    job.audio_path = audio_path
    print(f"[ComposeExport] Audio saved: {len(audio_data)} bytes -> {audio_path}")

    return {"received": True, "audioSize": len(audio_data)}


@api_router.post("/ffmpeg/export-finalize")
async def ffmpeg_export_finalize(request: Request):
    """Finalize the export — close FFmpeg stdin and wait for completion."""
    body = await request.json()
    job_id = body.get("jobId")

    if not job_id or job_id not in compose_jobs:
        return JSONResponse({"error": "Invalid jobId"}, status_code=400)

    job = compose_jobs[job_id]

    if job.status != "encoding":
        return JSONResponse({"error": f"Job not in encoding state (status: {job.status})"}, status_code=400)

    job.status = "finalizing"

    # Flush any remaining buffered frames
    with job.lock:
        while job.next_frame_to_write in job.frame_buffer:
            data = job.frame_buffer.pop(job.next_frame_to_write)
            try:
                if job.process and job.process.stdin:
                    job.process.stdin.write(data)
            except Exception:
                pass
            job.next_frame_to_write += 1

    # Close FFmpeg stdin to signal end of input
    if job.process and job.process.stdin:
        try:
            job.process.stdin.close()
        except Exception:
            pass

    # Wait for FFmpeg to finish
    try:
        _, stderr = await asyncio.wait_for(job.process.communicate(), timeout=120)
        if job.process.returncode != 0:
            error_msg = stderr.decode()[-500:] if stderr else "Unknown error"
            job.status = "error"
            job.error = f"FFmpeg exited with code {job.process.returncode}: {error_msg}"
            return JSONResponse({"error": job.error}, status_code=500)
    except asyncio.TimeoutError:
        job.process.terminate()
        job.status = "error"
        job.error = "FFmpeg timeout (120s)"
        return JSONResponse({"error": job.error}, status_code=500)

    # Determine the video-only file path
    ext = os.path.splitext(job.output_path)[1]
    video_only_path = os.path.join(os.path.dirname(job.output_path), f"video_{job.job_id}{ext}")

    # If we have audio, mux video + audio together
    if job.audio_path and os.path.exists(job.audio_path):
        ffmpeg_path = get_ffmpeg_path()
        container = job.container

        audio_codec_args = []
        if container == "webm":
            audio_codec_args = ["-c:a", "libopus", "-b:a", str(job.audio_bitrate or 128000)]
        elif container in ("mp4", "mov"):
            audio_codec_args = ["-c:a", "aac", "-b:a", str(job.audio_bitrate or 192000)]
        else:
            audio_codec_args = ["-c:a", "aac", "-b:a", str(job.audio_bitrate or 192000)]

        mux_args = [
            ffmpeg_path,
            "-y", "-hide_banner",
            "-i", video_only_path,
            "-i", job.audio_path,
            "-c:v", "copy",
            *audio_codec_args,
            "-shortest",
        ]

        if container == "mp4":
            mux_args.extend(["-movflags", "+faststart"])

        mux_args.append(job.output_path)

        print(f"[ComposeExport] Muxing audio: {' '.join(mux_args)}")

        mux_process = await asyncio.create_subprocess_exec(
            *mux_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, mux_stderr = await asyncio.wait_for(mux_process.communicate(), timeout=60)

        if mux_process.returncode != 0:
            # Fallback: use video-only output
            print(f"[ComposeExport] Audio mux failed, using video-only: {mux_stderr.decode()[-200:]}")
            if os.path.exists(video_only_path):
                import shutil
                shutil.move(video_only_path, job.output_path)
        else:
            # Clean up video-only temp file
            if os.path.exists(video_only_path):
                os.unlink(video_only_path)
    else:
        # No audio - rename video-only to final output
        import shutil
        if os.path.exists(video_only_path):
            shutil.move(video_only_path, job.output_path)

    # Get file size
    file_size = 0
    if os.path.exists(job.output_path):
        file_size = os.path.getsize(job.output_path)

    job.status = "done"

    print(f"[ComposeExport] Export complete: {file_size} bytes -> {job.output_path}")

    return {
        "success": True,
        "fileSize": file_size,
        "outputPath": job.output_path,
    }


@api_router.get("/ffmpeg/export-progress/{job_id}")
async def ffmpeg_export_progress(job_id: str):
    """Get progress for a compose export job."""
    if job_id not in compose_jobs:
        return JSONResponse({"error": "Invalid jobId"}, status_code=404)

    job = compose_jobs[job_id]
    progress = 0.0
    if job.total_frames > 0:
        progress = min(job.frames_received / job.total_frames, 1.0)

    return {
        "jobId": job_id,
        "phase": job.status,
        "progress": progress,
        "framesReceived": job.frames_received,
        "totalFrames": job.total_frames,
        "encoderFps": job.encoder_fps,
    }


@api_router.get("/ffmpeg/export-download/{job_id}")
async def ffmpeg_export_download(job_id: str):
    """Download the finished export file."""
    if job_id not in compose_jobs:
        return JSONResponse({"error": "Invalid jobId"}, status_code=404)

    job = compose_jobs[job_id]

    if job.status != "done":
        return JSONResponse({"error": f"Export not complete (status: {job.status})"}, status_code=400)

    if not os.path.exists(job.output_path):
        return JSONResponse({"error": "Output file not found"}, status_code=404)

    # Determine content type
    content_types = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
        "mkv": "video/x-matroska",
    }
    content_type = content_types.get(job.container, "video/mp4")

    ext = job.container or "mp4"
    filename = f"export.{ext}"
    
    return FileResponse(
        job.output_path,
        media_type=content_type,
        filename=filename,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@api_router.post("/ffmpeg/export-cancel/{job_id}")
async def ffmpeg_export_cancel(job_id: str):
    """Cancel an active compose export job."""
    if job_id not in compose_jobs:
        return JSONResponse({"error": "Invalid jobId"}, status_code=404)

    job = compose_jobs[job_id]

    if job.process and job.process.returncode is None:
        try:
            job.process.terminate()
        except Exception:
            pass

    job.status = "cancelled"
    _cleanup_job_files(job)

    return {"success": True}


# ============= File System =============

@api_router.post("/fs/write-file")
async def fs_write_file(request: Request):
    """Write data to a file."""
    body = await request.json()
    file_path = body.get("filePath")
    data_base64 = body.get("data")
    
    if not file_path:
        return JSONResponse({"error": "filePath required"}, status_code=400)
    
    if not data_base64:
        return JSONResponse({"error": "data required"}, status_code=400)
    
    try:
        data = base64.b64decode(data_base64)
        with open(file_path, "wb") as f:
            f.write(data)
        return {"success": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============= System Info =============

@api_router.get("/system/info")
async def system_info():
    """Get system information."""
    return {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "cpu_count": psutil.cpu_count(),
        "memory_total": psutil.virtual_memory().total,
    }


# ============= Include API Router =============
# Mount API routes BEFORE the catch-all static file route
app.include_router(api_router)


# ============= Frontend Static Files =============
# These MUST come after all API routes to avoid intercepting them

@app.get("/")
async def root():
    """Serve the frontend index.html."""
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(content="""
        <html>
        <head><title>FreeCut</title></head>
        <body>
            <h1>FreeCut Video Editor</h1>
            <p>Frontend not built. Run <code>npm run build</code> first.</p>
        </body>
        </html>
    """, status_code=200)


@app.get("/{path:path}")
async def serve_static(path: str):
    """Serve static files from the frontend build."""
    # Try to serve from dist directory
    file_path = FRONTEND_DIST / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    
    # Fallback to index.html for SPA routing
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    
    return JSONResponse({"error": "File not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
