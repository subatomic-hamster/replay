// Free view (2.5D), web renderer: the replay.scene_package.v1 scene (docs/scene-format.md,
// "How to render") drawn live with raw WebGL2 — no three.js: the scene is ~30 textured or
// flat quads per frame, raw GL blends in the same 8-bit sRGB space as the CPU reference
// renderer (render/replay_render/virtual/scene.py), and the shaders are the GLSL the Fire
// TV view uses. The atlas is a hidden <video>; each presented frame (requestVideoFrameCallback)
// is uploaded with its media time, so the sprites of frames[f] always match the texture.
// Status for tests and the fps readout goes on the container's data-* attributes.
import { useEffect, useLayoutEffect, useRef } from "react";
import type { SceneLayout, Vec3 } from "../../../../packages/tv-core/src/types";
import {
  billboardAxis,
  easeCamera,
  sameCamera,
  viewProjection,
  type CameraState,
  type FreeViewProps,
} from "./camera";

const NEAR_M = 0.3;
const BG_TOP = [22 / 255, 26 / 255, 34 / 255, 1];
const BG_BOTTOM = [9 / 255, 10 / 255, 12 / 255, 1];
const rgb = (r: number, g: number, b: number, a = 1) => [r / 255, g / 255, b / 255, a];

const VS = `#version 300 es
in vec3 aPos;
in vec2 aUv;
uniform mat4 uM;
out vec2 vUv;
void main() { vUv = aUv; gl_Position = uM * vec4(aPos, 1.0); }`;

// uMode: 0 RGBA texture (plates), 1 atlas (colour × ramped mask alpha), 2 flat colour,
// 3 contact shadow (uv = metres from the foot; uColor = r, sigma, -, alpha), 4 gradient.
const FS = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uTex;
uniform int uMode;
uniform vec4 uColor;
uniform vec4 uColor2;
uniform vec3 uMask;
out vec4 o;
void main() {
  if (uMode == 0) o = texture(uTex, vUv);
  else if (uMode == 1) {
    vec3 c = texture(uTex, vUv).rgb;
    float m = texture(uTex, vUv + vec2(uMask.x, 0.0)).g;
    o = vec4(c, clamp((m - uMask.y) / (uMask.z - uMask.y), 0.0, 1.0));
  } else if (uMode == 2) o = uColor;
  else if (uMode == 3) o = vec4(0.0, 0.0, 0.0, uColor.w / (1.0 + exp(1.702 * (length(vUv) - uColor.x) / uColor.y)));
  else o = mix(uColor, uColor2, vUv.y);
}`;

const IDENTITY = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);

interface Draw {
  first: number;
  count: number;
  mode: number;
  world: boolean;
  tex?: WebGLTexture | null;
  color?: number[];
  color2?: number[];
}

export function FreeView({ layout, camera, paused, startTimeSec, onTime, onReady, onError }: FreeViewProps) {
  const holder = useRef<HTMLDivElement>(null);
  const live = useRef({ camera, paused, onTime, onReady, onError });
  const video = useRef<HTMLVideoElement | null>(null);

  // Layout effect: a new target marks the view unsettled in the same task as the commit
  // that changed it, so a reader of data-settled never sees the previous target's "true".
  useLayoutEffect(() => {
    if (!sameCamera(live.current.camera, camera) && holder.current) holder.current.dataset.settled = "false";
    live.current = { camera, paused, onTime, onReady, onError };
  });

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    if (paused) {
      v.pause();
      live.current.onTime?.(v.currentTime);
    } else v.play().catch(() => undefined);
  }, [paused]);

  // One GL context, textures and atlas video per package. startTimeSec is read once.
  useEffect(() => {
    const root = holder.current;
    if (!root) return;
    const canvas = document.createElement("canvas");
    canvas.dataset.testid = "scene-canvas";
    canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;display:block";
    root.appendChild(canvas);
    const fail = (msg: string) => {
      root.dataset.error = msg;
      live.current.onError?.(msg);
    };
    const gl = canvas.getContext("webgl2", { alpha: false, antialias: true, premultipliedAlpha: false });
    if (!gl) {
      fail("WebGL2 is not available");
      return () => canvas.remove();
    }
    const prog = program(gl);
    if (typeof prog === "string") {
      fail(prog);
      return () => canvas.remove();
    }
    const loc = {
      m: gl.getUniformLocation(prog, "uM"),
      mode: gl.getUniformLocation(prog, "uMode"),
      color: gl.getUniformLocation(prog, "uColor"),
      color2: gl.getUniformLocation(prog, "uColor2"),
      mask: gl.getUniformLocation(prog, "uMask"),
    };
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    const aPos = gl.getAttribLocation(prog, "aPos");
    const aUv = gl.getAttribLocation(prog, "aUv");
    gl.enableVertexAttribArray(aPos);
    gl.enableVertexAttribArray(aUv);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 20, 0);
    gl.vertexAttribPointer(aUv, 2, gl.FLOAT, false, 20, 12);
    gl.useProgram(prog);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);

    let disposed = false;
    let dirty = true;
    const loaded = new Set<WebGLTexture | null>();
    let pending = layout.plates.length + 1;
    const ready = () => {
      if (--pending === 0 && !disposed) {
        root.dataset.ready = "true";
        live.current.onReady?.();
      }
    };

    // Plates: RGBA PNGs, mipmapped (the floor is minified a lot at grazing angles).
    const plates = layout.plates.map((p) => {
      const tex = gl.createTexture();
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        if (disposed) return;
        gl.bindTexture(gl.TEXTURE_2D, tex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        gl.generateMipmap(gl.TEXTURE_2D);
        texParams(gl, gl.LINEAR_MIPMAP_LINEAR);
        loaded.add(tex);
        dirty = true;
        ready();
      };
      img.onerror = () => fail(`plate ${p.file} failed to load`);
      img.src = p.url ?? p.file;
      return { tex, corners: p.corners_m };
    });

    // Atlas: a hidden, attached <video> (a detached one is not presented, so no frame callbacks).
    const atlasTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, atlasTex);
    texParams(gl, gl.LINEAR);
    const v = document.createElement("video");
    v.dataset.testid = "scene-atlas";
    v.style.cssText = "position:absolute;left:0;top:0;width:2px;height:2px;opacity:0;pointer-events:none";
    v.crossOrigin = "anonymous";
    v.muted = true;
    v.loop = true;
    v.playsInline = true;
    v.preload = "auto";
    root.appendChild(v);
    video.current = v;
    const lastFrame = layout.n_frames - 1;
    let atlasFrame = -1;
    const upload = (mediaTime: number) => {
      gl.bindTexture(gl.TEXTURE_2D, atlasTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, v);
      atlasFrame = Math.min(lastFrame, Math.max(0, Math.round(mediaTime * layout.fps)));
      dirty = true;
    };
    const rvfc = typeof v.requestVideoFrameCallback === "function";
    const onFrame = (_now: number, meta: VideoFrameCallbackMetadata) => {
      if (disposed) return;
      upload(meta.mediaTime);
      v.requestVideoFrameCallback(onFrame);
    };
    if (rvfc) v.requestVideoFrameCallback(onFrame);
    v.addEventListener("loadeddata", ready, { once: true });
    v.addEventListener("error", () => fail(v.error?.message || "atlas video failed"));
    v.addEventListener("loadedmetadata", () => {
      // Land on a frame centre so the presented frame is unambiguous.
      const t = Math.min(Math.max(0, startTimeSec ?? 0), lastFrame / layout.fps);
      v.currentTime = (Math.floor(t * layout.fps + 1e-6) + 0.5) / layout.fps;
      if (!live.current.paused) v.play().catch(() => undefined);
    }, { once: true });
    v.src = layout.atlas.url ?? layout.atlas.file;

    // Render loop: every animation frame while the camera moves or a new atlas frame
    // arrived (or the size changed); idle otherwise.
    let shown: CameraState = live.current.camera;
    let last = performance.now();
    let fpsT0 = last;
    let fpsN = 0;
    let drawMs = 0;
    let timeT0 = last;
    let raf = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const dt = now - last;
      last = now;
      const target = live.current.camera;
      const moving = !sameCamera(shown, target);
      if (moving) shown = easeCamera(shown, target, dt);
      const s = sameCamera(shown, target) ? "true" : "false";
      if (s !== root.dataset.settled) root.dataset.settled = s;
      if (!rvfc && v.readyState >= 2) upload(v.currentTime);
      const w = Math.round(canvas.clientWidth * devicePixelRatio);
      const h = Math.round(canvas.clientHeight * devicePixelRatio);
      if (w && h && (canvas.width !== w || canvas.height !== h)) {
        canvas.width = w;
        canvas.height = h;
        dirty = true;
      }
      if (moving || dirty) {
        dirty = false;
        const t0 = performance.now();
        draw(gl, loc, layout, shown, Math.max(0, atlasFrame), canvas.width, canvas.height, plates, loaded, atlasFrame >= 0 ? atlasTex : null);
        drawMs += performance.now() - t0;
        fpsN++;
        root.dataset.frame = String(atlasFrame);
      }
      // Draws per second (= the display rate while the camera moves) and the mean JS+GL
      // submit time per draw (GPU work is asynchronous and not in it).
      if (now - fpsT0 >= 1000) {
        root.dataset.fps = String(Math.round((fpsN * 1000) / (now - fpsT0)));
        root.dataset.drawMs = fpsN ? (drawMs / fpsN).toFixed(2) : "0";
        fpsN = 0;
        drawMs = 0;
        fpsT0 = now;
      }
      const ts = v.currentTime.toFixed(3);
      if (ts !== root.dataset.time) root.dataset.time = ts;
      if (now - timeT0 >= 250) {
        timeT0 = now;
        if (!v.paused) live.current.onTime?.(v.currentTime);
      }
    };
    raf = requestAnimationFrame(tick);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      live.current.onTime?.(v.currentTime);
      v.pause();
      v.removeAttribute("src");
      v.load();
      v.remove();
      video.current = null;
      for (const p of plates) gl.deleteTexture(p.tex);
      gl.deleteTexture(atlasTex);
      gl.deleteBuffer(buf);
      gl.deleteProgram(prog);
      canvas.remove();
      delete root.dataset.ready;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- startTimeSec only seeds the atlas
  }, [layout]);

  return <div ref={holder} data-testid="free-view" style={{ position: "absolute", inset: 0, overflow: "hidden" }} />;
}

function texParams(gl: WebGL2RenderingContext, min: number) {
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, min);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
}

function program(gl: WebGL2RenderingContext): WebGLProgram | string {
  const p = gl.createProgram();
  for (const [type, src] of [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, FS]] as const) {
    const s = gl.createShader(type);
    if (!s) return "shader: createShader failed";
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) return `shader: ${gl.getShaderInfoLog(s)}`;
    gl.attachShader(p, s);
  }
  gl.linkProgram(p);
  return gl.getProgramParameter(p, gl.LINK_STATUS) ? p : `link: ${gl.getProgramInfoLog(p)}`;
}

/** One frame in painter's order (docs/scene-format.md "How to render", steps 1–6). */
function draw(
  gl: WebGL2RenderingContext,
  loc: Record<"m" | "mode" | "color" | "color2" | "mask", WebGLUniformLocation | null>,
  lay: SceneLayout,
  cam: CameraState,
  f: number,
  W: number,
  H: number,
  plates: { tex: WebGLTexture | null; corners: [Vec3, Vec3, Vec3, Vec3] }[],
  loaded: Set<WebGLTexture | null>,
  atlas: WebGLTexture | null,
) {
  const vp = viewProjection(cam, lay, W, H);
  const lw = devicePixelRatio; // line widths are in CSS px, like the reference's px at 1080p
  const verts: number[] = [];
  const draws: Draw[] = [];
  const push = (d: Omit<Draw, "first" | "count">, pts: number[]) => {
    draws.push({ ...d, first: verts.length / 5, count: pts.length / 5 });
    for (const x of pts) verts.push(x);
  };
  const quad = (c: Vec3[], uv: number[][]) =>
    [0, 1, 2, 0, 2, 3].flatMap((i) => [...c[i], ...uv[i]]);
  const UV = [[0, 0], [1, 0], [1, 1], [0, 1]];
  const okDepth = (pts: Vec3[]) => pts.every((p) => vp.depth(p) > NEAR_M);
  // pixel (y down) of a world point, and a pixel → NDC vertex (u, v unused)
  const proj = (p: Vec3) => {
    const x = vp.R[0][0] * p[0] + vp.R[0][1] * p[1] + vp.R[0][2] * p[2] + vp.t[0];
    const y = vp.R[1][0] * p[0] + vp.R[1][1] * p[1] + vp.R[1][2] * p[2] + vp.t[1];
    const z = vp.depth(p);
    return [(vp.f * x) / z + W / 2, (vp.f * y) / z + H / 2];
  };
  // OpenCV pixel (centres on integers) → NDC (GL pixel centres on half-integers)
  const ndc = (x: number, y: number) => [((x + 0.5) / W) * 2 - 1, 1 - ((y + 0.5) / H) * 2, 0, 0, 0];
  const line = (px: number[][], closed: boolean, width: number, color: number[]) => {
    const out: number[] = [];
    const n = closed ? px.length : px.length - 1;
    for (let i = 0; i < n; i++) {
      const [a, b] = [px[i], px[(i + 1) % px.length]];
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const l = Math.hypot(dx, dy) || 1;
      const ox = (-dy / l) * (width / 2);
      const oy = (dx / l) * (width / 2);
      const c = [[a[0] + ox, a[1] + oy], [b[0] + ox, b[1] + oy], [b[0] - ox, b[1] - oy], [a[0] - ox, a[1] - oy]];
      for (const i2 of [0, 1, 2, 0, 2, 3]) out.push(...ndc(c[i2][0], c[i2][1]));
    }
    push({ mode: 2, world: false, color }, out);
  };
  const disc = (c: number[], r: number, color: number[]) => {
    const out: number[] = [];
    for (let i = 0; i < 24; i++) {
      const a0 = (i / 24) * 2 * Math.PI;
      const a1 = ((i + 1) / 24) * 2 * Math.PI;
      out.push(...ndc(c[0], c[1]), ...ndc(c[0] + r * Math.cos(a0), c[1] + r * Math.sin(a0)),
        ...ndc(c[0] + r * Math.cos(a1), c[1] + r * Math.sin(a1)));
    }
    push({ mode: 2, world: false, color }, out);
  };

  // 1. background gradient
  const full: Vec3[] = [[-1, 1, 0], [1, 1, 0], [1, -1, 0], [-1, -1, 0]];
  push({ mode: 4, world: false, color: BG_TOP, color2: BG_BOTTOM }, quad(full, UV));
  // 2. backdrop, then floor
  for (const p of plates) if (loaded.has(p.tex)) push({ mode: 0, world: true, tex: p.tex }, quad(p.corners, UV));
  // 3. contact shadows (r, Gaussian edge sigma ≈ r / 5, 45 % at the centre)
  const sprites = lay.frames[f] ?? [];
  const r = lay.billboard.shadow_radius_m;
  const ext = r + 3 * (r / 5);
  for (const it of sprites) {
    const [x, y] = it.foot;
    const c: Vec3[] = [[x - ext, y - ext, 0], [x + ext, y - ext, 0], [x + ext, y + ext, 0], [x - ext, y + ext, 0]];
    if (!okDepth(c)) continue;
    push({ mode: 3, world: true, color: [r, r / 5, 0, 0.45] }, quad(c, [[-ext, -ext], [ext, -ext], [ext, ext], [-ext, ext]]));
  }
  // 4. hoops: translucent backboard + outline, orange rim
  for (const hoop of lay.static.hoops) {
    const board = hoop.backboard_m;
    if (okDepth(board)) {
      push({ mode: 2, world: true, color: rgb(235, 235, 235, 0.35) }, quad(board, UV));
      line(board.map(proj), true, 2 * lw, rgb(250, 250, 250));
    }
    const ring: Vec3[] = Array.from({ length: 32 }, (_, i) => {
      const a = (i / 31) * 2 * Math.PI;
      const [cx, cy, cz] = hoop.rim_m;
      return [cx + hoop.rim_radius_m * Math.cos(a), cy + hoop.rim_radius_m * Math.sin(a), cz];
    });
    if (okDepth(ring)) line(ring.map(proj), false, 3 * lw, rgb(255, 90, 0));
  }
  // 5. players back to front by view depth of the chest point; the net at its depth
  const real = lay.camera.position_m;
  const people = sprites
    .map((it) => {
      const foot: Vec3 = [it.foot[0], it.foot[1], 0];
      return { it, foot, d: vp.depth([foot[0], foot[1], 0.9]) };
    })
    .sort((a, b) => b.d - a.d);
  const net = lay.static.net;
  const netD = net ? vp.depth(net.top_l_m.map((v, i) => (v + net.top_r_m[i]) / 2) as Vec3) : -1;
  let netDrawn = !net;
  const drawNet = () => {
    if (!net) return;
    netDrawn = true;
    const [lx, ly, h] = net.top_l_m;
    const [rx, ry] = net.top_r_m;
    const depth = net.depth_m;
    const mesh: Vec3[] = [[lx, ly, h], [rx, ry, h], [rx, ry, h - depth], [lx, ly, h - depth]];
    if (okDepth(mesh)) {
      push({ mode: 2, world: true, color: rgb(40, 40, 40, 0.3) }, quad(mesh, UV));
      line([proj(mesh[0]), proj(mesh[1])], false, 3 * lw, rgb(245, 245, 245));
    }
    for (const [x, y] of [[lx, ly], [rx, ry]]) {
      const post: Vec3[] = [[x, y, 0], [x, y, h + 0.05]];
      if (okDepth(post)) line(post.map(proj), false, 4 * lw, rgb(60, 60, 60));
    }
  };
  const [lo, hi] = lay.atlas.mask_ramp;
  for (const { it, foot, d } of people) {
    if (!netDrawn && d <= netD) drawNet();
    if (!atlas || d < NEAR_M + 0.5) continue;
    const axis = billboardAxis(lay.billboard.facing === "real" ? real : vp.eye, foot);
    const [s0, z0, s1, z1] = it.rect;
    const at = (s: number, z: number): Vec3 => [foot[0] + s * axis[0], foot[1] + s * axis[1], z];
    const c = [at(s0, z1), at(s1, z1), at(s1, z0), at(s0, z0)];
    if (!okDepth(c)) continue;
    const [u0, v0, u1, v1] = it.uv;
    push({ mode: 1, world: true, tex: atlas, color: [lay.atlas.mask_offset_u, lo, hi, 0] },
      quad(c, [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]));
  }
  if (!netDrawn) drawNet();
  // 6. the modelled ball with a short fading trail
  const trail = (lay.ball?.xyz.slice(Math.max(0, f - 8), f + 1) ?? []).filter((p): p is Vec3 => !!p);
  if (lay.ball && trail.length && okDepth(trail)) {
    const px = trail.map(proj);
    for (let j = 1; j < px.length; j++) {
      const a = j / px.length;
      line([px[j - 1], px[j]], false, 2 * lw, rgb(255 * a, 140 * a + 40, 60 * a));
    }
    const rad = Math.max(3 * lw, (vp.f * lay.ball.radius_m) / vp.depth(trail[trail.length - 1]));
    const c = px[px.length - 1];
    disc(c, rad + lw, rgb(60, 30, 10));
    disc(c, rad, rgb(235, 110, 30));
  }

  gl.viewport(0, 0, W, H);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STREAM_DRAW);
  for (const d of draws) {
    gl.uniformMatrix4fv(loc.m, false, d.world ? vp.matrix : IDENTITY);
    gl.uniform1i(loc.mode, d.mode);
    if (d.mode === 1 && d.color) gl.uniform3f(loc.mask, d.color[0], d.color[1], d.color[2]);
    else if (d.color) gl.uniform4fv(loc.color, d.color);
    if (d.color2) gl.uniform4fv(loc.color2, d.color2);
    if (d.tex) gl.bindTexture(gl.TEXTURE_2D, d.tex);
    gl.drawArrays(gl.TRIANGLES, d.first, d.count);
  }
}
