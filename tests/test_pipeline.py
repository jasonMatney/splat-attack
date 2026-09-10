import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from splat_attack.pipeline import PRESETS, ffmpeg_command, inspect_splat, probe, run, sample_rate, usable_models


class PipelineTests(unittest.TestCase):
    def test_eight_gb_mode_caps_training_but_preserves_reconstruction_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / 'source.MOV'; video.write_bytes(b'mocked video')
            output = Path(tmp) / 'run'
            info = dict(duration=6, width=1920, height=1080, stream_index=0)
            with patch('splat_attack.pipeline.memory_budget', return_value=8*1024**3), \
                 patch('splat_attack.pipeline.probe', return_value=info), \
                 patch('splat_attack.pipeline.tool', return_value='/bin/true'), \
                 patch('splat_attack.pipeline.subprocess.run', side_effect=RuntimeError('test stops before extraction')):
                with self.assertRaisesRegex(RuntimeError, 'test stops'):
                    run(video, output)
            state = json.loads((output / 'status.json').read_text())
            self.assertEqual(state['config']['train_resolution'], 768)
            self.assertEqual(state['config']['resolution'], 1600)
            self.assertEqual(state['config']['splats'], 250000)

    def test_divergent_camera_is_not_chosen_for_training(self):
        def model(focal, distortion):
            return SimpleNamespace(cameras={1:SimpleNamespace(width=900, height=1600, params=[focal,450,800,distortion])})
        models = {0:model(1431,.02),1:model(8096,25.2),2:model(float('nan'),0)}
        self.assertEqual(list(usable_models(models)), [0])

    def test_long_video_samples_entire_clip(self):
        self.assertAlmostEqual(sample_rate(900, PRESETS['preview']), 0.4)
        self.assertEqual(sample_rate(20, PRESETS['office']), 4)

    def test_hdr_and_spaces_are_passed_as_arguments(self):
        info = dict(duration=60, stream_index=0, color_transfer='arib-std-b67')
        with patch('splat_attack.pipeline.tool', return_value='/bin/ffmpeg'):
            cmd = ffmpeg_command(Path('/tmp/my office.MOV'), Path('/tmp/frame output'), info, PRESETS['office'])
        self.assertIn('/tmp/my office.MOV', cmd)
        self.assertIn('tonemap=tonemap=hable', cmd[cmd.index('-vf') + 1])

    def test_point_cloud_is_not_a_splat(self):
        with tempfile.TemporaryDirectory() as tmp:
            ply = Path(tmp) / 'points.ply'
            ply.write_text('ply\nformat ascii 1.0\nelement vertex 10\nproperty float x\nend_header\n')
            with self.assertRaisesRegex(RuntimeError, 'Gaussian'):
                inspect_splat(ply)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_extract_real_video_and_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); video = root / 'test clip.mp4'; images = root / 'images'; images.mkdir()
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=10:duration=6', '-c:v', 'libx264', str(video)], check=True)
            info = probe(video)
            self.assertAlmostEqual(info['duration'], 6, places=1)
            subprocess.run(ffmpeg_command(video, images, info, PRESETS['preview']), check=True)
            self.assertEqual(len(list(images.glob('*.jpg'))), 12)
            with patch('splat_attack.pipeline.tool', return_value='/bin/true'):
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    # probe needs the real binary; supply its already verified result.
                    with patch('splat_attack.pipeline.probe', return_value=info):
                        run(video, images)
            self.assertEqual(len(list(images.glob('*.jpg'))), 12)


if __name__ == '__main__':
    unittest.main()
