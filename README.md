# Tuya TV Viewer — prerelease Android TV

Prototipo Android TV non ufficiale per le telecamere associate a **Tuya Smart**. Il collegamento P2P avviene direttamente dall’app; non serve un NAS o un server domestico.

## Stato v0.11.0

- Login Tuya Smart e selezione di una telecamera con telecomando
- Diagnostica MQTT, SDP, relay e record media con log copiabili e dati personali oscurati
- APK unico per ARM 32 bit, ARM 64 bit e x86_64; Android 7 o successivo
- **Video live non confermato:** alcuni dispositivi completano la sessione P2P e inviano record media, ma non è ancora stato ricostruito un frame visualizzabile
- La telecamera Action LSC recente può non rispondere all’offerta SDP
- Griglia 2×2 e riconnessione automatica non ancora disponibili

Scarica la [prerelease v0.11.0](https://github.com/lohacker10/tuya-tv-viewer/releases/tag/v0.11.0). Il package Android resta `it.tuyatv.p2ptest`.

## Installazione e aggiornamenti

Gli APK debug di GitHub Actions possono avere firme diverse. Android richiede la stessa firma per aggiornare un’app già installata: se compare un conflitto, disinstalla la versione precedente prima di installare quella nuova; i dati locali verranno rimossi. Una firma stabile verrà configurata prima della release pubblica.

## Privacy

- Password e credenziali salvate restano sul dispositivo.
- I frame video restano in memoria; non vengono registrati o caricati.
- Il log copiato nasconde nomi, credenziali e identificativi.
- Non pubblicare log grezzi di `adb logcat` o campioni video.

L’app non è affiliata a Tuya, Action o LSC. CAPTCHA e MFA non sono supportati.
