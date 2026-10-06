#version 100
// uColor is straight alpha; the output is premultiplied. uMode: 0 solid, 1 soft contact
// shadow (Tier B: a disc of radius 1 blurred with sigma 0.2 radii, 45 % at the centre; the
// same logistic edge as FreeView.web.tsx), 2 round point (ball).
precision mediump float;
uniform vec4 uColor;
uniform float uMode;
varying vec2 vLocal;

void main() {
  float a = uColor.a;
  if (uMode > 1.5) {
    a *= 1.0 - smoothstep(0.8, 1.0, length(gl_PointCoord * 2.0 - 1.0));
  } else if (uMode > 0.5) {
    a /= 1.0 + exp(1.702 * (length(vLocal) - 1.0) / 0.2);
  }
  gl_FragColor = vec4(uColor.rgb * a, a);
}
