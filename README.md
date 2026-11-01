# Tuya TV Viewer — test di login

Prototipo Android TV **non ufficiale** per verificare il login a **Tuya Smart** senza NAS.

- Nessuna password, sessione, token, ID telecamera o dato personale è presente nel repository.
- Le credenziali vengono inserite **esclusivamente sul dispositivo** e possono essere conservate cifrate tramite Android Keystore.
- Questa versione non riproduce ancora il video: verifica soltanto l'autenticazione e, se disponibile, la lettura dei nomi dei dispositivi.
- Il protocollo di autenticazione è sperimentale: un login rifiutato non implica necessariamente una password sbagliata.

Per ottenere l'APK aprire la sezione **Actions** del repository e scaricare l'artifact della build `Build APK` completata. Il file `app-debug.apk` è un APK di test, non un'app pubblicata ufficialmente.

## Avviso su compatibilità e sicurezza

I dettagli del protocollo mobile sono derivati dal progetto MIT [AboveColin/tuya-mobile](https://github.com/AboveColin/tuya-mobile). Le identità e le chiavi *dell'applicazione Tuya* pubblicate in quel progetto non sono credenziali del proprietario delle telecamere e possono cambiare. Nessun segreto personale deve essere inviato su GitHub, nei log Actions o nelle issue.

Versione sperimentale per Android TV / Google TV (Android 6+). Non supporta captcha e MFA.