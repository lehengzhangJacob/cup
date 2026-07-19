package com.lingshan.guide;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.net.http.SslError;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

public class MainActivity extends Activity {
    private static final String APP_URL = "https://139.159.150.134:20443/";
    private static final int REQUEST_APP_PERMISSIONS = 1001;
    private static final int REQUEST_WEB_PERMISSIONS = 1002;
    private static final int REQUEST_FILE_CHOOSER = 1003;
    private static final int REQUEST_GEOLOCATION = 1004;

    private WebView webView;
    private PermissionRequest pendingWebPermissionRequest;
    private GeolocationPermissions.Callback pendingGeolocationCallback;
    private String pendingGeolocationOrigin;
    private ValueCallback<Uri[]> filePathCallback;
    private Uri cameraOutputUri;
    private AudioManager audioManager;
    private AudioFocusRequest audioFocusRequest;
    private final AudioManager.OnAudioFocusChangeListener audioFocusChangeListener = focusChange -> { };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        audioManager = (AudioManager) getSystemService(AUDIO_SERVICE);

        webView = new WebView(this);
        setContentView(webView);
        configureWebView();
        requestInitialPermissions();

        if (savedInstanceState == null) {
            webView.loadUrl(APP_URL);
        } else {
            webView.restoreState(savedInstanceState);
        }
    }

    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setGeolocationEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setUserAgentString(settings.getUserAgentString() + " LingshanGuideAndroid/1.0");
        webView.addJavascriptInterface(new AndroidAudioBridge(), "AndroidAudio");

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("https".equalsIgnoreCase(uri.getScheme())) {
                    return false;
                }
                return true;
            }

            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                Toast.makeText(MainActivity.this, "安全连接验证失败", Toast.LENGTH_LONG).show();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    Toast.makeText(MainActivity.this, "网页连接失败，请检查网络后重试", Toast.LENGTH_LONG).show();
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> handleWebPermissionRequest(request));
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                if (pendingWebPermissionRequest == request) {
                    pendingWebPermissionRequest = null;
                }
            }

            @Override
            public void onGeolocationPermissionsShowPrompt(
                    String origin,
                    GeolocationPermissions.Callback callback
            ) {
                if (hasLocationPermission()) {
                    callback.invoke(origin, true, false);
                    return;
                }
                pendingGeolocationOrigin = origin;
                pendingGeolocationCallback = callback;
                requestPermissions(
                        new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION},
                        REQUEST_GEOLOCATION
                );
            }

            @Override
            public boolean onShowFileChooser(
                    WebView view,
                    ValueCallback<Uri[]> callback,
                    FileChooserParams params
            ) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                launchFileChooser(params);
                return true;
            }
        });
    }

    private void requestInitialPermissions() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return;
        }
        List<String> missing = new ArrayList<>();
        addIfMissing(missing, Manifest.permission.RECORD_AUDIO);
        addIfMissing(missing, Manifest.permission.CAMERA);
        addIfMissing(missing, Manifest.permission.ACCESS_FINE_LOCATION);
        addIfMissing(missing, Manifest.permission.ACCESS_COARSE_LOCATION);
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P) {
            addIfMissing(missing, Manifest.permission.WRITE_EXTERNAL_STORAGE);
        }
        if (!missing.isEmpty()) {
            requestPermissions(missing.toArray(new String[0]), REQUEST_APP_PERMISSIONS);
        }
    }

    private void addIfMissing(List<String> permissions, String permission) {
        if (checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED) {
            permissions.add(permission);
        }
    }

    private void handleWebPermissionRequest(PermissionRequest request) {
        List<String> missing = new ArrayList<>();
        for (String resource : request.getResources()) {
            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) {
                addIfMissing(missing, Manifest.permission.RECORD_AUDIO);
            } else if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)) {
                addIfMissing(missing, Manifest.permission.CAMERA);
            }
        }
        if (missing.isEmpty()) {
            grantSupportedWebResources(request);
            return;
        }
        pendingWebPermissionRequest = request;
        requestPermissions(missing.toArray(new String[0]), REQUEST_WEB_PERMISSIONS);
    }

    private void grantSupportedWebResources(PermissionRequest request) {
        List<String> granted = new ArrayList<>();
        boolean grantsAudioCapture = false;
        for (String resource : request.getResources()) {
            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)
                    && checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                granted.add(resource);
                grantsAudioCapture = true;
            } else if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)
                    && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                granted.add(resource);
            }
        }
        if (granted.isEmpty()) {
            request.deny();
        } else {
            if (grantsAudioCapture) {
                prepareAudioCapture();
            }
            request.grant(granted.toArray(new String[0]));
        }
    }

    private void prepareAudioCapture() {
        if (audioManager == null) {
            return;
        }
        audioManager.setMode(AudioManager.MODE_IN_COMMUNICATION);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            AudioAttributes attributes = new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build();
            audioFocusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                    .setAudioAttributes(attributes)
                    .setOnAudioFocusChangeListener(audioFocusChangeListener)
                    .build();
            audioManager.requestAudioFocus(audioFocusRequest);
        } else {
            audioManager.requestAudioFocus(
                    audioFocusChangeListener,
                    AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
            );
        }
    }

    private void releaseAudioCapture() {
        if (audioManager == null) {
            return;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && audioFocusRequest != null) {
            audioManager.abandonAudioFocusRequest(audioFocusRequest);
            audioFocusRequest = null;
        } else {
            audioManager.abandonAudioFocus(audioFocusChangeListener);
        }
        audioManager.setMode(AudioManager.MODE_NORMAL);
    }

    private final class AndroidAudioBridge {
        @JavascriptInterface
        public void beginCapture() {
            runOnUiThread(MainActivity.this::prepareAudioCapture);
        }

        @JavascriptInterface
        public void endCapture() {
            runOnUiThread(MainActivity.this::releaseAudioCapture);
        }
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private void launchFileChooser(WebChromeClient.FileChooserParams params) {
        Intent contentIntent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        contentIntent.addCategory(Intent.CATEGORY_OPENABLE);
        contentIntent.setType(resolveMimeType(params.getAcceptTypes()));

        Intent chooser = Intent.createChooser(contentIntent, "选择文件");
        if (acceptsImages(params.getAcceptTypes()) && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            Intent cameraIntent = createCameraIntent();
            if (cameraIntent != null) {
                chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{cameraIntent});
            }
        }

        try {
            startActivityForResult(chooser, REQUEST_FILE_CHOOSER);
        } catch (ActivityNotFoundException error) {
            filePathCallback.onReceiveValue(null);
            filePathCallback = null;
            Toast.makeText(this, "手机没有可用的文件选择器", Toast.LENGTH_LONG).show();
        }
    }

    private Intent createCameraIntent() {
        ContentValues values = new ContentValues();
        values.put(MediaStore.Images.Media.DISPLAY_NAME, "lingshan_" + System.currentTimeMillis() + ".jpg");
        values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            values.put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/LingshanGuide");
        }
        try {
            cameraOutputUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
        } catch (SecurityException error) {
            return null;
        }
        if (cameraOutputUri == null) {
            return null;
        }
        Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
        intent.putExtra(MediaStore.EXTRA_OUTPUT, cameraOutputUri);
        intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        return intent.resolveActivity(getPackageManager()) == null ? null : intent;
    }

    private boolean acceptsImages(String[] acceptTypes) {
        for (String acceptType : acceptTypes) {
            if (acceptType != null && (acceptType.startsWith("image/") || acceptType.equals("*/*"))) {
                return true;
            }
        }
        return acceptTypes.length == 0;
    }

    private String resolveMimeType(String[] acceptTypes) {
        for (String acceptType : acceptTypes) {
            if (acceptType != null && !acceptType.trim().isEmpty() && !acceptType.contains(",")) {
                return acceptType;
            }
        }
        return "*/*";
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_WEB_PERMISSIONS && pendingWebPermissionRequest != null) {
            PermissionRequest request = pendingWebPermissionRequest;
            pendingWebPermissionRequest = null;
            grantSupportedWebResources(request);
        } else if (requestCode == REQUEST_GEOLOCATION && pendingGeolocationCallback != null) {
            pendingGeolocationCallback.invoke(pendingGeolocationOrigin, hasLocationPermission(), false);
            pendingGeolocationCallback = null;
            pendingGeolocationOrigin = null;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_FILE_CHOOSER || filePathCallback == null) {
            return;
        }
        Uri[] result = null;
        if (resultCode == RESULT_OK) {
            if (data != null && data.getData() != null) {
                result = new Uri[]{data.getData()};
            } else if (cameraOutputUri != null) {
                result = new Uri[]{cameraOutputUri};
            }
        }
        filePathCallback.onReceiveValue(result);
        filePathCallback = null;
        cameraOutputUri = null;
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        webView.saveState(outState);
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onResume() {
        super.onResume();
        webView.onResume();
    }

    @Override
    protected void onPause() {
        releaseAudioCapture();
        webView.onPause();
        super.onPause();
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        releaseAudioCapture();
        if (webView != null) {
            webView.loadUrl("about:blank");
            webView.stopLoading();
            webView.destroy();
        }
        super.onDestroy();
    }
}
