#version 100
// Plates (backdrop, floor): world quad, uv as in the package (origin top-left, v down;
// GLUtils uploads bitmap row 0 at t = 0, so no flip).
uniform mat4 uMvp;
attribute vec3 aPos;
attribute vec2 aUv;
varying highp vec2 vUv;

void main() {
  vUv = aUv;
  gl_Position = uMvp * vec4(aPos, 1.0);
}
