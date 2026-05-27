plugins {
    id("com.android.application")
}

android {
    namespace = "com.xiaomi.llmbenchmark"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.xiaomi.llmbenchmark"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    sourceSets {
        getByName("main") {
            java.srcDir("../mlc/package/lib/mlc4j/src/main/java")
            assets.srcDir("../mlc/package/lib/mlc4j/src/main/assets")
        }
    }
}

dependencies {
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.jar", "*.aar"))))
}
