package com.replaytv.scene

import kotlin.math.abs
import kotlin.math.hypot

// Run by apps/tv/android/scene-check.sh (plain JVM: the offline Gradle cache has no JUnit).
// Reference values: services/api/fixtures/scene_synth/layout.json (SYNTHETIC fixture).

private var failures = 0

private fun check(name: String, ok: Boolean, detail: String = "") {
  println((if (ok) "ok   " else "FAIL ") + name + (if (detail.isEmpty()) "" else "  ($detail)"))
  if (!ok) failures++
}

fun main() {
  val target = doubleArrayOf(1.6692, 14.0, -1.0944)
  val realPos = doubleArrayOf(12.7502, 14.0, 6.0)
  val realR = arrayOf(
    doubleArrayOf(-9e-08, 1.0, 2e-07),
    doubleArrayOf(0.53919508, 2.2e-07, -0.8421809),
    doubleArrayOf(-0.8421809, 3e-08, -0.53919508),
  )
  val realT = doubleArrayOf(-13.999995, -1.821736, 13.973167)
  val fx = 219.779
  val (w, h) = 1280.0 to 720.0

  // 1. The `real` preset (az 0, el 32.63, d 13.157, roll 0) is the real camera.
  val cam = SceneMath.orbit(target, -0.0, 0.0, 32.63, 13.157, 0.0)
  val eyeErr = (0..2).maxOf { abs(cam.eye[it] - realPos[it]) }
  check("real preset eye = camera.position_m", eyeErr < 0.02, "max err %.4f m".format(eyeErr))
  val rErr = (0..2).maxOf { i -> (0..2).maxOf { j -> abs(cam.r[i][j] - realR[i][j]) } }
  check("real preset R = camera.R", rErr < 2e-3, "max err %.5f".format(rErr))

  // 2. MVP at the source size projects like K·(R·X + t) (the reference renderer's real view).
  val mvp = SceneMath.viewProj(cam, 117.192, w / h, 0.1, 500.0)
  var pxErr = 0.0
  for (p in listOf(doubleArrayOf(-3.904, 3.143, 0.0), doubleArrayOf(0.0, 26.425, 3.05), doubleArrayOf(5.0, 20.0, 1.0))) {
    val c = DoubleArray(4) { row -> (0..2).sumOf { k -> mvp[k * 4 + row] * p[k] } + mvp[12 + row] }
    val gx = (c[0] / c[3] + 1) / 2 * w
    val gy = (1 - c[1] / c[3]) / 2 * h
    val xc = DoubleArray(3) { i -> (0..2).sumOf { k -> realR[i][k] * p[k] } + realT[i] }
    val kx = fx * xc[0] / xc[2] + 640.0
    val ky = fx * xc[1] / xc[2] + 360.0
    pxErr = maxOf(pxErr, hypot(gx - kx, gy - ky))
  }
  check("GL projection = K(RX+t)", pxErr < 1.0, "max err %.3f px".format(pxErr))

  // 3. Billboard of frame 13's first sprite: vertical, facing the real camera, uv corners.
  val rect = doubleArrayOf(-0.7397, -0.3716, 1.5502, 2.3382)
  val uv = doubleArrayOf(0.001563, 0.429688, 0.048438, 0.984375)
  val b = SceneMath.billboard(-3.904, 3.143, rect, uv, realPos)
  val ax = (b[5] - b[0]).toDouble() / (rect[2] - rect[0])
  val ay = (b[6] - b[1]).toDouble() / (rect[2] - rect[0])
  val dx = -3.904 - realPos[0]
  val dy = 3.143 - realPos[1]
  check("billboard axis is unit and faces the camera", abs(hypot(ax, ay) - 1) < 1e-4 && abs(ax * dx + ay * dy) < 1e-3)
  // Same side as the camera's right (not equal: this player is ~33° off the optical axis).
  check("billboard axis points to the camera's right", ax * cam.r[0][0] + ay * cam.r[0][1] > 0.5)
  check(
    "billboard corners z and uv",
    b[2] == rect[3].toFloat() && b[17] == rect[1].toFloat() && b[3] == uv[0].toFloat() && b[4] == uv[1].toFloat() &&
      b[13] == uv[2].toFloat() && b[14] == uv[3].toFloat(),
  )

  // 4. Orbit moves the eye on the sphere, roll keeps the forward axis.
  val left = SceneMath.orbit(target, -0.0, -15.2, 36.77, 13.157, 5.0)
  val dist = hypot(hypot(left.eye[0] - target[0], left.eye[1] - target[1]), left.eye[2] - target[2])
  check("orbit keeps the distance", abs(dist - 13.157) < 1e-9)
  val noRoll = SceneMath.orbit(target, -0.0, -15.2, 36.77, 13.157, 0.0)
  check("roll keeps forward", (0..2).all { abs(left.r[2][it] - noRoll.r[2][it]) < 1e-12 })

  // 5. Frame index from decoded pts (30 fps, 45 frames).
  check("pts 0 -> frame 0", SceneMath.frameIndex(0, 30.0, 45) == 0)
  check("pts 33333 us -> frame 1", SceneMath.frameIndex(33_333, 30.0, 45) == 1)
  check("pts 433333 us -> frame 13", SceneMath.frameIndex(433_333, 30.0, 45) == 13)
  check("past the end clamps", SceneMath.frameIndex(9_000_000, 30.0, 45) == 44)

  println(if (failures == 0) "SCENE MATH OK" else "SCENE MATH: $failures FAILED")
  if (failures != 0) kotlin.system.exitProcess(1)
}
