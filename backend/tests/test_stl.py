import struct
import unittest

from app.services.stl import bounding_box, copies_on_plate


def cube_stl(size: float = 20.0) -> bytes:
    s = size
    verts = [
        (0, 0, 0),
        (s, 0, 0),
        (s, s, 0),
        (0, s, 0),
        (0, 0, s),
        (s, 0, s),
        (s, s, s),
        (0, s, s),
    ]
    faces = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    ]
    buf = bytearray(80)
    buf += struct.pack("<I", 12)
    for i, j, k in faces:
        buf += struct.pack("<12fH", 0, 0, 1, *verts[i], *verts[j], *verts[k], 0)
    return bytes(buf)


class PlatePackTests(unittest.TestCase):
    def test_grid_on_220(self) -> None:
        pack = copies_on_plate(50, 50, 220, 220, 8)
        self.assertEqual(pack.copies, 9)
        self.assertEqual(pack.cols, 3)
        self.assertEqual(pack.rows, 3)
        self.assertFalse(pack.rotated)

    def test_rotation_helps(self) -> None:
        pack = copies_on_plate(80, 30, 220, 100, 8)
        self.assertEqual(pack.copies, 6)
        self.assertTrue(pack.rotated)

    def test_too_large(self) -> None:
        pack = copies_on_plate(230, 50, 220, 220, 8)
        self.assertEqual(pack.copies, 0)

    def test_single_part(self) -> None:
        pack = copies_on_plate(200, 200, 220, 220, 8)
        self.assertEqual(pack.copies, 1)


class StlBoundsTests(unittest.TestCase):
    def test_binary_cube(self) -> None:
        box = bounding_box(cube_stl(20))
        assert box is not None
        self.assertAlmostEqual(box.x_mm, 20, places=2)
        self.assertAlmostEqual(box.y_mm, 20, places=2)
        self.assertAlmostEqual(box.z_mm, 20, places=2)
        self.assertEqual(box.triangle_count, 12)

    def test_ascii_triangle(self) -> None:
        ascii_stl = b"""solid test
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 10 0 0
      vertex 0 15 5
    endloop
  endfacet
endsolid test
"""
        box = bounding_box(ascii_stl)
        assert box is not None
        self.assertAlmostEqual(box.x_mm, 10, places=2)
        self.assertAlmostEqual(box.y_mm, 15, places=2)
        self.assertAlmostEqual(box.z_mm, 5, places=2)


if __name__ == "__main__":
    unittest.main()
