package com.rahmani.signalscanner

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(28, 32, 28, 32)
        }
        val title = TextView(this).apply {
            text = "هشدار سیگنال بایننس"
            textSize = 25f
            gravity = Gravity.CENTER
        }
        status = TextView(this).apply {
            text = "برای دریافت هشدار سیگنال‌های تازه، پایش را روشن کن."
            textSize = 17f
            gravity = Gravity.CENTER
            setPadding(0, 28, 0, 28)
        }
        val start = Button(this).apply {
            text = "روشن‌کردن هشدارها"
            setOnClickListener { requestPermissionAndStart() }
        }
        val stop = Button(this).apply {
            text = "خاموش‌کردن هشدارها"
            setOnClickListener {
                stopService(Intent(this@MainActivity, SignalService::class.java))
                status.text = "هشدارها خاموش شد."
            }
        }
        val note = TextView(this).apply {
            text = "فقط سیگنال‌های اسپاتِ تأییدشده و تازه هشدار داده می‌شوند. این برنامه معامله انجام نمی‌دهد. برای کارکرد بهتر، اینترنت روشن باشد و محدودیت باتری برنامه را بردار."
            textSize = 14f
            gravity = Gravity.CENTER
            setPadding(0, 24, 0, 0)
        }
        layout.addView(title, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        layout.addView(status, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        layout.addView(start, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        layout.addView(stop, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        layout.addView(note, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        setContentView(layout)
    }

    private fun requestPermissionAndStart() {
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
            return
        }
        startMonitoring()
    }

    private fun startMonitoring() {
        val intent = Intent(this, SignalService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
        status.text = "پایش روشن شد؛ بررسی هر ۵ دقیقه انجام می‌شود، اما زمان انتشار گزارش گیت‌هاب ممکن است تأخیر داشته باشد."
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100 && grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startMonitoring()
        } else if (requestCode == 100) {
            status.text = "برای دریافت هشدار، اجازهٔ اعلان‌ها را در تنظیمات گوشی فعال کن."
        }
    }
}
