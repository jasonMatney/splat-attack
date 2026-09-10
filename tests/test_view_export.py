import unittest
import numpy as np
import pycolmap as pc
from splat_attack.view_export import sh_basis, sh_rotation, quaternion_product


class ViewingExportTests(unittest.TestCase):
    def test_rotation_preserves_view_dependent_colors(self):
        rotation = pc.Rotation3d(np.array([.3, -.4, .1])).matrix()
        rng = np.random.default_rng(13)
        directions = rng.normal(size=(150, 3)); directions /= np.linalg.norm(directions, axis=1)[:,None]
        for count in [1,4,9,16]:
            coefficients = rng.normal(size=(count,3))
            expected = sh_basis(directions @ rotation)[:,:count] @ coefficients
            actual = sh_basis(directions)[:,:count] @ sh_rotation(rotation, count) @ coefficients
            np.testing.assert_allclose(actual, expected, atol=1e-12)

    def test_quaternion_product_rotates_covariance(self):
        r = pc.Rotation3d(np.array([.3, -.4, .1]))
        s = pc.Rotation3d(np.array([.1, .2, -.5]))
        output = quaternion_product(r.quat[[3,0,1,2]], s.quat[[3,0,1,2]][None,:])[0]
        matrix = pc.Rotation3d(output[[1,2,3,0]]).matrix()
        np.testing.assert_allclose(matrix, r.matrix() @ s.matrix(), atol=1e-12)


if __name__ == '__main__':
    unittest.main()
