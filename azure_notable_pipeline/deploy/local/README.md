# Local Azure emulators

This stack starts Azurite and the Microsoft Cosmos DB Linux vNext emulator. It
does not start the Function host because Azure AI Foundry, Azure OpenAI, Search,
and Key Vault remain external runtime dependencies.

Prerequisites are Docker Compose, Python 3.12, and the dependencies from this
project's `requirements.txt`. The bootstrap is safe to rerun.

```bash
cp deploy/local/local.env.example deploy/local/local.env
python3 -m pip install -r requirements.txt
./deploy/local/bootstrap.sh
```

From PowerShell:

```powershell
Copy-Item deploy/local/local.env.example deploy/local/local.env
python -m pip install -r requirements.txt
./deploy/local/bootstrap.ps1
```

Azurite uses ports 10000-10002. Cosmos uses 8081 for the API, 8080 for health,
and 1234 for Data Explorer. Named volumes preserve state. To reset local data,
run `docker compose -f deploy/local/docker-compose.yml down --volumes`.

`local.env.example` contains only well-known public emulator credentials. Never
reuse them for a remote service.
