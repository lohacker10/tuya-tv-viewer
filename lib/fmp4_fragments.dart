import 'dart:typed_data';

/// Tuya prefixes each ordered SCTP fragment with segment/count/sequence bytes.
class Fmp4Fragments {
  int? _segment;
  int _next = 1;
  int _count = 0;

  Uint8List payload(Uint8List data) {
    if (data.length <= 4) throw const FormatException('Empty MP4 fragment');
    final segment = data[0] * 256 + data[1];
    final count = data[2];
    final sequence = data[3];
    if (count == 0 || sequence == 0 || sequence > count) {
      throw const FormatException('Invalid MP4 fragment sequence');
    }
    if (_segment == null) {
      if (sequence != 1)
        throw const FormatException('Missing first MP4 fragment');
      _segment = segment;
      _count = count;
    }
    if (segment != _segment || count != _count || sequence != _next) {
      throw const FormatException('Missing or reordered MP4 fragment');
    }
    _next++;
    if (sequence == count) {
      _segment = null;
      _next = 1;
    }
    return Uint8List.sublistView(data, 4);
  }
}
