package com.replaytv.scene

import kotlin.math.cos
import kotlin.math.roundToLong
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

/**
 * The scene package's geometry (docs/scene-format.md): orbit camera, GL matrices, billboards,
 * atlas frame index. Pure Kotlin, no android.*, so apps/tv/android/scene-check.sh can run it
 * on a JVM against the reference values.
 */
object SceneMath {
  /** OpenCV-convention camera: rows of [r] are right, down, forward; x_cam = r·(X − eye). */
  class Camera(val eye: DoubleArray, val r: Array<DoubleArray>)

  /** "Camera envelope and presets": a state (degrees, metres) orbiting `target`. */
  fun orbit(
    target: DoubleArray,
    azimuth0Deg: Double,
    azimuthDeg: Double,
    elevationDeg: Double,
    distanceM: Double,
    rollDeg: Double,
  ): Camera {
    val az = Math.toRadians(azimuth0Deg + azimuthDeg)
    val el = Math.toRadians(elevationDeg)
    val eye = doubleArrayOf(
      target[0] + distanceM * cos(el) * cos(az),
      target[1] + distanceM * cos(el) * sin(az),
      target[2] + distanceM * sin(el),
    )
    val fwd = norm(DoubleArray(3) { target[it] - eye[it] })
    val right = norm(cross(fwd, doubleArrayOf(0.0, 0.0, 1.0)))
    val down = cross(fwd, right)
    val c = cos(Math.toRadians(rollDeg))
    val s = sin(Math.toRadians(rollDeg))
    // R = Rz(roll) · R0
    val r = arrayOf(
      DoubleArray(3) { c * right[it] - s * down[it] },
      DoubleArray(3) { s * right[it] + c * down[it] },
      fwd,
    )
    return Camera(eye, r)
  }

  /** Column-major GL MVP: perspective(fovY, aspect) · diag(1, −1, −1, 1) · [R | −R·eye]. */
  fun viewProj(cam: Camera, fovYDeg: Double, aspect: Double, near: Double, far: Double): FloatArray {
    val f = 1.0 / tan(Math.toRadians(fovYDeg) / 2)
    val sign = doubleArrayOf(1.0, -1.0, -1.0)
    // view rows (GL camera: x right, y up, looking down −z)
    val v = Array(3) { i ->
      val row = cam.r[i]
      doubleArrayOf(
        sign[i] * row[0], sign[i] * row[1], sign[i] * row[2],
        -sign[i] * (row[0] * cam.eye[0] + row[1] * cam.eye[1] + row[2] * cam.eye[2]),
      )
    }
    val p = arrayOf(
      doubleArrayOf(f / aspect, 0.0, 0.0, 0.0),
      doubleArrayOf(0.0, f, 0.0, 0.0),
      doubleArrayOf(0.0, 0.0, (far + near) / (near - far), 2 * far * near / (near - far)),
      doubleArrayOf(0.0, 0.0, -1.0, 0.0),
    )
    val out = FloatArray(16)
    for (row in 0 until 4) for (col in 0 until 4) {
      var acc = p[row][3] * if (col == 3) 1.0 else 0.0
      for (k in 0 until 3) acc += p[row][k] * v[k][col]
      out[col * 4 + row] = acc.toFloat()
    }
    return out
  }

  /** Distance along the view axis (the painter's sort key). */
  fun depth(cam: Camera, x: Double, y: Double, z: Double): Double =
    cam.r[2][0] * (x - cam.eye[0]) + cam.r[2][1] * (y - cam.eye[1]) + cam.r[2][2] * (z - cam.eye[2])

  /**
   * "Billboards": the vertical card at foot (fx, fy) facing `c` (the real camera for
   * `facing: real`), as 4 vertices × (x, y, z, u, v) in the order (s0,z1) (s1,z1) (s1,z0) (s0,z0).
   */
  fun billboard(fx: Double, fy: Double, rect: DoubleArray, uv: DoubleArray, c: DoubleArray): FloatArray {
    val dx = fx - c[0]
    val dy = fy - c[1]
    val n = sqrt(dx * dx + dy * dy)
    val ax = dy / n
    val ay = -dx / n
    val (s0, z0, s1, z1) = rect.toList()
    val (u0, v0, u1, v1) = uv.toList()
    fun corner(s: Double, z: Double, u: Double, v: Double) =
      floatArrayOf((fx + s * ax).toFloat(), (fy + s * ay).toFloat(), z.toFloat(), u.toFloat(), v.toFloat())
    return corner(s0, z1, u0, v0) + corner(s1, z1, u1, v0) + corner(s1, z0, u1, v1) + corner(s0, z0, u0, v1)
  }

  /** Atlas frame of a decoded presentation time ("Time": frame f is at f / fps). Rounded, not
   *  floored: decoded timestamps are the exact frame times and 1/30 s is not exact in µs. */
  fun frameIndex(ptsUs: Long, fps: Double, nFrames: Int): Int =
    (ptsUs * fps / 1e6).roundToLong().coerceIn(0L, (nFrames - 1).toLong()).toInt()

  private fun cross(a: DoubleArray, b: DoubleArray) =
    doubleArrayOf(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

  private fun norm(a: DoubleArray): DoubleArray {
    val n = sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    return DoubleArray(3) { a[it] / n }
  }
}
