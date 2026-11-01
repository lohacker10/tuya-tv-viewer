# Tuya TV Viewer — prototipo Android TV

Progetto Android TV **non ufficiale** per telecamere associate a **Tuya Smart**. Nessun server locale, NAS o QR code.

## Stato v0.3.0

- ✅ Login diretto Tuya Smart con credenziali digitate sulla stick
- ✅ Salvataggio cifrato opzionale tramite Android Keystore
- ✅ Scelta del dispositivo con telecomando
- ✅ Test P2P/RTC e verifica di raggiungibilità **TCP del relay per una telecamera**
- ⛔ Video live **non ancora disponibile**: la fase di segnalazione MQTT, il protocollo KCP, la decifratura dei frame e la decodifica video non sono ancora implementati

### Test

Installa l'APK dalla [sezione Releases](https://github.com/lohacker10/tuya-tv-viewer/releases), avvia l'app, accedi a Tuya Smart, seleziona una telecamera e premi **TEST RELAY P2P**.

Il test verifica la configurazione e la connessione TCP al relay Tuya. Un esito positivo **non** significa che la riproduzione video funzioni.

## Aggiornamenti Android

Il nome visibile e l'**applicationId** rimangono invariati rispetto alla v0.2 (`it.tuyatv.p2ptest`). Tuttavia, le build debug firmate sui runner GitHub possono usare **certificati diversi**. In quel caso Android non consente l'aggiornamento in-place: occorre disinstallare la versione precedente (perdendo le credenziali locali) e installare la nuova. Per un canale di release definitivo sarà predisposta una firma stabile e privata tramite GitHub Secrets, mai nel repository.

## Sicurezza

- Nessuna password, sessione, token, identificativo telecamera, chiave locale o dato del proprietario viene pubblicato nel repository.
- Le credenziali sono inserite solo sul dispositivo, mai nel workflow o nei log Actions.
- Le configurazioni P2P vengono usate solo in memoria, senza visualizzare o registrare token, host e chiavi.
- L'identità **pubblica dell'applicazione Tuya** impiegata dal protocollo non rappresenta credenziali dell'utente.
- Il codice del protocollo mobile usa quanto documentato dal progetto MIT [AboveColin/tuya-mobile](https://github.com/AboveColin/tuya-mobile), con attribuzione in `ATTRIBUTION.md`.

Versione sperimentale per Android 6 o superiore. Account con MFA o CAPTCHA non supportati. Nessuna affiliazione a Tuya o Action/LSC.
