"""Rigid viewing copy for Brush's default camera; retains the original PLY.

Positions, covariance rotations, and degree 0–3 real spherical harmonics rotate
together. This changes the coordinate frame, not the reconstructed geometry.
"""
from pathlib import Path
import numpy as np
import pycolmap as pc


def sh_basis(directions):
    x, y, z = np.asarray(directions).T
    return np.column_stack([
        np.ones_like(x)*.28209479177387814,
        -.4886025119029199*y, .4886025119029199*z, -.4886025119029199*x,
        1.0925484305920792*x*y, -1.0925484305920792*y*z,
        .31539156525252005*(2*z*z-x*x-y*y), -1.0925484305920792*x*z,
        .5462742152960396*(x*x-y*y),
        -.5900435899266435*y*(3*x*x-y*y), 2.890611442640554*x*y*z,
        -.4570457994644658*y*(4*z*z-x*x-y*y),
        .3731763325901154*z*(2*z*z-3*x*x-3*y*y),
        -.4570457994644658*x*(4*z*z-x*x-y*y),
        1.445305721320277*z*(x*x-y*y), -.5900435899266435*x*(x*x-3*y*y),
    ])


def sh_rotation(rotation, count=16):
    directions = np.random.default_rng(42).normal(size=(64, 3))
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    # new directions map back to the old world via the inverse rigid rotation.
    return np.linalg.lstsq(sh_basis(directions)[:, :count],
                          sh_basis(directions @ rotation)[:, :count], rcond=None)[0]


def quaternion_product(left, right):
    w, x, y, z = left
    a, b, c, d = right.T
    return np.column_stack([w*a-x*b-y*c-z*d, w*b+x*a+y*d-z*c,
                            w*c-x*d+y*a+z*b, w*d+x*c-y*b+z*a])


def orient_for_viewer(source, destination, model_path, image_name=None):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Viewing copy already exists; refusing to overwrite it.')
    with source.open('rb') as file:
        header = []
        while True:
            line = file.readline()
            if not line or sum(map(len, header)) > 65536:
                raise ValueError('Invalid PLY header')
            header.append(line)
            if line.strip() == b'end_header':
                break
        lines = b''.join(header).decode('ascii').splitlines()
        if 'format binary_little_endian 1.0' not in lines:
            raise ValueError('Viewing copies currently require Brush binary little-endian PLY output.')
        properties = [line.split() for line in lines if line.startswith('property ')]
        if any(parts[1] != 'float' for parts in properties):
            raise ValueError('Unsupported property type in viewing export')
        names = [parts[-1] for parts in properties]
        count = int(next(line.split()[-1] for line in lines if line.startswith('element vertex ')))
        values = np.fromfile(file, dtype=[(name, '<f4') for name in names], count=count)
    if len(values) != count:
        raise ValueError('Truncated PLY')
    model = pc.Reconstruction(str(model_path))
    views = sorted(model.images.values(), key=lambda view: view.name)
    if not views:
        raise ValueError('No reconstructed viewing cameras')
    view = next(v for v in views if v.name == image_name) if image_name else views[len(views)//2]
    rotation = view.cam_from_world().rotation.matrix()
    translation = view.cam_from_world().translation + np.array([0, 0, -2.5])
    xyz = np.column_stack([values[name] for name in ['x', 'y', 'z']]) @ rotation.T + translation
    for axis, name in enumerate(['x', 'y', 'z']):
        values[name] = xyz[:, axis]
    # COLMAP exposes x,y,z,w; Gaussian PLY uses w,x,y,z.
    q = view.cam_from_world().rotation.quat[[3, 0, 1, 2]]
    rotated = quaternion_product(q, np.column_stack([values[f'rot_{i}'] for i in range(4)]))
    rotated /= np.linalg.norm(rotated, axis=1)[:, None]
    for i in range(4):
        values[f'rot_{i}'] = rotated[:, i]
    rest = len([name for name in names if name.startswith('f_rest_')])
    coefficients = rest//3+1
    if rest % 3 or coefficients not in (1, 4, 9, 16):
        raise ValueError('Unsupported spherical harmonic degree')
    transform = sh_rotation(rotation, coefficients)
    for channel in range(3):
        fields = [f'f_dc_{channel}'] + [f'f_rest_{channel*(coefficients-1)+i}' for i in range(coefficients-1)]
        sh = np.column_stack([values[field] for field in fields]) @ transform.T
        for i, field in enumerate(fields):
            values[field] = sh[:, i]
    with destination.open('xb') as file:
        file.write(b''.join(header))
        values.tofile(file)
    return {'image': view.name, 'rotation': rotation.tolist(), 'translation': translation.tolist(),
            'viewer_camera': [0, 0, -2.5], 'source': str(source), 'result': str(destination)}
