package com.replaytv.scene

import com.facebook.react.ReactPackage
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.module.annotations.ReactModule
import com.facebook.react.uimanager.SimpleViewManager
import com.facebook.react.uimanager.ThemedReactContext
import com.facebook.react.uimanager.ViewManager
import com.facebook.react.uimanager.ViewManagerDelegate
import com.facebook.react.viewmanagers.ReplaySceneViewManagerDelegate
import com.facebook.react.viewmanagers.ReplaySceneViewManagerInterface

/** specs/ReplaySceneViewNativeComponent.ts → [SceneView]. */
@ReactModule(name = SceneViewManager.NAME)
class SceneViewManager : SimpleViewManager<SceneView>(), ReplaySceneViewManagerInterface<SceneView> {
  private val delegate = ReplaySceneViewManagerDelegate(this)

  override fun getDelegate(): ViewManagerDelegate<SceneView> = delegate

  override fun getName() = NAME

  override fun createViewInstance(context: ThemedReactContext) = SceneView(context)

  override fun onDropViewInstance(view: SceneView) {
    super.onDropViewInstance(view)
    view.release()
  }

  override fun setLayoutJson(view: SceneView, value: String?) = view.setLayoutJson(value)

  override fun setAzimuth(view: SceneView, value: Double) = view.setCamera(0, value)

  override fun setElevation(view: SceneView, value: Double) = view.setCamera(1, value)

  override fun setDistance(view: SceneView, value: Double) = view.setCamera(2, value)

  override fun setRoll(view: SceneView, value: Double) = view.setCamera(3, value)

  override fun setFovY(view: SceneView, value: Double) = view.setCamera(4, value)

  override fun setPaused(view: SceneView, value: Boolean) = view.setPaused(value)

  override fun setStartTimeSec(view: SceneView, value: Double) = view.setStartTimeSec(value)

  override fun getExportedCustomDirectEventTypeConstants(): MutableMap<String, Any> =
    (super.getExportedCustomDirectEventTypeConstants() ?: mutableMapOf()).apply {
      for (e in listOf("SceneTime", "SceneReady", "SceneError")) put("top$e", mapOf("registrationName" to "on$e"))
    }

  companion object {
    const val NAME = "ReplaySceneView"
  }
}

class SceneViewPackage : ReactPackage {
  override fun createViewManagers(reactContext: ReactApplicationContext): List<ViewManager<in Nothing, in Nothing>> =
    listOf(SceneViewManager())
}
