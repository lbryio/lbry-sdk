import 'dart:io';
import 'package:flutter/foundation.dart';

TargetPlatform getTargetPlatformForDesktop() {
    // See https://github.com/flutter/flutter/wiki/Desktop-shells#target-platform-override
    if (Platform.isMacOS || Platform.isIOS) {
        return TargetPlatform.iOS;
    } else if (Platform.isAndroid) {
        return TargetPlatform.android;
    }
    return TargetPlatform.fuchsia;
}

