import 'dart:typed_data';

/// Some Tuya muxers use wall-clock jumps in tfdt while sample durations are valid.
/// Keep each track continuous using the durations carried by its own samples.
class Fmp4Timeline {
  Uint8List _pending = Uint8List(0);
  final _defaults = <int, int>{};
  final _audioDurations = <int, int>{};
  final _next = <int, int>{};

  List<Uint8List> push(Uint8List bytes) {
    final joined = Uint8List(_pending.length + bytes.length)
      ..setAll(0, _pending)
      ..setAll(_pending.length, bytes);
    final output = <Uint8List>[];
    var offset = 0;
    while (joined.length - offset >= 8) {
      final view = ByteData.sublistView(joined);
      final size = view.getUint32(offset);
      if (size < 8 || size > 16 * 1024 * 1024)
        throw const FormatException('Invalid MP4 box size');
      if (joined.length - offset < size) break;
      final box = Uint8List.fromList(
        Uint8List.sublistView(joined, offset, offset + size),
      );
      final type = String.fromCharCodes(box.sublist(4, 8));
      if (type == 'moov') {
        _readAudioTracks(box);
        _readDefaults(box, 8, box.length);
      }
      if (type == 'moof') _retime(box);
      // Seek indices describe the old clocks; they are unnecessary for live playback.
      if (type != 'sidx') output.add(box);
      offset += size;
    }
    _pending = Uint8List.fromList(Uint8List.sublistView(joined, offset));
    if (_pending.length > 16 * 1024 * 1024)
      throw const FormatException('MP4 box too large');
    return output;
  }

  Iterable<(String, int, int)> _boxes(
    Uint8List data,
    int start,
    int end,
  ) sync* {
    final view = ByteData.sublistView(data);
    for (var offset = start; offset + 8 <= end;) {
      final size = view.getUint32(offset);
      if (size < 8 || offset + size > end)
        throw const FormatException('Invalid MP4 child box');
      yield (
        String.fromCharCodes(data.sublist(offset + 4, offset + 8)),
        offset,
        offset + size,
      );
      offset += size;
    }
  }

  void _readDefaults(Uint8List data, int start, int end) {
    final view = ByteData.sublistView(data);
    for (final (type, offset, limit) in _boxes(data, start, end)) {
      if (type == 'mvex') _readDefaults(data, offset + 8, limit);
      if (type == 'trex' && limit - offset >= 32) {
        final track = view.getUint32(offset + 12);
        var duration = view.getUint32(offset + 20);
        final expected = _audioDurations[track];
        if (expected != null && duration > expected * 2) {
          duration = expected;
          view.setUint32(offset + 20, duration);
        }
        _defaults[track] = duration;
      }
    }
  }

  Iterable<(String, int, int)> _descendants(
    Uint8List data,
    int start,
    int end,
  ) sync* {
    for (final entry in _boxes(data, start, end)) {
      yield entry;
      if (const {'mdia', 'minf', 'stbl'}.contains(entry.$1))
        yield* _descendants(data, entry.$2 + 8, entry.$3);
    }
  }

  void _readAudioTracks(Uint8List data) {
    final view = ByteData.sublistView(data);
    for (final (type, start, end) in _boxes(data, 8, data.length)) {
      if (type != 'trak') continue;
      int? track;
      int? scale;
      int? sampleRate;
      var audio = false;
      for (final (kind, offset, limit) in _descendants(data, start + 8, end)) {
        if (kind == 'tkhd' || kind == 'mdhd') {
          if (limit - offset < 12)
            throw const FormatException('Truncated MP4 track header');
          final cursor = offset + (data[offset + 8] == 1 ? 28 : 20);
          if (cursor + 4 > limit)
            throw const FormatException('Truncated MP4 track');
          if (kind == 'tkhd')
            track = view.getUint32(cursor);
          else
            scale = view.getUint32(cursor);
        } else if (kind == 'hdlr' && limit - offset >= 20) {
          audio =
              String.fromCharCodes(data.sublist(offset + 16, offset + 20)) ==
              'soun';
        } else if (kind == 'stsd' && limit - offset >= 16) {
          for (final (codec, begin, finish) in _boxes(
            data,
            offset + 16,
            limit,
          )) {
            if (codec == 'mp4a' && finish - begin >= 36)
              sampleRate = view.getUint32(begin + 32) >> 16;
          }
        }
      }
      // Tuya AAC-LC frames carry 1024 samples; only repair exact clock conversions.
      if (audio &&
          track != null &&
          scale != null &&
          scale > 0 &&
          sampleRate != null &&
          sampleRate > 0 &&
          (scale * 1024) % sampleRate == 0) {
        _audioDurations[track] = scale * 1024 ~/ sampleRate;
      }
    }
  }

  void _retime(Uint8List data) {
    final view = ByteData.sublistView(data);
    for (final (kind, begin, end) in _boxes(data, 8, data.length)) {
      if (kind != 'traf') continue;
      final boxes = _boxes(data, begin + 8, end).toList();
      int? track;
      int? decodeOffset;
      var version = 0;
      var defaultDuration = 0;
      for (final (type, offset, limit) in boxes) {
        if (type == 'tfhd' && limit - offset >= 16) {
          final flags = view.getUint32(offset + 8) & 0xffffff;
          track = view.getUint32(offset + 12);
          defaultDuration = _defaults[track] ?? 0;
          var cursor = offset + 16;
          if (flags & 1 != 0) cursor += 8;
          if (flags & 2 != 0) cursor += 4;
          if (flags & 8 != 0) {
            if (cursor + 4 > limit)
              throw const FormatException('Truncated tfhd');
            defaultDuration = view.getUint32(cursor);
            final expected = _audioDurations[track];
            if (expected != null && defaultDuration > expected * 2) {
              defaultDuration = expected;
              view.setUint32(cursor, expected);
            }
          }
        } else if (type == 'tfdt' && limit - offset >= 16) {
          version = data[offset + 8];
          decodeOffset = offset + 12;
          if (version > 1 || decodeOffset + (version == 1 ? 8 : 4) > limit)
            throw const FormatException('Truncated tfdt');
        }
      }
      if (track == null || decodeOffset == null) {
        continue;
      }
      var duration = 0;
      for (final (type, offset, limit) in boxes) {
        if (type != 'trun' || limit - offset < 16) continue;
        final flags = view.getUint32(offset + 8) & 0xffffff;
        final count = view.getUint32(offset + 12);
        if (count > 100000) throw const FormatException('Too many MP4 samples');
        var cursor = offset + 16;
        if (flags & 1 != 0) cursor += 4;
        if (flags & 4 != 0) cursor += 4;
        for (var i = 0; i < count; i++) {
          var sampleDuration = defaultDuration;
          if (flags & 0x100 != 0) {
            if (cursor + 4 > limit)
              throw const FormatException('Truncated trun');
            sampleDuration = view.getUint32(cursor);
            final expected = _audioDurations[track];
            if (expected != null && sampleDuration > expected * 2) {
              sampleDuration = expected;
              view.setUint32(cursor, expected);
            }
            cursor += 4;
          }
          duration += sampleDuration;
          if (flags & 0x200 != 0) cursor += 4;
          if (flags & 0x400 != 0) cursor += 4;
          if (flags & 0x800 != 0) cursor += 4;
          if (cursor > limit)
            throw const FormatException('Truncated MP4 samples');
        }
      }
      if (duration == 0) continue;
      final time = _next[track] ?? 0;
      if (version == 1)
        view.setUint64(decodeOffset, time);
      else
        view.setUint32(decodeOffset, time & 0xffffffff);
      _next[track] = time + duration;
    }
  }
}
