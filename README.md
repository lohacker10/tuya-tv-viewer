# Tuya TV beta

App Flutter per Fire TV e Android TV: login Tuya con email oppure numero di telefono e password, accesso automatico con credenziali cifrate tramite Android Keystore, griglia 2×2 e selezione di una telecamera a schermo intero. Se l’avvio dello streaming fallisce, l’app prova una volta a rinnovare il login e riavviare le telecamere. La navigazione principale funziona con frecce e tasto OK del telecomando.

## Build

Requisiti: Flutter 3.41 o successivo, Android SDK, JDK 17, Android Gradle Plugin 8.11.1 e Python 3.11. La versione Android minima è API 24 (Android 7); l’APK include ABI ARMv7 e ARM64.

```sh
flutter pub get
flutter build apk --release
```

L’APK di questa beta è firmato con la chiave debug, per installazione manuale e prova. Per distribuirlo stabilmente serve una chiave di firma propria.

## Account e protocollo

Il client parla direttamente con i servizi mobili Tuya usando il progetto open source [tuya-ipc-p2p-sdk](https://github.com/roquerodrigo/tuya-ipc-p2p-sdk), licenza MIT, incluso in `third_party/tuya-ipc-p2p-sdk/`, adattato al profilo dell’app Tuya Smart. Non richiede SDK ufficiale. Inserire il prefisso internazionale per gli account con numero di telefono e la regione dell’account.

Il progetto upstream è dichiarato alpha: l’autore segnala di aver provato in tempo reale solo la regione US e di non aver verificato telecamere H.264. La sua implementazione restituisce immagini MJPEG, e una telecamera accetta un client video alla volta. Servizi, protocollo o parametri Tuya possono cambiare. La prima prova reale serve quindi a confermare login, regione e compatibilità dei modelli installati.
