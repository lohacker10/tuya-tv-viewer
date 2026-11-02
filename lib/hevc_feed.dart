import 'dart:async';
import 'dart:collection';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:video_player/video_player.dart';

import 'fmp4_fragments.dart';
import 'fmp4_timeline.dart';

/// Feeds the device's standard MP4 decoder from Tuya's WebRTC data channel.
class HevcFeed extends ChangeNotifier {
  HevcFeed(this.handle, this.onFailure, this.onReady, this.onContainerAudio);
  final String handle;
  final VoidCallback onFailure;
  final VoidCallback onReady;
  final void Function(bool) onContainerAudio;
  final _timeline = Fmp4Timeline();
  final _fragments = Fmp4Fragments();
  final _pending = Queue<Uint8List>();
  HttpServer? _server;
  HttpResponse? _response;
  VideoPlayerController? controller;
  bool _closed = false;
  bool _flushing = false;
  bool _ready = false;
  int _queuedBytes = 0;
  bool _containerAudio = true;

  Future<void> start() async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    _server = server;
    if (_closed) {
      await server.close(force: true);
      return;
    }
    server.listen(
      (request) {
        if (request.method != 'GET' ||
            request.uri.path != '/$handle.mp4' ||
            _response != null) {
          request.response.statusCode = HttpStatus.notFound;
          unawaited(request.response.close());
          return;
        }
        _response = request.response;
        request.response.headers.contentType = ContentType('video', 'mp4');
        request.response.headers.set(
          HttpHeaders.cacheControlHeader,
          'no-store',
        );
        unawaited(_flush());
      },
      onError: (Object _) {
        if (!_closed) onFailure();
      },
    );
    final player = VideoPlayerController.networkUrl(
      Uri.parse('http://127.0.0.1:${server.port}/$handle.mp4'),
      formatHint: VideoFormat.other,
      videoPlayerOptions: VideoPlayerOptions(mixWithOthers: true),
    );
    controller = player;
    player.addListener(() {
      if (_closed) return;
      if (player.value.hasError) {
        onFailure();
        return;
      }
      if (!_ready &&
          player.value.isInitialized &&
          player.value.position > Duration.zero) {
        _ready = true;
        debugPrint('RTC HEVC first video size=${player.value.size}');
        onReady();
        notifyListeners();
      }
    });
    unawaited(_initialize(player));
  }

  Future<void> _initialize(VideoPlayerController player) async {
    try {
      await player.initialize();
      if (_closed) return;
      try {
        final tracks = await player.getAudioTracks();
        _containerAudio = tracks.isNotEmpty;
        onContainerAudio(_containerAudio);
        debugPrint('RTC HEVC audio tracks: ${tracks.length}');
      } catch (_) {
        onContainerAudio(_containerAudio);
      }
      await player.setVolume(_containerAudio ? 1 : 0);
      await player.play();
      if (!_closed) notifyListeners();
    } catch (_) {
      if (!_closed) onFailure();
    }
  }

  void add(Uint8List fragment) {
    if (_closed) return;
    try {
      final data = _fragments.payload(fragment);
      for (final box in _timeline.push(data)) {
        if (_queuedBytes + box.length > 8 * 1024 * 1024)
          throw const FormatException('HD decoder is not consuming the stream');
        _pending.add(box);
        _queuedBytes += box.length;
      }
      unawaited(_flush());
    } catch (error) {
      debugPrint('RTC MP4 stream error: ${error.runtimeType}');
      onFailure();
    }
  }

  Future<void> _flush() async {
    final response = _response;
    if (_closed || _flushing || response == null) return;
    _flushing = true;
    try {
      while (!_closed && _pending.isNotEmpty) {
        final data = _pending.removeFirst();
        _queuedBytes -= data.length;
        response.add(data);
        await response.flush();
      }
    } catch (_) {
      if (!_closed) onFailure();
    } finally {
      _flushing = false;
    }
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _pending.clear();
    _queuedBytes = 0;
    await _server?.close(force: true);
    await controller?.dispose();
    dispose();
  }
}
