# NIFTY Options 1-Minute Trader Starter Script
param (
    [string]$Strategy = "",
    [string]$AiMode = "chat",
    [int]$Lots = 1,
    [int]$TrailingInterval = 5,
    [switch]$Once = $false,
    [switch]$IgnoreFeedHealth = $false,
    [switch]$ListStrategies = $false,
    [switch]$Live = $false
)

if ($ListStrategies) {
    python nifty_trader_scheduler.py --list-strategies
    exit
}

$cmdArgs = @("--interval", "60", "--trailing-interval", "$TrailingInterval", "--lots", "$Lots")

if ($Live) {
    $cmdArgs += "--live"
}
if ($Strategy) {
    $cmdArgs += @("--strategy", $Strategy)
}
if ($AiMode) {
    $cmdArgs += @("--ai-mode", $AiMode)
}
if ($Once) {
    $cmdArgs += "--once"
}
if ($IgnoreFeedHealth) {
    $cmdArgs += "--ignore-feed-health"
} else {
    $cmdArgs += "--wait-until-market-open"
}

Write-Host "Starting NIFTY Options Scheduler with profile: $(if ($Strategy) { $Strategy } else { 'Active (from config)' })..." -ForegroundColor Cyan
python nifty_trader_scheduler.py @cmdArgs
