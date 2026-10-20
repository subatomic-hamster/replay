package com.replaytv

import android.content.Context
import com.facebook.react.BaseReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.module.model.ReactModuleInfo
import com.facebook.react.module.model.ReactModuleInfoProvider
import com.replaytv.specs.NativeReplaySettingsSpec

/** specs/NativeReplaySettings.ts: the API base and key the user set on the Settings screen. */
class ReplaySettingsModule(context: ReactApplicationContext) : NativeReplaySettingsSpec(context) {
  private val prefs = context.getSharedPreferences("replay", Context.MODE_PRIVATE)

  override fun getName() = NAME

  override fun getApiBase(): String = prefs.getString("apiBase", null) ?: ""

  // commit, not apply: the value must survive the app being killed right after Save.
  override fun setApiBase(value: String) {
    prefs.edit().putString("apiBase", value).commit()
  }

  override fun getBuildApiBase(): String = BuildConfig.REPLAY_API_BASE

  override fun getApiKey(): String = prefs.getString("apiKey", null) ?: ""

  override fun setApiKey(value: String) {
    prefs.edit().putString("apiKey", value).commit()
  }

  override fun getBuildApiKey(): String = BuildConfig.REPLAY_API_KEY

  // Generic app values, kept apart from the settings above ("s." prefix).
  override fun getString(key: String): String = prefs.getString("s.$key", null) ?: ""

  // apply, not commit: resume.ts writes every few seconds; a kill can lose the last one.
  override fun setString(key: String, value: String) {
    prefs.edit().putString("s.$key", value).apply()
  }

  companion object {
    const val NAME = "ReplaySettings"
  }
}

class ReplaySettingsPackage : BaseReactPackage() {
  override fun getModule(name: String, reactContext: ReactApplicationContext): NativeModule? =
    if (name == ReplaySettingsModule.NAME) ReplaySettingsModule(reactContext) else null

  override fun getReactModuleInfoProvider() = ReactModuleInfoProvider {
    mapOf(
      ReplaySettingsModule.NAME to
        ReactModuleInfo(
          name = ReplaySettingsModule.NAME,
          className = ReplaySettingsModule.NAME,
          canOverrideExistingModule = false,
          needsEagerInit = false,
          isCxxModule = false,
          isTurboModule = true,
        )
    )
  }
}
