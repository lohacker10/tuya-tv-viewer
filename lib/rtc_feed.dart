import 'dart:async';
import 'dart:convert';

import 'hevc_feed.dart';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

const _backend = MethodChannel('tuya_tv/backend');

class RtcFeed extends ChangeNotifier {
  RtcFeed(
    this.id,
    this.handle,
    this.onStatus,
    this.onFailure, {
    required this.audioEnabled,
    required this.hevc,
    required this.highQuality,
  });

  final bool audioEnabled;
  final bool hevc;
  final bool highQuality;
  HevcFeed? hevcFeed;
  RTCDataChannel? _channel;
  final _audioTracks = <MediaStreamTrack>[];
  bool _containerAudio = false;
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
  bool _qualitySent = false;
  final _candidates = <RTCIceCandidate>[];
  Future<void> _incoming = Future.value();
  Timer? _watchdog;
  int _lastFrames = 0;
  DateTime _lastProgress = DateTime.now();

  Future<void> start(List<dynamic> iceServers) async {
    if (hevc) {
      _containerAudio = true;
      final media = HevcFeed(
        handle,
        () => fail('Decoder HD non disponibile'),
        () => onStatus('In diretta'),
        (hasAudio) {
          _containerAudio = hasAudio;
          for (final track in _audioTracks) {
            track.enabled = audioEnabled && !hasAudio;
          }
        },
      );
      hevcFeed = media;
      media.addListener(() {
        if (!_closed) notifyListeners();
      });
      await media.start();
      if (_closed) {
        await media.close();
        return;
      }
      notifyListeners();
    }
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
      if (_closed) {
        event.track.enabled = false;
        return;
      }
      if (event.track.kind == 'audio') {
        _audioTracks.add(event.track);
        event.track.enabled = audioEnabled && !_containerAudio;
      }
      if (!_closed && event.track.kind == 'video' && event.streams.isNotEmpty) {
        renderer.srcObject = event.streams.first;
        for (final track in event.streams.first.getAudioTracks()) {
          track.enabled = audioEnabled && !_containerAudio;
        }
      }
    };
    peer.onConnectionState = (state) {
      debugPrint('RTC connection: ${state.name}');
      if (!_closed &&
          !hevc &&
          !_qualitySent &&
          state == RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
        _qualitySent = true;
        unawaited(
          _send(
            'resolution',
            highQuality ? '0' : '1',
          ).catchError((Object _) => fail('Cambio risoluzione non riuscito')),
        );
      }
      if (state == RTCPeerConnectionState.RTCPeerConnectionStateFailed) {
        fail('Connessione interrotta');
      }
    };
    await peer.addTransceiver(
      kind: RTCRtpMediaType.RTCRtpMediaTypeAudio,
      // Tuya answers audio as sendrecv even when this viewer sends no audio track.
      init: RTCRtpTransceiverInit(direction: TransceiverDirection.SendRecv),
    );
    if (hevc) {
      final options = RTCDataChannelInit()..maxRetransmits = 5;
      final channel = await peer.createDataChannel('fmp4Stream', options);
      _channel = channel;
      channel.onMessage = (message) {
        if (_closed) return;
        if (message.isBinary) {
          hevcFeed?.add(message.binary);
          return;
        }
        try {
          final data = jsonDecode(message.text) as Map<String, dynamic>;
          final kind = data['type'];
          if (kind == 'codec') {
            final codec = data['msg'] as String;
            debugPrint('RTC HEVC codec: $codec');

            unawaited(
              channel.send(
                RTCDataChannelMessage(
                  jsonEncode({'type': 'start', 'msg': 'fmp4'}),
                ),
              ),
            );
          } else if (kind == 'recv') {
            unawaited(
              channel.send(
                RTCDataChannelMessage(
                  jsonEncode({'type': 'complete', 'msg': ''}),
                ),
              ),
            );
          }
        } catch (_) {
          fail('Formato HD non valido');
        }
      };
    } else {
      await peer.addTransceiver(
        kind: RTCRtpMediaType.RTCRtpMediaTypeVideo,
        init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly),
      );
    }
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
      int audioBytes = 0;
      for (final report in stats) {
        if (report.type == 'inbound-rtp') {
          if (report.values['kind'] == 'audio' ||
              report.values['mediaType'] == 'audio')
            audioBytes +=
                (num.tryParse('${report.values['bytesReceived']}') ?? 0)
                    .toInt();
          frames += (num.tryParse('${report.values['framesDecoded']}') ?? 0)
              .toInt();
        }
      }
      final player = hevcFeed?.controller;
      if (hevc && player != null && player.value.isInitialized) {
        // Live MP4 has no duration; the widget value clamps its position to 1 ms.
        frames = (await player.position)?.inMilliseconds ?? 0;
      }
      if (frames > _lastFrames) {
        _lastProgress = DateTime.now();
        debugPrint(
          'RTC progress: $frames size=${hevc ? player?.value.size : '${renderer.videoWidth}x${renderer.videoHeight}'} audio=$audioEnabled hevc=$hevc',
        );
      }
      if (audioEnabled && !_containerAudio)
        debugPrint('RTC audio received: $audioBytes bytes');
      _lastFrames = frames;
      if (DateTime.now().difference(_lastProgress).inSeconds >
          (highQuality ? 20 : 60))
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
    for (final track in _audioTracks) {
      track.enabled = false;
    }
    await _channel?.close();
    final peer = _peer;
    if (peer != null) {
      await peer.close();
      await peer.dispose();
    }
    await hevcFeed?.close();
    if (_initialized) {
      renderer.srcObject = null;
      await renderer.dispose();
    }
    dispose();
  }
}
