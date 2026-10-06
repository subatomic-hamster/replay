#version 100
// Android bitmaps are premultiplied, so the whole scene blends ONE, ONE_MINUS_SRC_ALPHA
// (the same result as the contract's straight-alpha blend).
precision mediump float;
uniform sampler2D uTex;
varying highp vec2 vUv;

void main() {
  gl_FragColor = texture2D(uTex, vUv);
}
