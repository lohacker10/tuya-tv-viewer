import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

const _backend = MethodChannel('tuya_tv/backend');
const _frameChannel = EventChannel('tuya_tv/frames');
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

class TuyaTvApp extends StatefulWidget {
  const TuyaTvApp({super.key});

  @override
  State<TuyaTvApp> createState() => _TuyaTvAppState();
}

class _TuyaTvAppState extends State<TuyaTvApp> {
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _countryCode = TextEditingController(text: '39');
  final _frames = ValueNotifier<Map<String, Uint8List>>({});
  final _streamStatuses = ValueNotifier<Map<String, String>>({});
  StreamSubscription<dynamic>? _frameSubscription;
  List<CameraInfo> _cameras = const [];
  String _region = 'eu';
  String? _error;
  int _page = 0;
  bool _busy = true;
  bool _loading = false;
  bool _signedIn = false;

  @override
  void initState() {
    super.initState();
    unawaited(
      SystemChrome.setPreferredOrientations(const [
        DeviceOrientation.landscapeLeft,
        DeviceOrientation.landscapeRight,
      ]),
    );
    unawaited(
      SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky),
    );
    _frameSubscription = _frameChannel.receiveBroadcastStream().listen(
      _onFrames,
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
  }

  void _onFrames(dynamic event) {
    if (event is! Map) return;
    final rawStatuses = event['statuses'];
    if (rawStatuses is Map) {
      final updatedStatuses = Map<String, String>.fromEntries(
        rawStatuses.entries
            .where((entry) => entry.key is String && entry.value is String)
            .map((entry) => MapEntry(entry.key as String, entry.value as String)),
      );
      if (!mapEquals(updatedStatuses, _streamStatuses.value)) {
        _streamStatuses.value = updatedStatuses;
      }
    }
    final rawFrames = event['frames'];
    if (rawFrames is! Map) return;
    final updated = Map<String, Uint8List>.of(_frames.value);
    for (final entry in rawFrames.entries) {
      if (entry.key is String && entry.value is Uint8List) {
        updated[entry.key as String] = entry.value as Uint8List;
      }
    }
    _frames.value = updated;
  }

  void _setCameras(String json) {
    final decoded = jsonDecode(json) as List<dynamic>;
    _cameras = decoded
        .map((item) => CameraInfo.fromJson(item as Map<String, dynamic>))
        .toList(growable: false);
    _streamStatuses.value = {};
    _signedIn = true;
    _page = 0;
    if (_cameras.isNotEmpty) unawaited(_showPage(0));
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

  Future<void> _showPage(int page) async {
    final start = page * 4;
    final ids = _cameras
        .skip(start)
        .take(4)
        .map((camera) => camera.id)
        .toList();
    try {
      await _backend.invokeMethod<void>('startStreams', ids);
    } on PlatformException catch (error) {
      if (mounted)
        setState(
          () => _error = error.message ?? 'Avvio telecamere non riuscito.',
        );
    }
  }

  Future<void> _changePage(int page) async {
    if (page < 0 || page >= (_cameras.length / 4).ceil()) return;
    setState(() => _page = page);
    await _showPage(page);
  }

  Future<void> _logout() async {
    setState(() => _loading = true);
    try {
      await _backend.invokeMethod<void>('logout');
      _frames.value = {};
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
    _frameSubscription?.cancel();
    _frames.dispose();
    _streamStatuses.dispose();
    _username.dispose();
    _password.dispose();
    _countryCode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Tuya TV',
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
          ? _cameraWall()
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
                  'TUYA TV',
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

  Widget _cameraWall() {
    final pageCount = (_cameras.length / 4).ceil();
    final first = _page * 4;
    final visible = _cameras.skip(first).take(4).toList();
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'TUYA TV',
          style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: 1.5),
        ),
        actions: [
          if (pageCount > 1)
            Center(
              child: Text(
                '${_page + 1} / $pageCount',
                style: const TextStyle(color: Colors.white70),
              ),
            ),
          IconButton(
            tooltip: 'Esci',
            onPressed: _loading ? null : _logout,
            icon: const Icon(Icons.logout),
          ),
          const SizedBox(width: 12),
        ],
      ),
      body: _cameras.isEmpty
          ? const Center(
              child: Text(
                'Nessuna telecamera Tuya compatibile trovata nell’account.',
              ),
            )
          : Padding(
              padding: const EdgeInsets.fromLTRB(24, 4, 24, 18),
              child: Column(
                children: [
                  Expanded(
                    child: GridView.builder(
                      itemCount: visible.length,
                      physics: const NeverScrollableScrollPhysics(),
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: 2,
                            crossAxisSpacing: 16,
                            mainAxisSpacing: 16,
                            childAspectRatio: 16 / 6.1,
                          ),
                      itemBuilder: (context, index) => CameraTile(
                        camera: visible[index],
                        frames: _frames,
                        statuses: _streamStatuses,
                        autofocus: index == 0,
                        onSelected: () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                            builder: (_) => CameraFullScreen(
                              camera: visible[index],
                              frames: _frames,
                              statuses: _streamStatuses,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  if (_error != null)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        _error!,
                        style: const TextStyle(color: Color(0xffff8a80)),
                      ),
                    )
                  else
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'Seleziona una telecamera · BACK per tornare',
                        style: TextStyle(color: Colors.white54),
                      ),
                    ),
                  if (pageCount > 1)
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        IconButton(
                          tooltip: 'Pagina precedente',
                          onPressed: _page > 0
                              ? () => _changePage(_page - 1)
                              : null,
                          icon: const Icon(Icons.chevron_left),
                        ),
                        IconButton(
                          tooltip: 'Pagina successiva',
                          onPressed: _page + 1 < pageCount
                              ? () => _changePage(_page + 1)
                              : null,
                          icon: const Icon(Icons.chevron_right),
                        ),
                      ],
                    ),
                ],
              ),
            ),
    );
  }
}

class CameraTile extends StatelessWidget {
  const CameraTile({
    required this.camera,
    required this.frames,
    required this.statuses,
    required this.onSelected,
    this.autofocus = false,
    super.key,
  });

  final CameraInfo camera;
  final ValueListenable<Map<String, Uint8List>> frames;
  final ValueListenable<Map<String, String>> statuses;
  final VoidCallback onSelected;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    return Focus(
      autofocus: autofocus,
      onKeyEvent: (node, event) {
        if (event is KeyDownEvent &&
            {
              LogicalKeyboardKey.select,
              LogicalKeyboardKey.enter,
              LogicalKeyboardKey.numpadEnter,
              LogicalKeyboardKey.space,
            }.contains(event.logicalKey)) {
          onSelected();
          return KeyEventResult.handled;
        }
        return KeyEventResult.ignored;
      },
      child: Builder(
        builder: (context) {
          final focused = Focus.of(context).hasFocus;
          return Material(
            color: const Color(0xff151c24),
            shape: RoundedRectangleBorder(
              side: BorderSide(
                color: focused
                    ? const Color(0xff33d6c1)
                    : const Color(0xff26313d),
                width: focused ? 3 : 1,
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: onSelected,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  AnimatedBuilder(
                    animation: Listenable.merge([frames, statuses]),
                    builder: (context, _) {
                      final frame = frames.value[camera.id];
                      if (frame == null)
                        return Center(
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Icon(
                                  Icons.videocam_off_outlined,
                                  size: 42,
                                  color: Colors.white38,
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  statuses.value[camera.id] ??
                                      (camera.online
                                          ? 'Connessione P2P…'
                                          : 'Telecamera offline'),
                                  textAlign: TextAlign.center,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(color: Colors.white70),
                                ),
                              ],
                            ),
                          ),
                        );
                      return Image.memory(
                        frame,
                        gaplessPlayback: true,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                      );
                    },
                  ),
                  Align(
                    alignment: Alignment.bottomCenter,
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                      color: Colors.black.withValues(alpha: 0.66),
                      child: Row(
                        children: [
                          Icon(
                            Icons.circle,
                            size: 9,
                            color: camera.online
                                ? const Color(0xff54e39a)
                                : Colors.grey,
                          ),
                          const SizedBox(width: 9),
                          Expanded(
                            child: Text(
                              camera.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                          const Icon(
                            Icons.open_in_full,
                            size: 17,
                            color: Colors.white70,
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class CameraFullScreen extends StatelessWidget {
  const CameraFullScreen({
    required this.camera,
    required this.frames,
    required this.statuses,
    super.key,
  });

  final CameraInfo camera;
  final ValueListenable<Map<String, Uint8List>> frames;
  final ValueListenable<Map<String, String>> statuses;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(camera.name),
        leading: const Focus(autofocus: true, child: BackButton()),
      ),
      body: Center(
        child: AnimatedBuilder(
          animation: Listenable.merge([frames, statuses]),
          builder: (context, _) {
            final frame = frames.value[camera.id];
            if (frame == null) {
              final status = statuses.value[camera.id] ??
                  (camera.online
                      ? 'Connessione P2P…'
                      : 'Telecamera offline');
              return Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (status == 'Connessione P2P…')
                    const CircularProgressIndicator(),
                  if (status != 'Connessione P2P…')
                    const Icon(Icons.videocam_off_outlined, size: 48),
                  const SizedBox(height: 18),
                  Text(status, textAlign: TextAlign.center),
                ],
              );
            }
            return InteractiveViewer(
              child: Image.memory(
                frame,
                gaplessPlayback: true,
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) =>
                    const Text('Immagine non disponibile'),
              ),
            );
          },
        ),
      ),
    );
  }
}
