package com.replaytv.scene

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.SurfaceTexture
import android.opengl.GLES11Ext.GL_TEXTURE_EXTERNAL_OES
import android.opengl.GLES20.*
import android.opengl.GLSurfaceView
import android.opengl.GLUtils
import android.os.SystemClock
import android.util.Log
import android.view.Surface
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.TimedValueQueue
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.LifecycleEventListener
import com.facebook.react.bridge.WritableMap
import com.facebook.react.uimanager.ThemedReactContext
import com.facebook.react.uimanager.UIManagerHelper
import com.facebook.react.uimanager.events.Event
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.tan

/** camera.ts EASE_MS: the time constant of the displayed camera's approach to the target. */
private const val EASE_MS = 140.0

/**
 * Fire TV renderer of a 2.5D scene package (docs/scene-format.md "How to render"): ExoPlayer
 * decodes atlas.mp4 into a SurfaceTexture (GL_TEXTURE_EXTERNAL_OES), the plates are mipmapped
 * 2D textures, every player is a billboard whose alpha comes from the mask half. The camera
 * prop is the TARGET state from JS (apps/tv/src/scene/camera.ts, the same D-pad code as the
 * web viewer); this view eases towards it like the web view, clamps it to the envelope and
 * draws.
 *
 * Frame sync: ExoPlayer reports (release time → media time) for every frame it renders and
 * the SurfaceTexture timestamp is that release time, so the sprites drawn are always those of
 * the atlas frame on the texture (ExoPlayer's own 360° renderer does the same).
 *
 * Threads: props and the player on the main thread, layout parsing and plate downloads on
 * `io`, everything GL on the GLSurfaceView thread.
 */
@SuppressLint("ViewConstructor")
@androidx.annotation.OptIn(markerClass = [UnstableApi::class])
class SceneView(private val reactContext: ThemedReactContext) :
  GLSurfaceView(reactContext), GLSurfaceView.Renderer, LifecycleEventListener {

  /** A parsed scene and its plates (bitmaps kept so a lost GL context can re-upload). */
  private class Live(val scene: Scene) {
    val bitmaps = arrayOfNulls<Bitmap>(scene.plates.size)
    val tex = IntArray(scene.plates.size)
  }

  // ---- main thread
  private var layoutJson: String? = null
  private var startTimeSec = 0.0
  private var player: ExoPlayer? = null
  private var surface: Surface? = null
  private var released = false
  private val io = Executors.newSingleThreadExecutor()

  // ---- shared
  @Volatile private var paused = true
  /** azimuth, elevation, distance, roll, fovY (degrees, metres). */
  @Volatile private var cam = doubleArrayOf(0.0, 0.0, 10.0, 0.0, 60.0)
  @Volatile private var live: Live? = null
  private val frameTimes = TimedValueQueue<Long>()
  private val frameAvailable = AtomicBoolean(false)

  // ---- GL thread
  private var plateProg: Prog? = null
  private var spriteProg: Prog? = null
  private var shapeProg: Prog? = null
  private var atlasTex = 0
  private var surfaceTexture: SurfaceTexture? = null
  private val stMatrix = FloatArray(16)
  private var frame = -1
  private var frameScene: Live? = null
  private var viewW = 1
  private var viewH = 1
  @Volatile private var readySent = false
  private var lastTimeEmitMs = 0L
  private var shown: DoubleArray? = null
  private var lastDrawMs = 0L
  private val verts =
    ByteBuffer.allocateDirect(256 * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()

  init {
    setEGLContextClientVersion(3)
    preserveEGLContextOnPause = true
    setRenderer(this)
    renderMode = RENDERMODE_WHEN_DIRTY
    reactContext.addLifecycleEventListener(this)
  }

  // ------------------------------------------------------------------ props (main thread)

  fun setLayoutJson(json: String?) {
    if (json == layoutJson) return
    layoutJson = json
    releasePlayer()
    live = null
    readySent = false
    requestRender()
    if (json.isNullOrEmpty()) return
    io.execute {
      val scene = try {
        Scene(json)
      } catch (e: Exception) {
        post { emitError("scene layout: ${e.message}") }
        return@execute
      }
      post { if (layoutJson === json) start(scene) }
    }
  }

  fun setCamera(i: Int, value: Double) {
    cam = cam.copyOf().also { it[i] = value }
    requestRender()
  }

  fun setPaused(value: Boolean) {
    if (value == paused) return
    paused = value
    val p = player ?: return
    p.playWhenReady = !value
    // FreeViewProps.onTime: also on pause (the screen resumes the angle at that time).
    if (value) emitTime(p.currentPosition / 1000.0)
  }

  /** Only seeds the atlas when a package starts, like FreeView.web.tsx. */
  fun setStartTimeSec(value: Double) {
    startTimeSec = value
  }

  private fun start(scene: Scene) {
    if (released) return
    val lv = Live(scene)
    live = lv
    frameTimes.clear()
    val p = ExoPlayer.Builder(context).build()
    p.setVideoFrameMetadataListener { presentationTimeUs, releaseTimeNs, _, _ ->
      frameTimes.add(releaseTimeNs, presentationTimeUs)
    }
    p.addListener(object : Player.Listener {
      override fun onPlayerError(error: PlaybackException) = emitError("atlas video: ${error.message}")
    })
    p.volume = 0f
    p.repeatMode = Player.REPEAT_MODE_ONE // the play loops, like the web atlas and the angles
    surface?.let { p.setVideoSurface(it) }
    // Start on a frame centre so the first frame shown is unambiguous (as on the web).
    val f0 = floor(startTimeSec * scene.fps + 1e-6).coerceIn(0.0, scene.nFrames - 1.0)
    p.setMediaItem(MediaItem.fromUri(scene.atlasUrl), ((f0 + 0.5) / scene.fps * 1000).toLong())
    p.playWhenReady = !paused
    p.prepare()
    player = p
    scene.plates.forEachIndexed { i, plate ->
      io.execute {
        val bmp = try {
          val conn = URL(plate.url).openConnection().apply {
            connectTimeout = 10_000
            readTimeout = 20_000
          }
          conn.getInputStream().use { BitmapFactory.decodeStream(it) } ?: error("not an image")
        } catch (e: Exception) {
          post { emitError("plate ${plate.url}: ${e.message}") }
          return@execute
        }
        queueEvent {
          lv.bitmaps[i] = bmp
          requestRender()
        }
      }
    }
  }

  private fun releasePlayer() {
    player?.release()
    player = null
  }

  /** Unmount (ViewManager.onDropViewInstance) or the host activity going away. */
  fun release() {
    if (released) return
    released = true
    reactContext.removeLifecycleEventListener(this)
    releasePlayer()
    io.shutdownNow()
    live = null
    surface?.release()
    surface = null
    surfaceTexture?.release()
    surfaceTexture = null
  }

  override fun onHostResume() {
    onResume()
    player?.playWhenReady = !paused
  }

  override fun onHostPause() {
    player?.playWhenReady = false
    onPause()
  }

  override fun onHostDestroy() = release()

  // ------------------------------------------------------------------ events

  private class SceneEvent(surfaceId: Int, viewId: Int, private val name: String, private val data: WritableMap) :
    Event<SceneEvent>(surfaceId, viewId) {
    override fun getEventName() = name
    override fun getEventData() = data
  }

  private fun emit(name: String, data: WritableMap = Arguments.createMap()) {
    UIManagerHelper.getEventDispatcher(reactContext)
      ?.dispatchEvent(SceneEvent(UIManagerHelper.getSurfaceId(reactContext), id, name, data))
  }

  private fun emitError(message: String) {
    Log.e("ReplayScene", message) // the Replay screen may not show onError; logcat always does
    emit("topSceneError", Arguments.createMap().apply { putString("message", message) })
  }

  private fun emitTime(sec: Double) = emit("topSceneTime", Arguments.createMap().apply { putDouble("sec", sec) })

  // ------------------------------------------------------------------ GL thread

  private inner class Prog(vert: String, frag: String) {
    val id: Int = glCreateProgram()
    private val locs = HashMap<String, Int>()

    init {
      glAttachShader(id, compile(GL_VERTEX_SHADER, vert))
      glAttachShader(id, compile(GL_FRAGMENT_SHADER, frag))
      glLinkProgram(id)
      val ok = IntArray(1)
      glGetProgramiv(id, GL_LINK_STATUS, ok, 0)
      check(ok[0] != 0) { "link $vert+$frag: ${glGetProgramInfoLog(id)}" }
    }

    private fun compile(type: Int, name: String): Int {
      val src = context.assets.open("scene/$name").bufferedReader().use { it.readText() }
      val s = glCreateShader(type)
      glShaderSource(s, src)
      glCompileShader(s)
      val ok = IntArray(1)
      glGetShaderiv(s, GL_COMPILE_STATUS, ok, 0)
      check(ok[0] != 0) { "compile $name: ${glGetShaderInfoLog(s)}" }
      return s
    }

    fun u(name: String) = locs.getOrPut(name) { glGetUniformLocation(id, name) }
    fun a(name: String) = locs.getOrPut(name) { glGetAttribLocation(id, name) }

    fun use(mvp: FloatArray) {
      glUseProgram(id)
      glUniformMatrix4fv(u("uMvp"), 1, false, mvp, 0)
    }

    /** Vertices are (x, y, z, u, v); `first`/`count` in vertices. */
    fun draw(mode: Int, v: FloatArray, first: Int = 0, count: Int = v.size / 5) {
      verts.clear()
      verts.put(v, first * 5, count * 5)
      for ((attr, size, offset) in listOf(Triple("aPos", 3, 0), Triple("aUv", 2, 3), Triple("aLocal", 2, 3))) {
        val loc = a(attr)
        if (loc < 0) continue
        verts.position(offset)
        glVertexAttribPointer(loc, size, GL_FLOAT, false, 20, verts)
        glEnableVertexAttribArray(loc)
      }
      glDrawArrays(mode, 0, count)
    }
  }

  override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
    // A new EGL context: every GL object is gone.
    try {
      plateProg = Prog("plate.vert", "plate.frag")
      spriteProg = Prog("sprite.vert", "sprite.frag")
      shapeProg = Prog("shape.vert", "shape.frag")
    } catch (e: Exception) {
      plateProg = null
      post { emitError("shaders: ${e.message}") }
      return
    }
    live?.tex?.fill(0)
    frameScene?.tex?.fill(0)
    val t = IntArray(1)
    glGenTextures(1, t, 0)
    atlasTex = t[0]
    glBindTexture(GL_TEXTURE_EXTERNAL_OES, atlasTex)
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_EXTERNAL_OES, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    val st = SurfaceTexture(atlasTex)
    st.setOnFrameAvailableListener {
      frameAvailable.set(true)
      requestRender()
    }
    val old = surfaceTexture
    surfaceTexture = st
    post {
      if (released) {
        st.release()
        return@post
      }
      val s = Surface(st)
      player?.setVideoSurface(s)
      surface?.release()
      surface = s
      old?.release()
    }
  }

  override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
    viewW = maxOf(width, 1)
    viewH = maxOf(height, 1)
    glViewport(0, 0, viewW, viewH)
  }

  override fun onDrawFrame(gl: GL10?) {
    // 1. Background (contract: any dark colour; Tier B's gradient mid-tone).
    glClearColor(0.063f, 0.075f, 0.094f, 1f)
    glClear(GL_COLOR_BUFFER_BIT)
    val lv = live
    val plate = plateProg
    val sprite = spriteProg
    val shape = shapeProg
    val st = surfaceTexture
    if (lv == null || plate == null || sprite == null || shape == null || st == null) return
    val sc = lv.scene
    if (frameScene !== lv) {
      frameScene?.tex?.let { glDeleteTextures(it.size, it, 0) }
      frameScene = lv
      frame = -1
    }
    if (frameAvailable.getAndSet(false)) {
      st.updateTexImage()
      st.getTransformMatrix(stMatrix)
      frameTimes.pollFloor(st.timestamp)?.let { onFrameShown(sc, SceneMath.frameIndex(it, sc.fps, sc.nFrames)) }
    }

    val c = ease()
    val view = SceneMath.orbit(
      sc.target, sc.azimuth0,
      c[0].coerceIn(sc.azimuthRange[0], sc.azimuthRange[1]),
      c[1].coerceIn(sc.elevationRange[0], sc.elevationRange[1]),
      c[2].coerceIn(sc.distanceRange[0], sc.distanceRange[1]),
      c[3],
    )
    val mvp = SceneMath.viewProj(view, c[4], viewW.toDouble() / viewH, 0.1, 500.0)
    val px = viewH / 1080f // line widths as in the reference renderer at 1080p

    glDisable(GL_DEPTH_TEST) // painter's order (contract step 1)
    glEnable(GL_BLEND)
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA) // everything is premultiplied

    // 2. Backdrop, then floor.
    plate.use(mvp)
    glActiveTexture(GL_TEXTURE0)
    glUniform1i(plate.u("uTex"), 0)
    sc.plates.forEachIndexed { i, p ->
      if (lv.tex[i] == 0) lv.bitmaps[i]?.let { lv.tex[i] = upload(it) }
      if (lv.tex[i] != 0) {
        glBindTexture(GL_TEXTURE_2D, lv.tex[i])
        plate.draw(GL_TRIANGLE_FAN, p.verts)
      }
    }
    if (frame < 0) return // no atlas frame decoded yet
    val feet = sc.feet[frame]
    val n = feet.size / 2

    // 3. Contact shadows.
    shape.use(mvp)
    glUniform1f(shape.u("uPointScale"), 0f)
    glUniform1f(shape.u("uMode"), 1f)
    glUniform4f(shape.u("uColor"), 0f, 0f, 0f, 0.45f)
    val e = 1.6f // radius + 3 sigma, in radii
    val r = (sc.shadowRadius * e).toFloat()
    for (i in 0 until n) {
      val x = feet[i * 2]
      val y = feet[i * 2 + 1]
      shape.draw(
        GL_TRIANGLE_FAN,
        floatArrayOf(x - r, y - r, 0f, -e, -e, x + r, y - r, 0f, e, -e, x + r, y + r, 0f, e, e, x - r, y + r, 0f, -e, e),
      )
    }

    // 4. Hoops: translucent backboard with an outline, then the rim.
    glUniform1f(shape.u("uMode"), 0f)
    for (h in sc.hoops) {
      glUniform4f(shape.u("uColor"), 0.92f, 0.92f, 0.92f, 0.35f)
      shape.draw(GL_TRIANGLE_FAN, h.board)
      glLineWidth(2 * px)
      glUniform4f(shape.u("uColor"), 0.98f, 0.98f, 0.98f, 1f)
      shape.draw(GL_LINE_LOOP, h.board)
      glLineWidth(3 * px)
      glUniform4f(shape.u("uColor"), 1f, 0.35f, 0f, 1f)
      shape.draw(GL_LINE_LOOP, h.rim)
    }

    // 5. Players back to front by the view depth of the chest point; the net in between.
    val depth = DoubleArray(n) { SceneMath.depth(view, feet[it * 2].toDouble(), feet[it * 2 + 1].toDouble(), 0.9) }
    val net = sc.net
    val netDepth = net?.let {
      SceneMath.depth(view, (it[0] + it[3]) / 2.0, (it[1] + it[4]) / 2.0, (it[2] + it[5]) / 2.0)
    }
    var netDrawn = net == null
    glActiveTexture(GL_TEXTURE1)
    glBindTexture(GL_TEXTURE_EXTERNAL_OES, atlasTex)
    sprite.use(mvp)
    glUniform1i(sprite.u("uAtlas"), 1)
    glUniformMatrix4fv(sprite.u("uSt"), 1, false, stMatrix, 0)
    glUniform1f(sprite.u("uMaskOffsetU"), sc.maskOffsetU)
    glUniform2f(sprite.u("uRamp"), sc.maskRamp[0], sc.maskRamp[1])
    for (i in (0 until n).sortedByDescending { depth[it] }) {
      if (!netDrawn && depth[i] <= netDepth!!) {
        drawNet(shape, mvp, net!!, px)
        netDrawn = true
        sprite.use(mvp)
      }
      sprite.draw(GL_TRIANGLE_FAN, sc.sprites[frame], i * 4, 4)
    }
    if (!netDrawn) drawNet(shape, mvp, net!!, px)

    // 6. The modelled ball (a disc; size follows depth).
    sc.ball?.getOrNull(frame)?.let { b ->
      shape.use(mvp)
      val focalPx = viewH / 2.0 / tan(Math.toRadians(c[4]) / 2)
      glUniform1f(shape.u("uPointScale"), (2 * focalPx * sc.ballRadius).toFloat())
      glUniform1f(shape.u("uMode"), 2f)
      glUniform4f(shape.u("uColor"), 0.92f, 0.43f, 0.12f, 1f)
      shape.draw(GL_POINTS, floatArrayOf(b[0], b[1], b[2], 0f, 0f))
    }
  }

  /** Tier B's net: a translucent band `depth` deep below the top line, the top line, posts. */
  private fun drawNet(shape: Prog, mvp: FloatArray, net: FloatArray, px: Float) {
    val (lx, ly, h) = Triple(net[0], net[1], net[2])
    val (rx, ry, d) = Triple(net[3], net[4], net[6])
    shape.use(mvp)
    glUniform1f(shape.u("uMode"), 0f)
    glUniform4f(shape.u("uColor"), 0.16f, 0.16f, 0.16f, 0.3f)
    shape.draw(GL_TRIANGLE_FAN, floatArrayOf(lx, ly, h, 0f, 0f, rx, ry, h, 0f, 0f, rx, ry, h - d, 0f, 0f, lx, ly, h - d, 0f, 0f))
    glLineWidth(3 * px)
    glUniform4f(shape.u("uColor"), 0.96f, 0.96f, 0.96f, 1f)
    shape.draw(GL_LINES, floatArrayOf(lx, ly, h, 0f, 0f, rx, ry, h, 0f, 0f))
    glLineWidth(4 * px)
    glUniform4f(shape.u("uColor"), 0.24f, 0.24f, 0.24f, 1f)
    shape.draw(GL_LINES, floatArrayOf(lx, ly, 0f, 0f, 0f, lx, ly, h + 0.05f, 0f, 0f, rx, ry, 0f, 0f, 0f, rx, ry, h + 0.05f, 0f, 0f))
  }

  /**
   * The displayed camera eases towards the prop (the target) exactly like camera.ts's
   * easeCamera: every field on one exponential with EASE_MS, snapping when all are within
   * 1e-3. Keeps rendering until it has settled.
   */
  private fun ease(): DoubleArray {
    val target = cam
    val now = SystemClock.uptimeMillis()
    // A dirty-mode view may have idled for seconds: cap the step to a few frames.
    val dt = (now - lastDrawMs).coerceIn(0L, 50L).toDouble()
    lastDrawMs = now
    val cur = shown ?: target
    val k = 1 - exp(-dt / EASE_MS)
    var far = false
    val next = DoubleArray(5) { i ->
      val d = target[i] - cur[i]
      if (abs(d) > 1e-3) far = true
      cur[i] + d * k
    }
    shown = if (far) next else target
    if (far) requestRender()
    return shown!!
  }

  private fun upload(bmp: Bitmap): Int {
    val t = IntArray(1)
    glGenTextures(1, t, 0)
    glBindTexture(GL_TEXTURE_2D, t[0])
    GLUtils.texImage2D(GL_TEXTURE_2D, 0, bmp, 0) // premultiplied, row 0 at t = 0
    glGenerateMipmap(GL_TEXTURE_2D) // ES 3: NPOT mipmaps are core
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    return t[0]
  }

  private fun onFrameShown(sc: Scene, f: Int) {
    frame = f
    if (!readySent) {
      readySent = true
      post { emit("topSceneReady") }
    }
    val now = SystemClock.uptimeMillis()
    // ~10 Hz while playing (like react-native-video's progress), every frame shown while paused (seeks).
    if (paused || now - lastTimeEmitMs >= 100) {
      lastTimeEmitMs = now
      val sec = f / sc.fps
      post { emitTime(sec) }
    }
  }
}
