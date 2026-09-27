# Relance le serveur de controle et tous les bots connus (config/*.yml) -
# execute automatiquement a l'ouverture de session Windows (tache planifiee
# "TradingBot_AutoStart") pour repartir tout seul apres un redemarrage
# (ex: mise a jour Windows nocturne, coupure de courant). Sans ca, un
# redemarrage laisse tous les bots a l'arret jusqu'a une relance manuelle -
# constate le 2026-09-16 (redemarrages Windows Update vers 23h45, bots
# repartis seulement a 9h55 le lendemain matin par relance manuelle).

$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\youen\Documents\finance-perso\trading-bot"
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
$logFile = Join-Path $root "logs\autostart.log"

function Write-Log($message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
    Add-Content -Path $logFile -Value $line
}

Write-Log "Autostart declenche."

# Demarre le serveur de controle - verrou anti-doublon cote Python
# (control_server.lock), donc sans risque meme s'il tourne deja.
# Sorties du serveur conservees : le 2026-09-27 il a refuse de demarrer (verrou
# perime, PID reattribue apres redemarrage) et le message s'est perdu dans une
# fenetre cachee - seul "indisponible apres 60s" restait dans ce journal.
Start-Process -FilePath $python -ArgumentList "-u -m tradingbot.control_server" -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root "logs\control_server_autostart.out.log") `
    -RedirectStandardError (Join-Path $root "logs\control_server_autostart.err.log")

# Attend que le serveur reponde (jusqu'a 60s) plutot qu'un delai fixe -
# Windows peut encore initialiser le reseau juste apres l'ouverture de session.
# `curl.exe` (natif Windows 10+, System32) plutot que Invoke-RestMethod :
# Invoke-RestMethod/-WebRequest en PowerShell 5.1 s'appuient sur le moteur
# WinINet/IE, qui echoue silencieusement (timeout systematique) dans le
# contexte non-interactif d'une tache planifiee sans profil utilisateur
# pleinement charge - bug reel constate le 2026-09-16 (60 tentatives, 0 succes,
# alors que le meme appel fonctionnait instantanement en session interactive).
$curl = "$env:SystemRoot\System32\curl.exe"
# EF-86 : si le serveur est en HTTPS (certificat dans .env), lui parler en
# HTTPS. `-k` : appel en boucle locale vers notre propre certificat
# auto-signe, il n'y a personne a authentifier entre les deux.
$base = "http://localhost:8765"
$tlsFlag = @()
if (Select-String -Path (Join-Path $root ".env") -Pattern '^DASHBOARD_TLS_CERT=.+' -Quiet) {
    $base = "https://localhost:8765"
    $tlsFlag = @("-k")
}
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    & $curl -s @tlsFlag -m 2 -o NUL -w "%{http_code}" "$base/api/list-configs" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    $err = Get-Content (Join-Path $root "logs\control_server_autostart.err.log") -Tail 3 -ErrorAction SilentlyContinue
    Write-Log "Serveur de controle indisponible apres 60s - abandon. Sortie d'erreur du serveur : $($err -join ' | ')"
    exit 1
}
Write-Log "Serveur de controle pret."

# Lance chaque bot connu - l'API renvoie proprement une erreur 409 (ignoree
# ici) pour ceux deja actifs, jamais de doublon. Corps JSON ecrit dans un
# fichier temporaire et transmis via `--data-binary "@fichier"` plutot que
# `-d $body` en ligne de commande : passer le JSON directement comme
# argument produisait un corps corrompu ("JSON invalide" cote serveur) dans
# ce contexte non-interactif (encodage/echappement dependant du shell qui
# invoque curl.exe) - bug reel constate le 2026-09-16, le fichier temporaire
# contourne le probleme quelle que soit sa cause exacte.
Get-ChildItem (Join-Path $root "config\*.yml") | ForEach-Object {
    $configPath = "config/$($_.Name)"
    $tmpFile = [System.IO.Path]::GetTempFileName()
    Set-Content -Path $tmpFile -Value "{`"config_path`":`"$configPath`"}" -NoNewline -Encoding ascii
    $response = & $curl -s @tlsFlag -m 10 -X POST -H "Content-Type: application/json" --data-binary "@$tmpFile" "$base/api/start-bot" 2>$null
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
    Write-Log "$configPath -> $response"
}
Write-Log "Autostart termine."
