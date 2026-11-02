# Tuya TV beta 5

App Flutter per Fire TV e Android TV: login Tuya con email/telefono e password, credenziali cifrate tramite Android Keystore e accesso automatico.

La home contiene soltanto quattro anteprime SD, senza titoli, barre o guide. Il bordo evidenzia la telecamera selezionata. Frecce e OK/Enter aprono la telecamera a tutto schermo, richiedendo il flusso principale **HD con audio**; BACK ripristina la griglia silenziosa. Durante il fullscreen viene mantenuta una sola connessione video. Il display resta acceso mentre l’app è visibile.

Il menu del telecomando permette di riconnettere o disconnettere l’account senza aggiungere pulsanti alla home. Page Up/Down cambiano pagina se l’account contiene più di quattro telecamere.

## Compatibilità

**Minimo Android 7/API 24**, ARMv7 o ARM64. Fire OS 5 è basato su Android 5.1/API 22 e non può installare questa build. Abbassare soltanto `minSdk` non basta: il runtime Python e le dipendenze attuali richiedono API 24. Per supportare Fire OS 5 servirebbe una variante legacy con componenti diversi.

Per sostituire lo stick, scegliere un modello Android/Fire OS compatibile, ad esempio **Fire TV Stick 4K Max di seconda generazione (2023), Fire OS 8**. I modelli con **Vega OS**, tra cui Fire TV Stick 4K Select, non eseguono questo APK. Verificare sempre modello e sistema operativo prima dell’acquisto.

Fonti: [sistemi Fire TV](https://developer.amazon.com/docs/fire-tv/fire-os-overview.html), [identificazione dei modelli](https://developer.amazon.com/docs/device-specs/identify-fire-tv-devices.html), [requisiti Chaquopy](https://chaquo.com/chaquopy/doc/current/android.html).

## Video e autenticazione

La griglia richiede il flusso secondario H.264. Il fullscreen richiede il principale: H.264 via WebRTC oppure H.265 tramite il canale MP4 frammentato del portale e il decoder Android. Per quest’ultimo il flusso viene inoltrato al player esclusivamente su loopback, con buffer limitato; le durate AAC-LC errate e i timestamp vengono normalizzati senza ricodificare i dati video/audio. Non vengono registrate riprese sul dispositivo.

Se l’HD non parte o il decoder fallisce, l’app ripristina SD con audio abilitato quando disponibile. La risoluzione e l’audio effettivi dipendono dalla telecamera e dal decoder. Su una TV reale occorre verificare soprattutto H.265 e audio HDMI.

Il login mobile autorizza automaticamente una sessione separata del portale **Tuya EU**, senza mostrare o scansionare QR. Non serve AppKey né SDK ufficiale Tuya. Password e SID mobile restano nel client mobile; il portale riceve la propria sessione web. Le sessioni scadute vengono rinnovate automaticamente. Al ritorno dall’app in pausa vengono riaperti i flussi della vista corrente.

La beta usa il percorso WebRTC V3 (`p2pType=4`); altre regioni e protocolli non sono verificati. Le API private Tuya possono cambiare.

## Verifica reale

Provata su un telefono Android 16 con quattro anteprime 640×360, selezione tramite telecomando/Enter/BACK e fullscreen H.264 a 1920×1080 con pacchetti audio ricevuti. Provato anche il percorso H.265 a 2304×1296 con una traccia audio AAC nel contenitore MP4. Fire TV e audio HDMI richiedono ancora una prova sul dispositivo reale.

## Build e verifiche

Requisiti: Flutter 3.41+, Android SDK, JDK 17, Python 3.11.

```sh
flutter pub get
flutter analyze --no-pub
python -m unittest discover -s test -p 'test_*.py' -v
dart run test/fmp4_fragments_check.dart
flutter build apk --release --target-platform android-arm,android-arm64
```

GitHub Actions esegue analisi, test e build e allega l’APK alla prerelease. Firma debug per prove manuali: con chiavi diverse potrebbe servire disinstallare la beta precedente. La build debug locale usa `.dev` per convivere con la release conservandone i dati.

## Componenti

Login e scoperta delle telecamere derivano da [tuya-ipc-p2p-sdk](https://github.com/roquerodrigo/tuya-ipc-p2p-sdk), MIT, incluso in `third_party/tuya-ipc-p2p-sdk/`. I player usano [flutter_webrtc](https://pub.dev/packages/flutter_webrtc) e [video_player](https://pub.dev/packages/video_player). La segnalazione web è una implementazione indipendente del protocollo osservato; non include i bundle proprietari del portale o l’APK Tuya.
