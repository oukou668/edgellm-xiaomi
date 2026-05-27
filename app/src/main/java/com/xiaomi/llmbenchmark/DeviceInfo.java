package com.xiaomi.llmbenchmark;

import android.os.Build;
import android.os.StatFs;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.Locale;
import org.json.JSONObject;

final class DeviceInfo {
    final String manufacturer;
    final String model;
    final String androidRelease;
    final int sdkInt;
    final String abi;
    final long totalMemoryBytes;
    final long availableDataBytes;
    final String gpuHint;

    private DeviceInfo(
            String manufacturer,
            String model,
            String androidRelease,
            int sdkInt,
            String abi,
            long totalMemoryBytes,
            long availableDataBytes,
            String gpuHint) {
        this.manufacturer = manufacturer;
        this.model = model;
        this.androidRelease = androidRelease;
        this.sdkInt = sdkInt;
        this.abi = abi;
        this.totalMemoryBytes = totalMemoryBytes;
        this.availableDataBytes = availableDataBytes;
        this.gpuHint = gpuHint;
    }

    static DeviceInfo collect(File dataDir) {
        StatFs statFs = new StatFs(dataDir.getAbsolutePath());
        return new DeviceInfo(
                Build.MANUFACTURER,
                Build.MODEL,
                Build.VERSION.RELEASE,
                Build.VERSION.SDK_INT,
                Build.SUPPORTED_ABIS.length == 0 ? "unknown" : Build.SUPPORTED_ABIS[0],
                readMemTotalBytes(),
                statFs.getAvailableBytes(),
                System.getProperty("ro.hardware.egl", "unknown"));
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("manufacturer", manufacturer);
        json.put("model", model);
        json.put("android_release", androidRelease);
        json.put("sdk_int", sdkInt);
        json.put("abi", abi);
        json.put("total_memory_bytes", totalMemoryBytes);
        json.put("available_data_bytes", availableDataBytes);
        json.put("gpu_hint", gpuHint);
        return json;
    }

    String summary() {
        return String.format(
                Locale.US,
                "%s %s, Android %s/API %d, %s, %.1f GiB RAM, %.1f GiB free",
                manufacturer,
                model,
                androidRelease,
                sdkInt,
                abi,
                totalMemoryBytes / 1024.0 / 1024.0 / 1024.0,
                availableDataBytes / 1024.0 / 1024.0 / 1024.0);
    }

    private static long readMemTotalBytes() {
        try (BufferedReader reader = new BufferedReader(new FileReader("/proc/meminfo"))) {
            String line = reader.readLine();
            if (line == null) {
                return 0L;
            }
            String digits = line.replaceAll("[^0-9]", "");
            return Long.parseLong(digits) * 1024L;
        } catch (Exception ignored) {
            return 0L;
        }
    }
}

