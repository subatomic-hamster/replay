#version 100
// Player billboards. aUv is the package's atlas uv (full video, v down); the decoder's
// SurfaceTexture transform (uSt, GL convention: t up) maps it to the external texture,
// for the colour texel and for its mask texel u + maskOffsetU alike.
uniform mat4 uMvp;
uniform mat4 uSt;
uniform float uMaskOffsetU;
attribute vec3 aPos;
attribute vec2 aUv;
varying highp vec2 vColUv;
varying highp vec2 vMaskUv;

void main() {
  vColUv = (uSt * vec4(aUv.x, 1.0 - aUv.y, 0.0, 1.0)).xy;
  vMaskUv = (uSt * vec4(aUv.x + uMaskOffsetU, 1.0 - aUv.y, 0.0, 1.0)).xy;
  gl_Position = uMvp * vec4(aPos, 1.0);
}
