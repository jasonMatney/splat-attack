# Validation — September 10, 2026

Environment: Apple M3 Mac, 8 GB unified memory; Python 3.11, pycolmap 3.13.0,
Brush v0.3.0, FFmpeg 7.1.1. Native app compiled and launched locally.

## Checks completed

- Eight automated tests pass: frame sampling, real FFmpeg extraction, safe
  argument handling, existing-output protection, invalid splat rejection,
  divergent-camera rejection, 8 GB configuration, and appearance/covariance
  preservation under viewing-coordinate rotation. Some tests cover several
  related assertions.
- A synthetic 24-second textured-room video ran through the full pipeline:
  48/48 views registered, 6,360 Gaussians exported after 20 training steps.
  This checks execution, not convergence or real-office quality.
- A real 64-second portrait iPhone HEVC/HLG capture was decoded, rotated and
  tone-mapped. Initial sequential mapping registered 11/127 frames. Exhaustive
  guided recovery recovered a usable 29/127-view component. A denser 4 FPS
  attempt recovered 44/254 views, still below the default 60% coverage gate.
- A **partial** preview from the 29-view component trained for 6,000 steps at
  1280 px with a 750,000-splat cap. It exported **51,672 Gaussians**, about
  **12.2 MB**, in roughly **12 minutes 40 seconds**, including preparation.
  This run predates the automatic 8 GB training cap. Its timing is not a
  prediction for other captures or concurrent workloads.
- The real export opened in Brush and reported the expected Gaussian count.
  A diagnostic projection at a recovered camera shows recognizable lounge
  furniture, with blur and artifacts. It does **not** represent a complete,
  clean reconstruction of the office. The native viewer's generic initial
  pose was unsuitable, motivating the separate camera-aligned viewing export.

The office video, scene files, screenshots, camera database and source paths
are excluded from Git. A faster, more accurate reconstruction of this full
walkthrough remains unverified. Capture one area slowly, with substantial
translation and overlapping views, before evaluating larger office scans.
