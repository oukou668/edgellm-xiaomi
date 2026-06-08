plugins {
    id("com.android.application")
}

fun gitValue(repo: String, vararg args: String): String {
    return try {
        val process = ProcessBuilder(listOf("git", "-C", repo) + args)
            .redirectErrorStream(true)
            .start()
        val text = process.inputStream.bufferedReader().readText().trim()
        if (process.waitFor() == 0 && text.isNotBlank()) text else "unknown"
    } catch (_: Exception) {
        "unknown"
    }
}

fun gitDirty(repo: String): String {
    return try {
        val process = ProcessBuilder("git", "-C", repo, "status", "--porcelain")
            .redirectErrorStream(true)
            .start()
        val text = process.inputStream.bufferedReader().readText().trim()
        process.waitFor()
        (text.isNotBlank()).toString()
    } catch (_: Exception) {
        "unknown"
    }
}

val appRepo = rootDir.absolutePath
val mlcBenchmarkRepo = "/Users/chenhaotian/code/mlc_benchmark"
val llamaBenchmarkRepo = "/Users/chenhaotian/code/llama_benchmark"
val llamaCppRepo = providers.gradleProperty("llamaCppDir")
    .orElse("/Users/chenhaotian/code/llama_benchmark/third_party/llama.cpp")
    .get()
val mlcLlmRepo = providers.gradleProperty("mlcLlmSourceDir")
    .orElse("/Users/chenhaotian/code/iPhone/mlc-llm")
    .get()

android {
    namespace = "com.xiaomi.llmbenchmark"
    compileSdk = 36
    ndkVersion = "28.2.13676358"

    defaultConfig {
        applicationId = "com.xiaomi.llmbenchmark"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"

        buildConfigField("String", "APP_REPO_PATH", "\"$appRepo\"")
        buildConfigField("String", "APP_GIT_COMMIT", "\"${gitValue(appRepo, "rev-parse", "HEAD")}\"")
        buildConfigField("String", "APP_GIT_DIRTY", "\"${gitDirty(appRepo)}\"")
        buildConfigField("String", "MLC_BENCHMARK_REPO_PATH", "\"$mlcBenchmarkRepo\"")
        buildConfigField("String", "MLC_BENCHMARK_GIT_COMMIT", "\"${gitValue(mlcBenchmarkRepo, "rev-parse", "HEAD")}\"")
        buildConfigField("String", "MLC_BENCHMARK_GIT_DIRTY", "\"${gitDirty(mlcBenchmarkRepo)}\"")
        buildConfigField("String", "LLAMA_BENCHMARK_REPO_PATH", "\"$llamaBenchmarkRepo\"")
        buildConfigField("String", "LLAMA_BENCHMARK_GIT_COMMIT", "\"${gitValue(llamaBenchmarkRepo, "rev-parse", "HEAD")}\"")
        buildConfigField("String", "LLAMA_BENCHMARK_GIT_DIRTY", "\"${gitDirty(llamaBenchmarkRepo)}\"")
        buildConfigField("String", "LLAMA_CPP_REPO_PATH", "\"$llamaCppRepo\"")
        buildConfigField("String", "LLAMA_CPP_GIT_COMMIT", "\"${gitValue(llamaCppRepo, "rev-parse", "HEAD")}\"")
        buildConfigField("String", "LLAMA_CPP_GIT_DIRTY", "\"${gitDirty(llamaCppRepo)}\"")
        buildConfigField("String", "MLC_LLM_SOURCE_DIR", "\"$mlcLlmRepo\"")
        buildConfigField("String", "MLC_LLM_GIT_COMMIT", "\"${gitValue(mlcLlmRepo, "rev-parse", "HEAD")}\"")
        buildConfigField("String", "MLC_LLM_GIT_DIRTY", "\"${gitDirty(mlcLlmRepo)}\"")

        ndk {
            abiFilters += listOf("arm64-v8a")
        }

        externalNativeBuild {
            cmake {
                arguments += listOf(
                    "-DANDROID_STL=c++_static",
                    "-DBUILD_SHARED_LIBS=ON",
                    "-DLLAMA_BUILD_COMMON=ON",
                    "-DLLAMA_OPENSSL=OFF",
                    "-DGGML_NATIVE=OFF",
                    "-DGGML_BACKEND_DL=ON",
                    "-DGGML_CPU_ALL_VARIANTS=ON",
                    "-DGGML_LLAMAFILE=OFF",
                    "-DLLAMA_CPP_DIR=${providers.gradleProperty("llamaCppDir").orElse("/Users/chenhaotian/code/llama_benchmark/third_party/llama.cpp").get()}"
                )
            }
        }
    }

    sourceSets {
        getByName("main") {
            java.srcDir("../mlc/dist/lib/mlc4j/src/main/java")
            assets.srcDir("../mlc/dist/bundle")
        }
    }

    buildFeatures {
        buildConfig = true
    }

    externalNativeBuild {
        cmake {
            path("src/main/cpp/CMakeLists.txt")
            version = "3.31.6"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }
}

dependencies {
    implementation(fileTree(mapOf("dir" to "libs", "include" to listOf("*.jar", "*.aar"))))
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
