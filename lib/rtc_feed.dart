import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

const _backend = MethodChannel('tuya_tv/backend');

class RtcFeed {
  RtcFeed(this.id, this.handle, this.onStatus, this.onFailure);

  final String id;
  final String handle;
  final void Function(String) onStatus;
  final VoidCallback onFailure;
  final renderer = RTCVideoRenderer();
  RTCPeerConnection? _peer;
  bool _closed = false;
  bool _initialized = false;
  bool _answered = false;
  bool _failed = false;
  final _candidates = <RTCIceCandidate>[];
  Future<void> _incoming = Future.value();
  Timer? _watchdog;
  int _lastFrames = 0;
  DateTime _lastProgress = DateTime.now();

  Future<void> start(List<dynamic> iceServers) async {
    await renderer.initialize();
    _initialized = true;
    if (_closed) {
      await renderer.dispose();
      return;
    }
    renderer.onFirstFrameRendered = () {
      if (_closed) return;
      debugPrint('RTC first decoded frame');
      onStatus('In diretta');
    };
    final peer = await createPeerConnection({
      'iceServers': iceServers,
      'bundlePolicy': 'max-bundle',
      'sdpSemantics': 'unified-plan',
    });
    _peer = peer;
    if (_closed) {
      await peer.close();
      await peer.dispose();
      return;
    }
    peer.onIceCandidate = (candidate) {
      final value = candidate.candidate;
      if (value != null && value.isNotEmpty && !_closed) {
        unawaited(
          _send(
            'candidate',
            value,
          ).catchError((Object _) => fail('Errore segnalazione ICE')),
        );
      }
    };
    peer.onTrack = (event) {
      if (event.track.kind == 'audio') event.track.enabled = false;
      if (!_closed && event.track.kind == 'video' && event.streams.isNotEmpty) {
        renderer.srcObject = event.streams.first;
        for (final track in event.streams.first.getAudioTracks()) {
          track.enabled = false;
        }
      }
    };
    peer.onConnectionState = (state) {
      debugPrint('RTC connection: ${state.name}');
      if (state == RTCPeerConnectionState.RTCPeerConnectionStateFailed) {
        fail('Connessione interrotta');
      }
    };
    await peer.addTransceiver(
      kind: RTCRtpMediaType.RTCRtpMediaTypeAudio,
      // Tuya answers audio as sendrecv even when this viewer sends no audio track.
      init: RTCRtpTransceiverInit(direction: TransceiverDirection.SendRecv),
    );
    await peer.addTransceiver(
      kind: RTCRtpMediaType.RTCRtpMediaTypeVideo,
      init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly),
    );
    final offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    if (_closed) return;
    await _send('offer', offer.sdp!);
    _watchdog = Timer.periodic(
      const Duration(seconds: 10),
      (_) => unawaited(_checkProgress()),
    );
  }

  Future<void> _send(String type, String value) async {
    if (!_closed) {
      await _backend.invokeMethod<void>('rtcSignal', {
        'id': id,
        'handle': handle,
        'type': type,
        'value': value,
      });
    }
  }

  void receive(String type, String value) {
    _incoming = _incoming
        .then((_) async {
          final peer = _peer;
          if (_closed || peer == null) return;
          if (type == 'answer' && !_answered) {
            await peer.setRemoteDescription(
              RTCSessionDescription(value, 'answer'),
            );
            _answered = true;
            for (final candidate in _candidates) {
              await peer.addCandidate(candidate);
            }
            _candidates.clear();
            onStatus('Connessione video…');
          } else if (type == 'candidate') {
            final candidate = RTCIceCandidate(
              value.startsWith('a=') ? value.substring(2) : value,
              '0',
              0,
            );
            if (_answered) {
              await peer.addCandidate(candidate);
            } else if (_candidates.length < 128) {
              _candidates.add(candidate);
            }
          } else if (type == 'error') {
            fail(value);
          }
        })
        .catchError((Object error) {
          debugPrint('RTC event error: ${error.runtimeType}');
          fail('Negoziazione video non riuscita');
        });
  }

  Future<void> _checkProgress() async {
    if (_closed || _peer == null) return;
    try {
      final stats = await _peer!.getStats();
      int frames = 0;
      for (final report in stats) {
        if (report.type == 'inbound-rtp') {
          frames += (num.tryParse('${report.values['framesDecoded']}') ?? 0)
              .toInt();
        }
      }
      if (frames > _lastFrames) {
        _lastProgress = DateTime.now();
        debugPrint('RTC frames decoded: $frames');
      }
      _lastFrames = frames;
      if (DateTime.now().difference(_lastProgress).inSeconds > 60)
        fail('Video fermo: riconnessione…');
    } catch (_) {
      if (!_closed) fail('Connessione video persa');
    }
  }

  void fail(String message) {
    if (_closed || _failed) return;
    _failed = true;
    onStatus(message);
    onFailure();
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _watchdog?.cancel();
    renderer.onFirstFrameRendered = null;
    final peer = _peer;
    if (peer != null) {
      await peer.close();
      await peer.dispose();
    }
    if (_initialized) {
      renderer.srcObject = null;
      await renderer.dispose();
    }
  }
}
