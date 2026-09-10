# Splat Attack

An iPhone video → interior Gaussian splat workflow for Apple Silicon Macs.
The native desktop app imports MOV/MP4 footage, extracts frames, reconstructs
cameras with COLMAP, trains a real Gaussian splat with Brush, and opens it in
Brush's interactive viewer. Processing does not upload your footage.

## Start on this Mac

Open **`dist/Splat Attack.app`**, choose an AirDropped video, select **Quick
preview** or **Office**, then **Generate interior splat**. After training,
click **Open splat in Brush**. Dragging a video into the window also selects it.

Keep this checkout in place: the app links to its `.venv`, `.tools`, and `runs`
directories. If you move the checkout, rebuild the app. This is a local developer
build, not a signed/notarized standalone redistributable installer.

## Set up another Mac

Requirements: **Apple Silicon, macOS 14+, Xcode command-line tools, Homebrew,
Python 3.11 and FFmpeg**. Allow disk space for the source, extracted images,
undistorted copies, camera database, and splat. 16 GB memory is a sensible
starting point; large jobs can need more. GPU memory/performance is workload
dependent.

```bash
git clone https://github.com/jasonMatney/splat-attack.git
cd splat-attack
bash scripts/setup-mac.sh
open "dist/Splat Attack.app"
```

The setup script installs pinned Python packages in `.venv` and downloads the
official Brush v0.3.0 Apple Silicon release with a pinned SHA-256 checksum.
Internet is needed for setup. Subsequent reconstruction uses local files and
does not require an account or cloud service. Existing filesystem sync software
can still sync files in whatever location you choose for the checkout.

## Record an office that reconstructs well

1. Use the iPhone's **standard Video mode, 1× lens, 4K/30 fps** when available.
   1080p footage also works. Avoid Cinematic/Action modes, digital zoom, or lens
   switching during a clip. HDR and portrait orientation are handled on import.
2. Turn on the office lights and keep people and objects still. Lock exposure
   and focus when practical.
3. Walk slowly for **1–3 minutes**, keeping desks, chairs and corners visible
   from several positions. Move around objects rather than only rotating in
   place. Translation is essential for triangulation.
4. Use overlapping views. Return to the starting area and capture important
   furniture at more than one height. Blank walls, reflections, windows and
   motion blur may leave holes or floating artifacts.
5. AirDrop the original MOV to the Mac. Try **Quick preview** to check coverage
   before spending time on a full training run.

These are capture recommendations, not a guarantee of quality or dimensional
accuracy. Reconstructed coordinates have no surveyed scale or georeferencing.
This produces a visual splat, not a measured BIM model or watertight mesh.

## What runs

| Stage | Implementation |
|---|---|
| Import | FFprobe checks duration and video track. FFmpeg applies orientation metadata, tone-maps HLG/PQ HDR, and extracts JPEGs. |
| Sample | 2/4/5 frames/second for Preview/Office/Detail; lower rate for long videos so the frame cap covers the full clip. |
| Features | CPU COLMAP SIFT, one SIMPLE_RADIAL camera for a fixed-lens clip. |
| Match | Sequential matching with overlapping and quadratic-neighbor views. If coverage fails on up to 400 frames, automatically retry all pairs with guided matching. No vocabulary downloads. |
| Cameras | Incremental COLMAP mapping, choosing the largest connected component. |
| Quality gate | Reject implausible focal length/distortion. Require at least 12 registered frames and 60% registration by default; partial coverage is reported. |
| Prepare | Undistort into a PINHOLE COLMAP dataset that Brush can train. |
| Train | Brush v0.3.0 on the Mac's Metal GPU. |
| Export | `exports/office.ply`, validated to contain Gaussian properties, plus source fingerprint and job metadata. |

| Preset | Frame cap | Longest edge | Training steps | Splat cap |
|---|---:|---:|---:|---:|
| Quick preview | 360 | 1280 | 6,000 | 750,000 |
| Office | 900 | 1600 | 20,000 | 2,000,000 |
| High detail | 1,500 | 1920 | 30,000 | 4,000,000 |

Runtime varies with the Mac and capture. The interface reports real pipeline
stages; it does not invent a percentage or ETA. Plug in the Mac and keep it awake.
The Stop button terminates the job process group and keeps intermediate files.
Each new run gets a unique folder; existing results are never overwritten.
An interrupted job can be inspected but the app does not yet resume training.

## Command line

```bash
.venv/bin/python -m splat_attack.pipeline doctor
.venv/bin/python -m splat_attack.pipeline run ~/Downloads/IMG_1234.MOV \
  --output runs/my-office --preset office
.venv/bin/python -m splat_attack.pipeline view runs/my-office/exports/office.ply
```

`--steps` is available for diagnostics. A 20-step test verifies execution, not
visual convergence. `SPLAT_FFMPEG`, `SPLAT_FFPROBE`, and `SPLAT_BRUSH` can point to
alternative installed binaries. The pinned versions are the supported baseline.

Results stay in `runs/<job>/`. `status.json` records the source SHA-256, settings,
registered frames, selected component, warnings and final PLY path.
`pipeline.log` contains FFmpeg/Brush command logs; desktop jobs also capture
COLMAP output in `console.log`. **Runs, videos, trained scenes, dependencies and
build artifacts are excluded from Git.**

The optional **Keep a partial scene** checkbox (`--allow-partial` in the CLI)
allows training the largest usable component below 60% coverage. It still
requires 12 views, and the resulting status and UI explicitly say **partial**.
This cannot fill in unobserved parts of the office.

If reconstruction fails, check the logs and capture guidance. Missing camera
overlap cannot be fixed by training for more steps. A GPU adapter error in a
restricted shell means Brush cannot access Metal there; launch normally from
the desktop or use a shell with GPU access.

## Verify

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/make_test_video.py /tmp/splat-fixture
.venv/bin/python -m splat_attack.pipeline run /tmp/splat-fixture/SYNTHETIC-room.mp4 \
  --output /tmp/splat-check --preset preview --steps 20
```

The fixture generator creates a **synthetic** textured room solely for testing.
It is not representative evidence of real-office reconstruction quality.

## Scope and credits

This implements the video-to-splat portion of the AirVis Studio workflow with
independent code and public reconstruction engines. It does not reproduce
AirVis's proprietary renderer, collision generation, LOD streaming, masking,
cloud sharing, or headset clients. The app is macOS-only; the pipeline could be
adapted to other Brush-supported systems but those platforms are not validated.

- [COLMAP / pycolmap](https://github.com/colmap/colmap): camera reconstruction;
  BSD-3-Clause. [CLI reference](https://colmap.github.io/cli.html).
- [Brush](https://github.com/ArthurBrussee/brush/tree/v0.3.0): Gaussian training
  and viewing; Apache-2.0. Official release LICENSE is retained with the binary.
- [FFmpeg](https://ffmpeg.org/): video decoding and frame extraction; licensing
  depends on the installed build.
- NumPy and Pillow: Python dependencies and synthetic test rendering.

No AirVis code or assets are included.
