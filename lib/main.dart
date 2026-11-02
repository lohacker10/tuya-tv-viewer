import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:video_player/video_player.dart';

import 'rtc_feed.dart';

const _backend = MethodChannel('tuya_tv/backend');
const _eventChannel = EventChannel('tuya_tv/events');
const _regions = <String, String>{
  'eu': 'Europa',
  'us': 'Stati Uniti',
  'cn': 'Cina',
  'in': 'India',
  'sg': 'Singapore',
};

void main() => runApp(const TuyaTvApp());

class CameraInfo {
  const CameraInfo(this.id, this.name, this.online);

  final String id;
  final String name;
  final bool online;

  static CameraInfo fromJson(Map<String, dynamic> json) => CameraInfo(
    json['id'] as String,
    json['name'] as String,
    json['online'] as bool? ?? true,
  );
}

class _AvailableUpdate {
  const _AvailableUpdate(this.version, this.apkUrl, this.checksumUrl);

  final String version;
  final String apkUrl;
  final String checksumUrl;
}

class TuyaTvApp extends StatefulWidget {
  const TuyaTvApp({super.key});

  @override
  State<TuyaTvApp> createState() => _TuyaTvAppState();
}

class _TuyaTvAppState extends State<TuyaTvApp> with WidgetsBindingObserver {
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _countryCode = TextEditingController(text: '39');
  final _feeds = ValueNotifier<Map<String, RtcFeed>>({});
  int _generation = 0;
  bool _active = true;
  CameraInfo? _fullscreenCamera;
  bool _preferHd = true;
  int _selected = 0;
  final _focusNodes = List.generate(4, (_) => FocusNode());
  final _retries = <String, Timer>{};
  final _streamStatuses = ValueNotifier<Map<String, String>>({});
  StreamSubscription<dynamic>? _eventSubscription;
  List<CameraInfo> _cameras = const [];
  String _region = 'eu';
  String? _error;
  int _page = 0;
  bool _busy = true;
  bool _loading = false;
  bool _signedIn = false;
  bool _updatePromptShown = false;
  bool _pendingUpdatePermission = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(
      SystemChrome.setPreferredOrientations(const [
        DeviceOrientation.landscapeLeft,
        DeviceOrientation.landscapeRight,
      ]),
    );
    unawaited(
      SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky),
    );
    _eventSubscription = _eventChannel.receiveBroadcastStream().listen(
      _onEvents,
      onError: (_) {},
    );
    _restoreLogin();
  }

  Future<void> _restoreLogin() async {
    try {
      final cameras = await _backend.invokeMethod<String>('autoLogin');
      if (cameras != null) _setCameras(cameras);
    } on PlatformException catch (error) {
      _error = error.message ?? 'Accesso automatico non riuscito.';
    } finally {
      if (mounted) setState(() => _busy = false);
    }
    unawaited(_checkForUpdate());
  }

  void _onEvents(dynamic event) {
    if (event is! String) return;
    final events = jsonDecode(event) as List<dynamic>;
    for (final item in events) {
      final feed = _feeds.value[item['id']];
      if (feed != null && feed.handle == item['handle']) {
        feed.receive(item['type'] as String, item['value'] as String);
      }
    }
  }

  void _status(String id, String status) {
    if (mounted) _streamStatuses.value = {..._streamStatuses.value, id: status};
  }

  Future<void> _startCamera(CameraInfo camera, int generation) async {
    final fullscreen = _fullscreenCamera?.id == camera.id;
    final hd = fullscreen && _preferHd;
    if (!mounted || generation != _generation || !_active) return;
    if (!camera.online) {
      _status(camera.id, 'Telecamera offline');
      return;
    }
    try {
      _status(camera.id, 'Connessione WebRTC…');
      final raw = await _backend.invokeMethod<String>('prepareStream', {
        'id': camera.id,
        'quality': hd ? 'hd' : 'sd',
      });
      if (!mounted || generation != _generation || !_active) return;
      final config = jsonDecode(raw!) as Map<String, dynamic>;
      final old = _feeds.value[camera.id];
      if (old != null) await old.close();
      final feed = RtcFeed(
        camera.id,
        config['handle'] as String,
        (value) {
          if (generation == _generation) _status(camera.id, value);
        },
        () => _retry(camera, generation, hd: hd),
        audioEnabled: fullscreen,
        highQuality: hd,
        hevc: config['hevc'] == true,
      );
      _feeds.value = {..._feeds.value, camera.id: feed};
      await feed.start(config['iceServers'] as List<dynamic>);
    } catch (error) {
      if (generation == _generation && mounted) {
        _status(
          camera.id,
          error is PlatformException
              ? error.message ?? 'Connessione fallita'
              : 'Connessione video fallita',
        );
        _retry(camera, generation, hd: hd);
      }
    }
  }

  void _retry(CameraInfo camera, int generation, {bool hd = false}) {
    if (generation != _generation || !_active || !mounted) return;
    if (hd) {
      _preferHd = false;
      debugPrint('RTC HD unavailable; restoring SD with audio');
    }
    _retries[camera.id]?.cancel();
    _retries[camera.id] = Timer(
      Duration(seconds: hd ? 1 : 8),
      () => unawaited(_startCamera(camera, generation)),
    );
  }

  Future<int> _stopVideo() async {
    final generation = ++_generation;
    for (final timer in _retries.values) {
      timer.cancel();
    }
    _retries.clear();
    final feeds = _feeds.value.values.toList();
    _feeds.value = {};
    await Future.wait(feeds.map((feed) => feed.close()));
    await _backend.invokeMethod<void>('stopStreams');
    return generation;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) {
      _active = false;
      unawaited(_stopVideo());
    } else if (state == AppLifecycleState.resumed && !_active) {
      _active = true;
      if (_signedIn) unawaited(_showCurrent());
      if (_pendingUpdatePermission) {
        _pendingUpdatePermission = false;
        unawaited(_resumeUpdateAfterPermission());
      }
    }
  }

  void _setCameras(String json) {
    final decoded = jsonDecode(json) as List<dynamic>;
    final cameras = decoded
        .map((item) => CameraInfo.fromJson(item as Map<String, dynamic>))
        .toList();
    final ordered = cameras.indexed.toList()
      ..sort((a, b) {
        final rankA = _directionRank(a.$2.name);
        final rankB = _directionRank(b.$2.name);
        return rankA == rankB ? a.$1.compareTo(b.$1) : rankA.compareTo(rankB);
      });
    _cameras = ordered.map((entry) => entry.$2).toList(growable: false);
    _streamStatuses.value = {};
    _signedIn = true;
    _page = 0;
    if (_cameras.isNotEmpty) unawaited(_showCurrent());
  }

  int _directionRank(String name) {
    final words = name
        .toLowerCase()
        .replaceAll('à', 'a')
        .replaceAll('è', 'e')
        .replaceAll('é', 'e')
        .replaceAll('ì', 'i')
        .replaceAll('ò', 'o')
        .replaceAll('ù', 'u')
        .split(RegExp(r'[^a-z0-9]+'))
        .where((word) => word.isNotEmpty)
        .toSet();
    final north =
        words.contains('nord') ||
        words.contains('north') ||
        words.contains('n');
    final east =
        words.contains('est') || words.contains('east') || words.contains('e');
    final northEast =
        (north && east) ||
        words.contains('nordest') ||
        words.contains('northeast') ||
        words.contains('ne');
    if (north && !northEast) return 0;
    if (northEast) return 1;
    if (east) return 2;
    if (words.contains('sud') || words.contains('south') || words.contains('s'))
      return 3;
    return 4;
  }

  Future<void> _checkForUpdate() async {
    if (_updatePromptShown || !mounted) return;
    try {
      final raw = await _backend.invokeMethod<String>('checkForUpdate');
      if (raw == null || !mounted || _updatePromptShown) return;
      final data = jsonDecode(raw) as Map<String, dynamic>;
      final update = _AvailableUpdate(
        data['version'] as String,
        data['apkUrl'] as String,
        data['checksumUrl'] as String,
      );
      _updatePromptShown = true;
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Aggiornamento disponibile'),
          content: Text('È disponibile Telecamere ${update.version}.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Più tardi'),
            ),
            FilledButton.icon(
              onPressed: () {
                Navigator.pop(dialogContext);
                unawaited(_installUpdate(update));
              },
              icon: const Icon(Icons.download),
              label: const Text('Aggiorna'),
            ),
          ],
        ),
      );
    } on PlatformException {
      // GitHub update checks are optional and never block app startup.
    } on FormatException {
      // Ignore malformed release metadata.
    }
  }

  Future<void> _installUpdate(_AvailableUpdate update) async {
    try {
      final started = await _backend.invokeMethod<bool>('installUpdate', {
        'version': update.version,
        'apkUrl': update.apkUrl,
        'checksumUrl': update.checksumUrl,
      });
      if (started == false) _pendingUpdatePermission = true;
    } on PlatformException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.message ?? 'Aggiornamento non riuscito.')),
      );
    }
  }

  Future<void> _resumeUpdateAfterPermission() async {
    try {
      final allowed = await _backend.invokeMethod<bool>('canInstallUpdates');
      if (allowed == true) {
        _updatePromptShown = false;
        await _checkForUpdate();
      }
    } on PlatformException {
      // A later app launch retries the optional update check.
    }
  }

  Future<void> _login() async {
    if (_username.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = 'Inserisci email/telefono e password Tuya.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final json = await _backend.invokeMethod<String>('login', {
        'username': _username.text.trim(),
        'password': _password.text,
        'countryCode': _countryCode.text.trim().isEmpty
            ? '39'
            : _countryCode.text.trim(),
        'region': _region,
      });
      if (json == null)
        throw PlatformException(
          code: 'EMPTY_RESPONSE',
          message: 'Risposta vuota dal servizio Tuya.',
        );
      _setCameras(json);
    } on PlatformException catch (error) {
      _error = error.message ?? 'Accesso Tuya non riuscito.';
    } on FormatException {
      _error = 'Risposta Tuya non valida.';
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _showCurrent() async {
    final generation = await _stopVideo();
    if (generation != _generation || !_active || !mounted) return;
    final fullscreen = _fullscreenCamera;
    final cameras = fullscreen == null
        ? _cameras.skip(_page * 4).take(4)
        : [fullscreen];
    for (final camera in cameras) {
      if (generation != _generation || !_active || !mounted) return;
      await _startCamera(camera, generation);
    }
  }

  void _openCamera(CameraInfo camera, int index) {
    _selected = index;
    setState(() {
      _fullscreenCamera = camera;
      _preferHd = true;
    });
    unawaited(_showCurrent());
  }

  void _returnToGrid() {
    setState(() => _fullscreenCamera = null);
    unawaited(_showCurrent());
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _focusNodes[_selected].requestFocus();
    });
  }

  Future<void> _changePage(int page) async {
    if (page < 0 || page >= (_cameras.length / 4).ceil()) return;
    setState(() {
      _page = page;
      _selected = 0;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _focusNodes[0].requestFocus();
    });
    await _showCurrent();
  }

  Future<void> _logout() async {
    setState(() => _loading = true);
    try {
      await _stopVideo();
      await _backend.invokeMethod<void>('logout');
      _streamStatuses.value = {};
      _username.clear();
      _password.clear();
      setState(() {
        _cameras = const [];
        _signedIn = false;
        _error = null;
      });
    } on PlatformException catch (error) {
      setState(() => _error = error.message ?? 'Uscita non riuscita.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _eventSubscription?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    for (final timer in _retries.values) {
      timer.cancel();
    }
    for (final feed in _feeds.value.values) {
      unawaited(feed.close());
    }
    unawaited(_backend.invokeMethod<void>('stopStreams'));
    _feeds.dispose();
    _streamStatuses.dispose();
    _username.dispose();
    _password.dispose();
    _countryCode.dispose();
    for (final node in _focusNodes) {
      node.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Telecamere',
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff33d6c1),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xff090d12),
        useMaterial3: true,
      ),
      home: _busy
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : _signedIn
          ? Builder(builder: _cameraWall)
          : _loginPage(),
    );
  }

  Widget _loginPage() {
    return Scaffold(
      body: Center(
        child: SizedBox(
          width: 520,
          child: AutofillGroup(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Icon(
                  Icons.videocam_rounded,
                  size: 58,
                  color: Color(0xff33d6c1),
                ),
                const SizedBox(height: 14),
                Text(
                  'TELECAMERE',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: 2,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Accedi per vedere le telecamere del tuo account',
                  textAlign: TextAlign.center,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyLarge?.copyWith(color: Colors.white70),
                ),
                const SizedBox(height: 28),
                TextField(
                  controller: _username,
                  autofocus: true,
                  keyboardType: TextInputType.text,
                  textInputAction: TextInputAction.next,
                  autofillHints: const [AutofillHints.username],
                  decoration: const InputDecoration(
                    labelText: 'Email o telefono Tuya',
                    prefixIcon: Icon(Icons.person_outline),
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _password,
                  obscureText: true,
                  textInputAction: TextInputAction.done,
                  autofillHints: const [AutofillHints.password],
                  onSubmitted: (_) => _login(),
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    prefixIcon: Icon(Icons.lock_outline),
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    SizedBox(
                      width: 150,
                      child: TextField(
                        controller: _countryCode,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Prefisso Paese',
                          prefixText: '+',
                          border: OutlineInputBorder(),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        initialValue: _region,
                        decoration: const InputDecoration(
                          labelText: 'Regione account',
                          border: OutlineInputBorder(),
                        ),
                        items: _regions.entries
                            .map(
                              (entry) => DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                            )
                            .toList(),
                        onChanged: (value) =>
                            setState(() => _region = value ?? 'eu'),
                      ),
                    ),
                  ],
                ),
                if (_error != null) ...[
                  const SizedBox(height: 14),
                  Text(
                    _error!,
                    style: const TextStyle(color: Color(0xffff8a80)),
                    textAlign: TextAlign.center,
                  ),
                ],
                const SizedBox(height: 22),
                FilledButton.icon(
                  onPressed: _loading ? null : _login,
                  icon: _loading
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.login),
                  label: Text(_loading ? 'Accesso in corso…' : 'Accedi'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 18),
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Le credenziali vengono cifrate e salvate su questo dispositivo per il login automatico.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.white54, fontSize: 12),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _cameraWall(BuildContext context) {
    final fullscreen = _fullscreenCamera;
    final visible = _cameras.skip(_page * 4).take(4).toList();
    return PopScope(
      canPop: fullscreen == null,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && _fullscreenCamera != null) _returnToGrid();
      },
      child: Scaffold(
        backgroundColor: Colors.black,
        body: fullscreen != null
            ? CameraVideo(
                camera: fullscreen,
                feeds: _feeds,
                statuses: _streamStatuses,
              )
            : Focus(
                onKeyEvent: (_, event) {
                  if (event is! KeyDownEvent) return KeyEventResult.ignored;
                  final key = event.logicalKey;
                  if (key == LogicalKeyboardKey.contextMenu) {
                    unawaited(
                      showDialog<void>(
                        context: context,
                        builder: (context) => SimpleDialog(
                          children: [
                            SimpleDialogOption(
                              onPressed: () {
                                Navigator.pop(context);
                                unawaited(_showCurrent());
                              },
                              child: const Text('Riconnetti'),
                            ),
                            SimpleDialogOption(
                              onPressed: () {
                                Navigator.pop(context);
                                unawaited(_logout());
                              },
                              child: const Text('Disconnetti account'),
                            ),
                          ],
                        ),
                      ),
                    );
                    return KeyEventResult.handled;
                  }
                  if (key == LogicalKeyboardKey.pageDown ||
                      key == LogicalKeyboardKey.pageUp) {
                    unawaited(
                      _changePage(
                        _page + (key == LogicalKeyboardKey.pageDown ? 1 : -1),
                      ),
                    );
                    return KeyEventResult.handled;
                  }
                  return KeyEventResult.ignored;
                },
                child: LayoutBuilder(
                  builder: (context, size) => GridView.builder(
                    padding: EdgeInsets.zero,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: 4,
                    gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 2,
                      childAspectRatio: size.maxWidth / size.maxHeight,
                    ),
                    itemBuilder: (context, index) {
                      if (index >= visible.length)
                        return const ColoredBox(color: Colors.black);
                      return CameraTile(
                        camera: visible[index],
                        feeds: _feeds,
                        statuses: _streamStatuses,
                        focusNode: _focusNodes[index],
                        autofocus: index == _selected,
                        onSelected: () => _openCamera(visible[index], index),
                        onMove: (key) {
                          final next = switch (key) {
                            LogicalKeyboardKey.arrowLeft =>
                              index % 2 == 1 ? index - 1 : index,
                            LogicalKeyboardKey.arrowRight =>
                              index % 2 == 0 ? index + 1 : index,
                            LogicalKeyboardKey.arrowUp =>
                              index >= 2 ? index - 2 : index,
                            LogicalKeyboardKey.arrowDown =>
                              index < 2 ? index + 2 : index,
                            _ => index,
                          };
                          if (next < visible.length) {
                            _selected = next;
                            _focusNodes[next].requestFocus();
                          }
                        },
                      );
                    },
                  ),
                ),
              ),
      ),
    );
  }
}

class CameraTile extends StatelessWidget {
  const CameraTile({
    required this.camera,
    required this.feeds,
    required this.statuses,
    required this.onSelected,
    required this.onMove,
    required this.focusNode,
    this.autofocus = false,
    super.key,
  });
  final CameraInfo camera;
  final ValueListenable<Map<String, RtcFeed>> feeds;
  final ValueListenable<Map<String, String>> statuses;
  final VoidCallback onSelected;
  final void Function(LogicalKeyboardKey) onMove;
  final FocusNode focusNode;
  final bool autofocus;

  @override
  Widget build(BuildContext context) => Focus(
    focusNode: focusNode,
    autofocus: autofocus,
    onKeyEvent: (_, event) {
      if (event is! KeyDownEvent) return KeyEventResult.ignored;
      final key = event.logicalKey;
      if ({
        LogicalKeyboardKey.select,
        LogicalKeyboardKey.enter,
        LogicalKeyboardKey.numpadEnter,
        LogicalKeyboardKey.space,
      }.contains(key)) {
        onSelected();
        return KeyEventResult.handled;
      }
      if ({
        LogicalKeyboardKey.arrowLeft,
        LogicalKeyboardKey.arrowRight,
        LogicalKeyboardKey.arrowUp,
        LogicalKeyboardKey.arrowDown,
      }.contains(key)) {
        onMove(key);
        return KeyEventResult.handled;
      }
      return KeyEventResult.ignored;
    },
    child: Builder(
      builder: (context) => Semantics(
        label: camera.name,
        button: true,
        selected: Focus.of(context).hasFocus,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onSelected,
          child: Stack(
            fit: StackFit.expand,
            children: [
              CameraVideo(
                camera: camera,
                feeds: feeds,
                statuses: statuses,
                cover: true,
              ),
              if (Focus.of(context).hasFocus)
                IgnorePointer(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      border: Border.all(
                        color: const Color(0xff33d6c1),
                        width: 4,
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    ),
  );
}

class CameraVideo extends StatelessWidget {
  const CameraVideo({
    required this.camera,
    required this.feeds,
    required this.statuses,
    this.cover = false,
    super.key,
  });
  final CameraInfo camera;
  final ValueListenable<Map<String, RtcFeed>> feeds;
  final ValueListenable<Map<String, String>> statuses;
  final bool cover;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: Listenable.merge([feeds, statuses]),
    builder: (context, _) {
      final feed = feeds.value[camera.id];
      final status = statuses.value[camera.id] ?? 'Connessione…';
      Widget placeholder() => Semantics(
        label: status,
        child: Center(
          child:
              camera.online &&
                  !status.toLowerCase().contains('fallit') &&
                  !status.contains('non ')
              ? const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.videocam_off_outlined, color: Colors.white38),
        ),
      );
      if (feed == null) return placeholder();
      return AnimatedBuilder(
        animation: Listenable.merge([feed.renderer, feed]),
        builder: (context, _) => Stack(
          fit: StackFit.expand,
          children: [
            if (feed.hevcFeed?.controller?.value.isInitialized == true)
              FittedBox(
                fit: cover ? BoxFit.cover : BoxFit.contain,
                child: SizedBox(
                  width: feed.hevcFeed!.controller!.value.size.width,
                  height: feed.hevcFeed!.controller!.value.size.height,
                  child: VideoPlayer(feed.hevcFeed!.controller!),
                ),
              )
            else if (!feed.hevc && feed.renderer.textureId != null)
              RTCVideoView(
                feed.renderer,
                objectFit: cover
                    ? RTCVideoViewObjectFit.RTCVideoViewObjectFitCover
                    : RTCVideoViewObjectFit.RTCVideoViewObjectFitContain,
              ),
            if (feed.hevc
                ? feed.hevcFeed?.controller?.value.isInitialized != true
                : feed.renderer.videoWidth == 0)
              placeholder(),
          ],
        ),
      );
    },
  );
}
