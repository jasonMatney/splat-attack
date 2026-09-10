"""Real FFmpeg -> COLMAP -> Brush pipeline. No network calls or cloud jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PRESETS = {
    'preview': dict(fps=2, max_frames=360, resolution=1280, steps=6000, splats=750000),
    'office': dict(fps=4, max_frames=900, resolution=1600, steps=20000, splats=2000000),
    'detail': dict(fps=5, max_frames=1500, resolution=1920, steps=30000, splats=4000000),
}


def tool(name):
    override = os.environ.get('SPLAT_' + name.upper())
    choices = [override] if override else []
    if name == 'brush':
        choices += [str(ROOT / '.tools/brush/brush_app'), shutil.which('brush_app'), shutil.which('brush')]
    else:
        choices += [shutil.which(name), '/opt/homebrew/bin/' + name, '/usr/local/bin/' + name]
    for candidate in choices:
        if candidate and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise RuntimeError(f'{name} is missing. Run scripts/setup-mac.sh first.')


def probe(video):
    result = subprocess.run([tool('ffprobe'), '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(video)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    streams = [s for s in data['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if not streams:
        raise ValueError('This file has no video track.')
    stream = streams[0]
    duration = float(stream.get('duration') or data.get('format', {}).get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Could not determine video duration.')
    return dict(duration=duration, width=stream['width'], height=stream['height'],
                codec=stream['codec_name'], color_transfer=stream.get('color_transfer'),
                stream_index=stream['index'])


def sample_rate(duration, preset):
    # Cover the entire clip, even when it is longer than the preset frame budget.
    return min(preset['fps'], preset['max_frames'] / duration)


def memory_budget():
    try:
        if sys.platform == 'darwin':
            return int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.memsize'], stderr=subprocess.DEVNULL))
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def ffmpeg_command(video, images, info, config):
    limit = config['resolution']
    filters = [f"fps={sample_rate(info['duration'], config):.8f}"]
    if info.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        filters += ['zscale=t=linear:npl=100', 'format=gbrpf32le',
                    'zscale=p=bt709', 'tonemap=tonemap=hable:desat=0',
                    'zscale=t=bt709:m=bt709:r=tv', 'format=yuv420p']
    filters += [f"scale=w='min({limit},iw)':h='min({limit},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"]
    return [tool('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'warning', '-i', str(video),
            '-map', f"0:{info['stream_index']}", '-vf', ','.join(filters),
            '-frames:v', str(config['max_frames']), '-q:v', '2', str(images / 'frame_%06d.jpg')]


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2))
    temporary.replace(path)


def inspect_splat(path):
    with path.open('rb') as file:
        header = file.read(16384).split(b'end_header', 1)[0].decode('ascii', errors='replace')
    if not header.startswith('ply\n') or 'element vertex ' not in header:
        raise RuntimeError('Trainer output is not a PLY file.')
    for field in ('f_dc_0', 'opacity', 'scale_0', 'rot_0'):
        if field not in header:
            raise RuntimeError(f'Trainer output is missing Gaussian property {field}.')
    count = int(next(line.split()[-1] for line in header.splitlines() if line.startswith('element vertex ')))
    if count < 1:
        raise RuntimeError('Trainer produced an empty splat.')
    return count


def usable_models(models):
    """Reject obviously divergent intrinsics before choosing by coverage."""
    return {key: model for key, model in models.items() if all(
        0.25 <= camera.params[0] / max(camera.width, camera.height) <= 2.0
        and abs(camera.params[-1]) <= 0.5
        for camera in model.cameras.values())}


def run(video, output, preset='office', steps=None, min_registered=12, min_ratio=0.6, allow_partial=False):
    import pycolmap as pc

    video = Path(video).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    if not video.is_file():
        raise ValueError('Choose an existing video file.')
    tool('ffmpeg'); tool('ffprobe'); brush = tool('brush')
    info = probe(video)
    if info['duration'] < 5:
        raise ValueError('Use at least 5 seconds of video with camera movement.')
    if output.exists():
        raise ValueError('Output folder already exists. Choose a new folder to protect earlier results.')
    output.mkdir(parents=True)
    config = dict(PRESETS[preset])
    config['train_resolution'] = config['resolution']
    ram = memory_budget()
    if ram is not None and ram <= 8 * 1024**3:
        config['train_resolution'] = min(config['resolution'], 768)
        config['splats'] = min(config['splats'], 250000)
    if steps is not None:
        if steps < 1:
            raise ValueError('Training steps must be positive.')
        config['steps'] = steps
    state = dict(status='running', stage='prepare', source=str(video), video=info,
                 preset=preset, config=config, started=time.time(), output=str(output),
                 versions={'pycolmap': pc.__version__, 'brush': '0.3.0'}, warnings=[], allow_partial=allow_partial)
    if config['train_resolution'] != config['resolution']:
        state['warnings'].append('8 GB memory mode: training at 768 px with a 250,000 splat cap. Fine detail will be reduced.')
    log = (output / 'pipeline.log').open('a', buffering=1)

    def emit(stage, message, **fields):
        state.update(stage=stage, message=message, **fields)
        write_json(output / 'status.json', state)
        print(json.dumps(dict(stage=stage, message=message, **fields)), flush=True)

    def command(args):
        log.write('\nCOMMAND: ' + repr(args) + '\n')
        subprocess.run(args, stdout=log, stderr=log, check=True)

    def cancelled(signum, frame):
        raise KeyboardInterrupt

    previous_handler = signal.signal(signal.SIGTERM, cancelled)
    try:
        emit('extract', 'Extracting frames across the full video')
        images = output / 'images'; images.mkdir()
        command(ffmpeg_command(video, images, info, config))
        count = len(list(images.glob('*.jpg')))
        if count < min_registered:
            raise ValueError(f'Only {count} frames were extracted. Record a longer walk around the room.')
        state['frames'] = count
        state['sample_fps'] = sample_rate(info['duration'], config)
        # The fingerprint and logs stay on the user's disk with the reconstruction.
        digest = hashlib.sha256()
        with video.open('rb') as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b''):
                digest.update(chunk)
        state['source_sha256'] = digest.hexdigest()
        db = str(output / 'database.db')
        emit('features', f'Finding visual features in {count} frames')
        extraction = pc.FeatureExtractionOptions()
        extraction.num_threads = min(os.cpu_count() or 4, 8)
        extraction.max_image_size = config['resolution']
        reader = pc.ImageReaderOptions()
        reader.default_focal_length_factor = 0.85
        pc.extract_features(db, str(images), camera_mode=pc.CameraMode.SINGLE,
                            camera_model='SIMPLE_RADIAL', extraction_options=extraction,
                            reader_options=reader, device=pc.Device.cpu)
        emit('match', 'Matching overlapping views')
        pairing = pc.SequentialPairingOptions()
        pairing.overlap = min(20, count - 1)
        pairing.loop_detection = False  # No vocabulary download; stay offline.
        matching = pc.FeatureMatchingOptions()
        matching.num_threads = min(os.cpu_count() or 4, 8)
        pc.match_sequential(db, pairing_options=pairing, matching_options=matching, device=pc.Device.cpu)
        emit('cameras', 'Solving camera positions and room structure')
        sparse = output / 'sparse'; sparse.mkdir()
        options = pc.IncrementalPipelineOptions()
        options.num_threads = min(os.cpu_count() or 4, 8)
        options.mapper.init_min_tri_angle = 4
        models = pc.incremental_mapping(db, str(images), str(sparse), options=options)
        models = usable_models(models)
        best_count = max((m.num_reg_images() for m in models.values()), default=0)
        if best_count / count < min_ratio and count <= 400:
            emit('match', 'Coverage is incomplete. Trying all frame pairs to recover revisited areas.')
            matching.guided_matching = True
            pc.match_exhaustive(db, matching_options=matching, device=pc.Device.cpu)
            retry_path = output / 'sparse-recovery'; retry_path.mkdir()
            emit('cameras', 'Reconstructing with the additional frame matches')
            recovered = usable_models(pc.incremental_mapping(db, str(images), str(retry_path), options=options))
            if max((m.num_reg_images() for m in recovered.values()), default=0) > best_count:
                models = recovered
            state['recovery_attempted'] = True
        if not models:
            raise RuntimeError('No room could be reconstructed. Walk slowly around textured furniture; avoid a stationary pan, blur and blank walls.')
        model_id, model = max(models.items(), key=lambda item: item[1].num_reg_images())
        registered = model.num_reg_images()
        ratio = registered / count
        state.update(registered=registered, registration_ratio=ratio, points=model.num_points3D(), components=len(models))
        selected = output / 'selected-model'; selected.mkdir()
        model.write(str(selected))
        state['selected_model'] = str(selected)
        if registered < min_registered or (ratio < min_ratio and not allow_partial):
            raise RuntimeError(f'Only {registered}/{count} frames joined the largest reconstruction. Training stopped to avoid a misleading partial room. Capture more overlap and keep one lens throughout.')
        if ratio < 0.9 or len(models) > 1:
            state['warnings'].append(f'The largest component contains {registered}/{count} frames. Some room coverage may be missing.')
        state['partial'] = ratio < min_ratio
        emit('undistort', f'{registered}/{count} camera views reconstructed; preparing training images')
        dataset = output / 'dataset'
        undistort = pc.UndistortCameraOptions()
        undistort.max_image_size = config['resolution']
        pc.undistort_images(str(dataset), str(selected), str(images), undistort_options=undistort)
        # Brush reads COLMAP models under sparse/0.
        model_files = list((dataset / 'sparse').glob('*.bin'))
        if model_files:
            (dataset / 'sparse/0').mkdir()
            for file in model_files:
                file.rename(dataset / 'sparse/0' / file.name)
        exports = output / 'exports'; exports.mkdir()
        emit('train', f"Training {config['steps']:,} steps on your GPU; this can take a while")
        export_every = 1000 if config['steps'] % 1000 == 0 else config['steps']
        command([brush, str(dataset), '--total-steps', str(config['steps']),
                 '--max-resolution', str(config['train_resolution']), '--max-splats', str(config['splats']),
                 '--growth-stop-iter', str(max(1, int(config['steps'] * 0.75))),
                 '--export-every', str(export_every), '--export-path', str(exports),
                 '--export-name', 'office.ply'])
        result = exports / 'office.ply'
        splats = inspect_splat(result)
        raw_result = result
        try:
            from .view_export import orient_for_viewer
            viewing = exports / 'office-view.ply'
            transform = orient_for_viewer(result, viewing, dataset / 'sparse/0')
            write_json(exports / 'view-transform.json', transform)
            result = viewing
        except (ValueError, OSError) as error:
            state['warnings'].append(f'Could not create the initial viewing orientation: {error}. Original export retained.')
        ready_message = f'Partial scene ready: only {registered}/{count} views reconstructed' if state['partial'] else 'Your splat is ready to open'
        emit('complete', ready_message, status='complete', result=str(result), raw_result=str(raw_result),
             splats=splats, finished=time.time())
        return result
    except KeyboardInterrupt:
        emit('cancelled', 'Stopped. Intermediate files and logs were kept.', status='cancelled', finished=time.time())
        raise
    except Exception as error:
        detail = f"{state['stage'].capitalize()} failed (exit {error.returncode})." if isinstance(error, subprocess.CalledProcessError) else str(error)
        emit('failed', detail + ' See pipeline.log and console.log for details.', status='failed', finished=time.time())
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
        log.close()


def main():
    # A separate session allows the desktop Stop button to stop the whole job.
    if os.environ.get('SPLAT_PROCESS_GROUP') == '1':
        os.setsid()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor')
    job = sub.add_parser('run')
    job.add_argument('video', type=Path)
    job.add_argument('--output', type=Path, required=True)
    job.add_argument('--preset', choices=PRESETS, default='office')
    job.add_argument('--steps', type=int, help='Override for diagnostics; normal captures should use a preset')
    job.add_argument('--allow-partial', action='store_true', help='Train the largest valid component even below 60%% coverage; output is labeled partial')
    view = sub.add_parser('view'); view.add_argument('ply', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            import pycolmap
            print(json.dumps({name: tool(name) for name in ['ffmpeg', 'ffprobe', 'brush']} | {'pycolmap': pycolmap.__version__}))
        elif args.action == 'view':
            inspect_splat(args.ply)
            subprocess.run([tool('brush'), str(args.ply.resolve()), '--with-viewer'], check=True)
        else:
            run(args.video, args.output, args.preset, args.steps, allow_partial=args.allow_partial)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
