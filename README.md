# Tuya TV beta 4

App Flutter per Android TV e Fire TV: login Tuya con email/telefono e password, accesso automatico con credenziali cifrate tramite Android Keystore, quattro dirette in griglia 2×2 e telecamera selezionata a schermo intero. Frecce e OK/Enter selezionano una telecamera; BACK torna alla griglia.

La beta 4 usa il protocollo WebRTC del portale **Tuya EU**. Dopo il login mobile, autorizza automaticamente una sessione web distinta con il token previsto dal flusso QR di Tuya: **non occorre mostrare o scansionare un QR**. Il SID mobile rimane sul gateway mobile; password e sessioni non vengono inviate a servizi propri. Non richiede AppKey, progetto sviluppatore o SDK ufficiale Tuya.

Il player richiede il flusso secondario H.264 per contenere il carico di quattro decoder. Anche a schermo intero mantiene la qualità del flusso secondario; l’audio è disabilitato. Alla pausa chiude le sessioni video; al ritorno le riapre. Un flusso fermo viene riconnesso e le sessioni mobile/web scadute vengono rinnovate automaticamente.

## Verifica reale

Testata il 2 novembre 2026 su un telefono Android 16 con quattro telecamere dell’account: quattro flussi H.264 simultanei a 640×360, contatori di fotogrammi in aumento per diversi minuti, selezione a schermo intero, navigazione con frecce/Enter/BACK e riapertura senza reinserire le credenziali.

Fire TV e Android TV di vecchia generazione restano da verificare su hardware reale. Questa beta usa il portale europeo e il percorso WebRTC V3 (`p2pType=4`); altre regioni, H.265 senza flusso secondario H.264 e dispositivi con altri protocolli non sono verificati. Le API private Tuya possono cambiare.

## Build e test

Requisiti: Flutter 3.41+, Android SDK, JDK 17 e Python 3.11. Android minimo API 24 (Android 7); l’APK release include ARMv7 e ARM64.

```sh
flutter pub get
flutter analyze --no-pub
python -m unittest discover -s test -p 'test_*.py' -v
flutter build apk --release --target-platform android-arm,android-arm64
```

GitHub Actions esegue analisi, test e compilazione e allega l’APK alla prerelease. La firma debug è destinata alle prove; build firmate con chiavi diverse possono richiedere la disinstallazione della versione precedente. La build debug locale usa il suffisso `.dev`, così può convivere con la release senza cancellarne i dati.

## Componenti

Il login e la scoperta delle telecamere derivano dal progetto MIT [tuya-ipc-p2p-sdk](https://github.com/roquerodrigo/tuya-ipc-p2p-sdk), conservato in `third_party/tuya-ipc-p2p-sdk/` e adattato al profilo dell’app Tuya Smart. La decodifica usa [flutter_webrtc](https://pub.dev/packages/flutter_webrtc). La segnalazione web è una implementazione indipendente del protocollo osservato nel portale; non include i bundle JavaScript proprietari del portale o l’APK Tuya.
