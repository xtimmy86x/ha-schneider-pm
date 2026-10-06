# Schneider PowerLogic — guida italiana

Integrazione personalizzata per leggere i **PM3255** tramite un gateway
Ethernet/RS485. Configurazione da interfaccia, senza YAML.

**Prima versione 0.1.1, da validare sul contatore reale.** I test automatici
utilizzano Home Assistant 2026.9.4 e un simulatore Modbus TCP locale.

## Installazione

Richiede Home Assistant **2026.9.4 o successivo**; la versione verificata dai
test è la 2026.9.4.

Per provare una PR, seleziona il suo branch nella repository, poi **Code → Download
ZIP**. Copia la cartella `custom_components/schneider_pm` in
`/config/custom_components/` e riavvia Home Assistant.

Dopo il merge sarà possibile aggiungere questa repository a HACS come repository
personalizzata, categoria **Integrazione**:
`https://github.com/xtimmy86x/ha-schneider-pm`.
Non è inclusa nel catalogo HACS predefinito e non è ancora stata pubblicata una release.

## Primo avvio

1. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.
2. Cerca **Schneider PowerLogic**.
3. Inserisci nome, IP e porta del gateway.
4. Con Waveshare impostato su **TCP Server / Modbus TCP to RTU**, seleziona
   **Modbus TCP → RTU**. La modalità **RTU su TCP** serve ai convertitori trasparenti.
5. Lascia inizialmente 10 secondi per le misure e 60 secondi per le energie.
6. Aggiungi il PM3255 con indirizzo **1**, assegna un nome e seleziona
   **Aggiungi un altro contatore**.
7. Aggiungi il PM3255 con indirizzo **2** e completa la procedura.

Modello e numero di serie vengono letti per verificare il contatore. I parametri
seriali, per esempio **19200, 8 bit, parità pari, 1 stop**, si configurano sui
contatori e sul gateway e devono corrispondere. Non vengono modificati da HA.

## Aggiungere gli altri contatori

Apri **Configura → Aggiungi contatore**, specifica il nuovo indirizzo e il nome.
Puoi passare da due a cinque contatori senza modificare file. Ogni contatore
compare come dispositivo distinto, collegato al dispositivo gateway.

Da **Configura** puoi anche modificare nome/indirizzo di un contatore, rimuoverlo,
o modificare il collegamento e gli intervalli del gateway. Le modifiche ricaricano
questa istanza dell’integrazione. Gli ID delle entità usano il numero di serie e
rimangono stabili quando cambi IP o nome. Cambiare indirizzo richiede che il
medesimo contatore risponda al nuovo indirizzo.

## Sensori

Sono disponibili **40 sensori di misura/energia per contatore**, più connessione
e ultima lettura riuscita. Sono comprese correnti, tensioni, potenze attive,
reattive e apparenti, fattori di potenza, frequenza, energie importate/esportate
e quattro contatori di energia attiva per tariffa.

Alcune quantità secondarie sono disabilitate inizialmente: puoi abilitarle dalla
lista delle entità del dispositivo. Tutta la mappa supportata viene comunque letta.

Nel pannello **Energia**, usa **Energia attiva importata** per il prelievo e
**Energia attiva esportata** per l’immissione. Sono espresse in kWh e derivano dai
contatori interi a 64 bit dello strumento. Non sommare il totale con i suoi
contatori per tariffa: conteresti due volte gli stessi consumi.

Il fattore di potenza viene convertito dalla codifica Schneider ed esposto come
rapporto con segno. I rapporti TA/TV sono già applicati dal contatore: non viene
aggiunto un altro moltiplicatore.

## Comunicazione

Le richieste sul gateway sono coordinate tramite la connessione condivisa di HA.
Un contatore offline non rende indisponibili gli altri, anche se il suo timeout
può ritardarne temporaneamente le letture sul bus.

Se un contatore smette di rispondere, le sue misure diventano indisponibili.
L’energia non viene mai sostituita da uno zero fittizio; dopo il ripristino della
comunicazione torna disponibile alla successiva lettura energetica riuscita.
Il sensore **Connessione** indica il risultato dell’ultima lettura delle misure
istantanee; **Ultima lettura riuscita** indica quando quella lettura è avvenuta.

La configurazione già salvata si carica anche con contatori offline e tenta
automaticamente il recupero. Le nuove aggiunte richiedono invece che il
contatore risponda. I timeout sono gestiti dalla connessione Modbus di HA.

## Prima prova sull’impianto

Confronta tensioni, correnti, potenze ed energie con il display dei PM3255.
Verifica entrambi i dispositivi. In caso di errori, scarica la diagnostica dalla
pagina dell’integrazione: esclude IP, nomi e numeri di serie, ma conserva gli
indirizzi Modbus e lo stato delle letture.

Questa versione esegue solo letture: non azzera contatori, non modifica TA/TV o
tariffe e non comanda uscite. Non importa lo storico memorizzato nello strumento.

Per dettagli tecnici e sviluppo: [README inglese](README.md).
