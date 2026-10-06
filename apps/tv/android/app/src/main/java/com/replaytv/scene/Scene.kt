package com.replaytv.scene

import org.json.JSONArray
import org.json.JSONObject

/**
 * The parts of a `replay.scene_package.v1` layout (docs/scene-format.md) the GL view draws,
 * flattened into float arrays once. `json` is GET /games/{id}/scenes/{play_id} (absolute
 * `url` next to every file).
 */
class Scene(json: String) {
  class Plate(val url: String, val verts: FloatArray)
  class Hoop(val rim: FloatArray, val board: FloatArray)

  val fps: Double
  val nFrames: Int
  val target: DoubleArray
  val azimuth0: Double
  val azimuthRange: DoubleArray
  val elevationRange: DoubleArray
  val distanceRange: DoubleArray
  val plates: List<Plate>
  val atlasUrl: String
  val maskOffsetU: Float
  val maskRamp: FloatArray
  val shadowRadius: Double
  /** Per frame: the billboards, 20 floats each (SceneMath.billboard). */
  val sprites: Array<FloatArray>
  /** Per frame: the foot points, 2 floats each (same order as [sprites]). */
  val feet: Array<FloatArray>
  val hoops: List<Hoop>
  /** Net: [top_l, top_r] xyz and depth, or null. */
  val net: FloatArray?
  val ball: Array<FloatArray?>?
  val ballRadius: Double

  init {
    val o = JSONObject(json)
    require(o.getString("schema") == "replay.scene_package.v1") { "unsupported scene schema ${o.getString("schema")}" }
    fps = o.getDouble("fps")
    nFrames = o.getInt("n_frames")
    val env = o.getJSONObject("envelope")
    target = doubles(env.getJSONArray("target_m"))
    azimuth0 = env.getDouble("azimuth0_deg")
    azimuthRange = doubles(env.getJSONArray("azimuth_deg"))
    elevationRange = doubles(env.getJSONArray("elevation_deg"))
    distanceRange = doubles(env.getJSONArray("distance_m"))

    val plateUv = floatArrayOf(0f, 0f, 1f, 0f, 1f, 1f, 0f, 1f)
    val ps = o.getJSONArray("plates")
    plates = (0 until ps.length()).map { i ->
      val p = ps.getJSONObject(i)
      val corners = p.getJSONArray("corners_m")
      val v = FloatArray(20)
      for (k in 0 until 4) {
        val c = doubles(corners.getJSONArray(k))
        for (j in 0 until 3) v[k * 5 + j] = c[j].toFloat()
        v[k * 5 + 3] = plateUv[k * 2]
        v[k * 5 + 4] = plateUv[k * 2 + 1]
      }
      Plate(p.getString("url"), v)
    }

    val atlas = o.getJSONObject("atlas")
    atlasUrl = atlas.getString("url")
    maskOffsetU = atlas.getDouble("mask_offset_u").toFloat()
    maskRamp = doubles(atlas.getJSONArray("mask_ramp")).map { it.toFloat() }.toFloatArray()

    shadowRadius = o.getJSONObject("billboard").getDouble("shadow_radius_m")
    // v1 packages face the real camera; the contract recommends `real` for any package.
    val realCam = doubles(o.getJSONObject("camera").getJSONArray("position_m"))
    val frames = o.getJSONArray("frames")
    sprites = Array(frames.length()) { FloatArray(0) }
    feet = Array(frames.length()) { FloatArray(0) }
    for (f in 0 until frames.length()) {
      val list = frames.getJSONArray(f)
      val s = FloatArray(list.length() * 20)
      val ft = FloatArray(list.length() * 2)
      for (i in 0 until list.length()) {
        val it = list.getJSONObject(i)
        val foot = doubles(it.getJSONArray("foot"))
        SceneMath.billboard(foot[0], foot[1], doubles(it.getJSONArray("rect")), doubles(it.getJSONArray("uv")), realCam)
          .copyInto(s, i * 20)
        ft[i * 2] = foot[0].toFloat()
        ft[i * 2 + 1] = foot[1].toFloat()
      }
      sprites[f] = s
      feet[f] = ft
    }

    val st = o.getJSONObject("static")
    val hs = st.getJSONArray("hoops")
    hoops = (0 until hs.length()).map { i ->
      val hp = hs.getJSONObject(i)
      val c = doubles(hp.getJSONArray("rim_m"))
      val r = hp.getDouble("rim_radius_m")
      val ring = FloatArray(32 * 5)
      for (k in 0 until 32) {
        val a = 2 * Math.PI * k / 32
        ring[k * 5] = (c[0] + r * Math.cos(a)).toFloat()
        ring[k * 5 + 1] = (c[1] + r * Math.sin(a)).toFloat()
        ring[k * 5 + 2] = c[2].toFloat()
      }
      val bq = hp.getJSONArray("backboard_m")
      val board = FloatArray(20)
      for (k in 0 until 4) doubles(bq.getJSONArray(k)).forEachIndexed { j, x -> board[k * 5 + j] = x.toFloat() }
      Hoop(ring, board)
    }
    net = st.optJSONObject("net")?.let { n ->
      (doubles(n.getJSONArray("top_l_m")) + doubles(n.getJSONArray("top_r_m")) + n.getDouble("depth_m"))
        .map { it.toFloat() }.toFloatArray()
    }
    val b = o.optJSONObject("ball")
    ballRadius = b?.optDouble("radius_m", 0.12) ?: 0.12
    ball = b?.getJSONArray("xyz")?.let { xyz ->
      Array(xyz.length()) { f -> xyz.optJSONArray(f)?.let { p -> doubles(p).map { it.toFloat() }.toFloatArray() } }
    }
  }

  private fun doubles(a: JSONArray) = DoubleArray(a.length()) { a.getDouble(it) }
}
