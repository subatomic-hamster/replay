#version 100
#extension GL_OES_EGL_image_external : require
// Colour from the left half, alpha from the mask half through the package's ramp
// (docs/scene-format.md "Atlas"). Output premultiplied (blend ONE, ONE_MINUS_SRC_ALPHA).
precision mediump float;
uniform samplerExternalOES uAtlas;
uniform vec2 uRamp;
varying highp vec2 vColUv;
varying highp vec2 vMaskUv;

void main() {
  vec3 c = texture2D(uAtlas, vColUv).rgb;
  float m = texture2D(uAtlas, vMaskUv).g;
  float a = clamp((m - uRamp.x) / (uRamp.y - uRamp.x), 0.0, 1.0);
  gl_FragColor = vec4(c * a, a);
}
