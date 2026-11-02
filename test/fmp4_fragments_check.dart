import 'dart:typed_data';
import '../lib/fmp4_fragments.dart';
import '../lib/fmp4_timeline.dart';

void check(bool condition, String message) {
  if (!condition) throw StateError(message);
}

void rejects(void Function() action) {
  try {
    action();
  } on FormatException {
    return;
  }
  throw StateError('Invalid fragment accepted');
}

void main() {
  final parser = Fmp4Fragments();
  check(
    parser.payload(Uint8List.fromList([255, 255, 2, 1, 10, 11])).join(',') ==
        '10,11',
    'Header was not removed',
  );
  check(
    parser.payload(Uint8List.fromList([255, 255, 2, 2, 12])).single == 12,
    'Second fragment lost',
  );
  check(
    parser.payload(Uint8List.fromList([0, 0, 1, 1, 13])).single == 13,
    'Segment rollover failed',
  );
  rejects(() => Fmp4Fragments().payload(Uint8List.fromList([0, 0, 2, 2, 1])));
  rejects(() => Fmp4Fragments().payload(Uint8List.fromList([0, 0, 0, 0, 1])));
  rejects(() => Fmp4Fragments().payload(Uint8List(4)));
  final incomplete = Fmp4Fragments();
  incomplete.payload(Uint8List.fromList([0, 1, 3, 1, 1]));
  rejects(() => incomplete.payload(Uint8List.fromList([0, 1, 3, 3, 1])));
  final changedSegment = Fmp4Fragments();
  changedSegment.payload(Uint8List.fromList([0, 1, 2, 1, 1]));
  rejects(() => changedSegment.payload(Uint8List.fromList([0, 2, 2, 2, 1])));
  checkTimeline();
  checkAacClock();
  print('MP4 fragment and timeline checks passed');
}

Uint8List box(String type, List<int> payload) {
  final result = Uint8List(8 + payload.length);
  ByteData.sublistView(result).setUint32(0, result.length);
  result.setAll(4, type.codeUnits);
  result.setAll(8, payload);
  return result;
}

Uint8List u32(int value) =>
    (ByteData(4)..setUint32(0, value)).buffer.asUint8List();
Uint8List u64(int value) =>
    (ByteData(8)..setUint64(0, value)).buffer.asUint8List();

void checkTimeline() {
  Uint8List fragment(int timestamp) => box(
    'moof',
    box('traf', [
      ...box('tfhd', [0, 0, 0, 8, ...u32(1), ...u32(1024)]),
      ...box('tfdt', [1, 0, 0, 0, ...u64(timestamp)]),
      ...box('trun', [0, 0, 0, 0, ...u32(2)]),
    ]),
  );
  final media = box('mdat', [5, 6, 7, 8, 9]);
  final source = Uint8List.fromList([
    ...fragment(1000000000),
    ...media,
    ...fragment(1000092160),
    ...media,
  ]);
  final parser = Fmp4Timeline();
  final output = <Uint8List>[];
  for (var i = 0; i < source.length; i += 3) {
    output.addAll(
      parser.push(
        Uint8List.sublistView(
          source,
          i,
          i + 3 > source.length ? source.length : i + 3,
        ),
      ),
    );
  }
  final first = String.fromCharCodes(output[0]).indexOf('tfdt');
  final second = String.fromCharCodes(output[2]).indexOf('tfdt');
  check(
    ByteData.sublistView(output[0]).getUint64(first + 8) == 0,
    'First timestamp was not rebased',
  );
  check(
    ByteData.sublistView(output[2]).getUint64(second + 8) == 2048,
    'Audio timestamp jump was not repaired',
  );
  check(
    output[1].join(',') == media.join(',') &&
        output[3].join(',') == media.join(','),
    'Media bytes changed',
  );
  rejects(
    () => Fmp4Timeline().push(
      Uint8List.fromList([0, 0, 0, 1, 109, 100, 97, 116]),
    ),
  );
}

void checkAacClock() {
  final audioEntry = Uint8List(28);
  ByteData.sublistView(audioEntry).setUint32(24, 8000 << 16);
  final init = box(
    'moov',
    box('trak', [
      ...box('tkhd', [0, 0, 0, 0, ...u32(0), ...u32(0), ...u32(2)]),
      ...box('mdia', [
        ...box('mdhd', [0, 0, 0, 0, ...u32(0), ...u32(0), ...u32(1000)]),
        ...box('hdlr', [0, 0, 0, 0, ...u32(0), ...'soun'.codeUnits]),
        ...box(
          'minf',
          box(
            'stbl',
            box('stsd', [0, 0, 0, 0, ...u32(1), ...box('mp4a', audioEntry)]),
          ),
        ),
      ]),
    ]),
  );
  Uint8List fragment(int time) => box(
    'moof',
    box('traf', [
      ...box('tfhd', [0, 0, 0, 8, ...u32(2), ...u32(11520)]),
      ...box('tfdt', [1, 0, 0, 0, ...u64(time)]),
      ...box('trun', [0, 0, 0, 0, ...u32(7)]),
    ]),
  );
  final parser = Fmp4Timeline();
  parser.push(init);
  final first = parser.push(fragment(0)).single;
  final second = parser.push(fragment(80640)).single;
  final durationOffset = String.fromCharCodes(first).indexOf('tfhd') + 12;
  final timeOffset = String.fromCharCodes(second).indexOf('tfdt') + 8;
  check(
    ByteData.sublistView(first).getUint32(durationOffset) == 128,
    'AAC sample duration uses the wrong clock',
  );
  check(
    ByteData.sublistView(second).getUint64(timeOffset) == 896,
    'AAC decode time did not follow repaired samples',
  );
  check(
    parser.push(box('sidx', List.filled(24, 0))).isEmpty,
    'Stale seek index leaked into the live stream',
  );
}
