package com.xiaomi.llmbenchmark;

import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class HardwareSummary {
    final int sampleCount;
    final long peakAppPssBytes;
    final long peakAppJavaHeapBytes;
    final long peakAppNativeHeapBytes;
    final double peakSystemMemoryUsedRatio;
    final double peakBatteryTempC;
    final double peakThermalTempC;
    final String peakThermalZone;

    HardwareSummary(List<HardwareSample> samples) {
        long peakPss = 0L;
        long peakJava = 0L;
        long peakNative = 0L;
        double peakMemRatio = 0.0;
        double peakBattery = Double.NaN;
        double peakThermal = Double.NaN;
        String peakZone = "";
        for (HardwareSample sample : samples) {
            peakPss = Math.max(peakPss, sample.appPssBytes);
            peakJava = Math.max(peakJava, sample.appJavaHeapBytes);
            peakNative = Math.max(peakNative, sample.appNativeHeapBytes);
            peakMemRatio = Math.max(peakMemRatio, sample.systemMemoryUsedRatio());
            if (!Double.isNaN(sample.batteryTempC)
                    && (Double.isNaN(peakBattery) || sample.batteryTempC > peakBattery)) {
                peakBattery = sample.batteryTempC;
            }
            if (!Double.isNaN(sample.maxThermalTempC)
                    && (Double.isNaN(peakThermal) || sample.maxThermalTempC > peakThermal)) {
                peakThermal = sample.maxThermalTempC;
                peakZone = sample.maxThermalZone;
            }
        }
        this.sampleCount = samples.size();
        this.peakAppPssBytes = peakPss;
        this.peakAppJavaHeapBytes = peakJava;
        this.peakAppNativeHeapBytes = peakNative;
        this.peakSystemMemoryUsedRatio = peakMemRatio;
        this.peakBatteryTempC = peakBattery;
        this.peakThermalTempC = peakThermal;
        this.peakThermalZone = peakZone;
    }

    JSONObject toJson(List<HardwareSample> samples) throws Exception {
        JSONObject json = new JSONObject();
        json.put("sample_count", sampleCount);
        json.put("peak_app_pss_bytes", peakAppPssBytes);
        json.put("peak_app_java_heap_bytes", peakAppJavaHeapBytes);
        json.put("peak_app_native_heap_bytes", peakAppNativeHeapBytes);
        json.put("peak_system_memory_used_ratio", peakSystemMemoryUsedRatio);
        json.put("peak_battery_temperature_c", jsonNumber(peakBatteryTempC));
        json.put("peak_thermal_temperature_c", jsonNumber(peakThermalTempC));
        json.put("peak_thermal_zone", peakThermalZone);
        JSONArray sampleArray = new JSONArray();
        for (HardwareSample sample : samples) {
            sampleArray.put(sample.toJson());
        }
        json.put("samples", sampleArray);
        return json;
    }

    static List<HardwareSample> safeSamples(List<HardwareSample> samples) {
        return Collections.unmodifiableList(samples);
    }

    private static Object jsonNumber(double value) {
        return Double.isNaN(value) ? JSONObject.NULL : value;
    }
}
