package com.xiaomi.llmbenchmark;

import org.json.JSONObject;

final class HardwareSample {
    final long elapsedMs;
    final String phase;
    final String itemId;
    final long systemAvailMemBytes;
    final long systemTotalMemBytes;
    final long appPssBytes;
    final long appJavaHeapBytes;
    final long appNativeHeapBytes;
    final double batteryTempC;
    final double maxThermalTempC;
    final String maxThermalZone;

    HardwareSample(
            long elapsedMs,
            String phase,
            String itemId,
            long systemAvailMemBytes,
            long systemTotalMemBytes,
            long appPssBytes,
            long appJavaHeapBytes,
            long appNativeHeapBytes,
            double batteryTempC,
            double maxThermalTempC,
            String maxThermalZone) {
        this.elapsedMs = elapsedMs;
        this.phase = phase;
        this.itemId = itemId;
        this.systemAvailMemBytes = systemAvailMemBytes;
        this.systemTotalMemBytes = systemTotalMemBytes;
        this.appPssBytes = appPssBytes;
        this.appJavaHeapBytes = appJavaHeapBytes;
        this.appNativeHeapBytes = appNativeHeapBytes;
        this.batteryTempC = batteryTempC;
        this.maxThermalTempC = maxThermalTempC;
        this.maxThermalZone = maxThermalZone;
    }

    double systemMemoryUsedRatio() {
        if (systemTotalMemBytes <= 0L) {
            return 0.0;
        }
        return Math.max(0.0, Math.min(1.0, 1.0 - systemAvailMemBytes * 1.0 / systemTotalMemBytes));
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("elapsed_ms", elapsedMs);
        json.put("phase", phase);
        json.put("item_id", itemId);
        json.put("system_available_memory_bytes", systemAvailMemBytes);
        json.put("system_total_memory_bytes", systemTotalMemBytes);
        json.put("system_memory_used_ratio", systemMemoryUsedRatio());
        json.put("app_pss_bytes", appPssBytes);
        json.put("app_java_heap_bytes", appJavaHeapBytes);
        json.put("app_native_heap_bytes", appNativeHeapBytes);
        json.put("battery_temperature_c", batteryTempC);
        json.put("max_thermal_temperature_c", maxThermalTempC);
        json.put("max_thermal_zone", maxThermalZone);
        return json;
    }
}
