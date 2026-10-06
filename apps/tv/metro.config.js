const path = require('path');
const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');

// packages/tv-core (pure TS shared with apps/web) lives outside this project root. Its
// files have no node_modules of their own, so the Babel helpers Metro injects into them
// (@babel/runtime/...) must resolve from this app's node_modules.
const core = path.resolve(__dirname, '../../packages/tv-core');

module.exports = mergeConfig(getDefaultConfig(__dirname), {
  watchFolders: [core],
  resolver: { nodeModulesPaths: [path.resolve(__dirname, 'node_modules')] },
});
