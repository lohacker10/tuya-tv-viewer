# Tuya TV Viewer — prototipo Android TV

Progetto Android TV **non ufficiale** per telecamere associate a **Tuya Smart**. Nessun NAS, server domestico o QR code.

## Stato v0.4.0

- Login diretto Tuya Smart sul dispositivo e salvataggio locale cifrato opzionale
- Scelta telecamera con telecomando Android TV
- Verifica configurazione IPC/RTC e connessione TCP al relay Tuya
- **TEST MQTT:** prova di autenticazione TLS/MQTT 3.1.1 sul canale di segnalazione P2P, senza inviare SDP, comandare o aprire video
- **COPIA LOG:** copia negli appunti del dispositivo il risultato diagnostico, con nomi, credenziali e identificativi oscurati
- **Non disponibile:** preview live, protocollo KCP, SDP offer/answer, decodifica H.264

### Come provare

Scarica l'APK v0.4 dalla [sezione Releases](https://github.com/lohacker10/tuya-tv-viewer/releases).
Avvia l'app, accedi al tuo account Tuya Smart e premi **TEST MQTT**. Premi poi **COPIA LOG** per condividere il testo diagnostico ripulito.

Il test MQTT verifica solo che il broker consenta l'autenticazione; anche in caso di successo, **la diretta video non è stata ancora verificata**. Lo schema di autenticazione MQTT è sperimentale e potrebbe essere differente per alcune versioni Tuya Smart: un rifiuto non dimostra che le credenziali dell'account siano errate.

## Identità dell'app e aggiornamenti

Il nome Android e il package restano invariati rispetto alla v0.2: `it.tuyatv.p2ptest`.
La firma debug di GitHub Actions viene creata su runner temporanei e può cambiare. **Android richiede stessa firma E stesso package per installare un APK come aggiornamento.** Se l'installazione segnala un conflitto, disinstalla la versione precedente prima di installare l'APK nuovo (perderai i dati locali).
Per la release definitiva bisognerà configurare una firma persistente salvata *privatamente* nei GitHub Actions secrets, mai pubblicata nel repository.

## Sicurezza e privacy

- Nessun account, password, sessione, token, ID delle telecamere, chiave locale o indirizzo privato dell'utente viene caricato nel codice GitHub.
- Le credenziali sono inserite unicamente sulla stick e possono essere salvate tramite Android Keystore.
- Il log del test MQTT mostra soltanto stati e categorie di errore. Il pulsante COPIA LOG rimuove nomi e identificativi dai test diagnostici.
- Non sono inviati log personali a GitHub; i log vengono mostrati e copiati soltanto sul dispositivo.
- Il protocollo mobile è basato sul progetto open source MIT [AboveColin/tuya-mobile](https://github.com/AboveColin/tuya-mobile); si veda `ATTRIBUTION.md`.
- Android 6+; CAPTCHA/MFA non supportati.

Nessuna affiliazione a Tuya o Action/LSC. **Non** allegare output non oscurati di `adb logcat` in issue pubbliche.
