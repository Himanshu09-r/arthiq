# Arthiq extraction eval

27 labelled sentences (Hinglish, English, Marathi, Gujarati, Tamil). Real Sarvam LLM (sarvam-105b), schema-validated extraction, before any validation or read-back.

**Fully correct: 27/27 (100%)**   |   avg 1.0s, max 3.3s per sentence

| Field | Correct | Checked | Accuracy |
|---|---|---|---|
| intent | 27 | 27 | 100% |
| customer | 25 | 25 | 100% |
| items | 12 | 12 | 100% |
| amount | 13 | 13 | 100% |
| correction | 3 | 3 | 100% |

| Language | Fully correct | Cases |
|---|---|---|
| hi | 13 | 13 |
| en | 5 | 5 |
| mr | 4 | 4 |
| gu | 3 | 3 |
| ta | 2 | 2 |

Read-back and a spoken 'yes' still stand between every extraction and the ledger, so a miss here is caught by the shopkeeper before anything is saved.
