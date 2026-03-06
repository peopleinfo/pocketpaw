# FreeCut Backend Migration & Export Architecture

This project has been completely migrated from Electron to a pure **Python + FastAPI** backend using **uv** for dependency management. The frontend remains a React + Vite application, but all native OS interactions are now handled by the Python server.

## Key Architecture Upgrades

- **Backend**: Python 3.11+, FastAPI, Uvicorn, managed by `uv`.
- **Export Pipeline**: Replaced the slow, frame-by-frame WebCodecs client-side rendering with a blazing-fast **GPU-accelerated FFmpeg** pipeline.
  - Video and audio tracks are processed natively via `imageio-ffmpeg` using hardware acceleration (e.g., `h264_nvenc` for NVIDIA GPUs).
  - Handles complex filter graphs, multi-clip compositions, and silent audio generation smoothly.
  - Export speeds have dramatically increased, matching professional desktop applications (e.g., CapCut).
- **Download Flow**: Uses the File System Access API (`showSaveFilePicker`) to seamlessly save the exported file from the Python backend to the user's local file system.
