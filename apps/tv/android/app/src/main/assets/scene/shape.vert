#version 100
// Flat-coloured geometry: hoops, net, contact shadows (aLocal = disc coords in radii) and
// the ball (a GL point; uPointScale = 2 · focal px · radius, so its size follows depth).
uniform mat4 uMvp;
uniform float uPointScale;
attribute vec3 aPos;
attribute vec2 aLocal;
varying vec2 vLocal;

void main() {
  vLocal = aLocal;
  gl_Position = uMvp * vec4(aPos, 1.0);
  gl_PointSize = max(uPointScale / gl_Position.w, 3.0);
}
