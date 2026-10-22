package com.replaytv

import android.app.Application
import com.facebook.react.PackageList
import com.facebook.react.ReactApplication
import com.facebook.react.ReactHost
import com.facebook.react.ReactNativeApplicationEntryPoint.loadReactNative
import com.facebook.react.defaults.DefaultReactHost.getDefaultReactHost
import com.facebook.react.modules.network.CookieJarContainer
import com.facebook.react.modules.network.OkHttpClientProvider
import com.replaytv.scene.SceneViewPackage
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

/**
 * No cookies anywhere (the API takes a key header, media comes from presigned URLs). React
 * Native's default jar asks WebView's CookieManager, and loading WebView for that held the
 * first API request ~1.9 s on a Fire TV Stick. fetch, Fresco and react-native-video all build
 * their OkHttp client through OkHttpClientProvider, and each sets its jar on this container.
 */
private object NoCookies : CookieJarContainer {
  override fun setCookieJar(cookieJar: CookieJar) {}

  override fun removeCookieJar() {}

  override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {}

  override fun loadForRequest(url: HttpUrl): List<Cookie> = emptyList()
}

class MainApplication : Application(), ReactApplication {

  override val reactHost: ReactHost by lazy {
    getDefaultReactHost(
      context = applicationContext,
      packageList =
        PackageList(this).packages.apply {
          add(ReplaySettingsPackage())
          add(SceneViewPackage())
        },
    )
  }

  override fun onCreate() {
    super.onCreate()
    OkHttpClientProvider.setOkHttpClientFactory {
      OkHttpClientProvider.createClientBuilder().cookieJar(NoCookies).build()
    }
    loadReactNative(this)
  }
}
